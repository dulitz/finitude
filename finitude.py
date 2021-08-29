"""
finitude.py

Exports runtime data from a Carrier Infinity or Bryant Evolution HVAC system
to Prometheus.

Prometheus can query us very often (every second if desired) because we are
constantly listening to the HVAC's RS-485 bus and updating our internal state.
"""

import logging, prometheus_client, re, threading, time, yaml

from queue import SimpleQueue, Empty

import frames
import registers
import sniffserver


class RequestError(Exception):
    pass


LOGGER = logging.getLogger('finitude')


class HvacMonitor:
    FRAME_COUNT = prometheus_client.Counter('finitude_frames',
                                            'number of frames received',
                                            ['name', 'source', 'dest', 'func', 'register'])
    IS_SYNC = prometheus_client.Gauge('finitude_synchronized',
                                      '1 if reader is synchronized to bus', ['name'])
    DESYNC_COUNT = prometheus_client.Counter('finitude_desyncs',
                                             'number of desynchronizations', ['name'])
    RECONNECT_COUNT = prometheus_client.Counter('finitude_reconnects',
                                                'number of stream reconnects', ['name'])
    STORED_FRAMES = prometheus_client.Gauge('finitude_stored_frames',
                                            'number of frames stored', ['name'])
    FRAME_SEQUENCE_LENGTH = prometheus_client.Gauge('finitude_frame_sequence_length',
                                                    'length of sequence', ['name'])
    DEVINFO = prometheus_client.Info('finitude_device',
                                     'info table from each device on the bus',
                                     ['name', 'device'])
    HVACSTATE = prometheus_client.Enum('finitude_state_enum',
                                       'state of HVAC system',
                                       ['name'], states=['off', 'heat', 'cool'])
    TEMPSENSORS = prometheus_client.Gauge('finitude_temp_sensor',
                                          'temp reported by sensor',
                                          ['name', 'device', 'state', 'sensor_type'])
    TABLE_NAME_MAP = {
        'AirHandler06': 'airhandler',
        'AirHandler16': 'airhandler',
        'TStatCurrentParams': '',
        'TStatZoneParams': '',
        'TStatVacationParams': 'vacation',
        'HeatPump01': 'heatpump',
        'HeatPump02': 'heatpump',
        }
    GAUGES = {}
    CV = threading.Condition()
    NUM_ZONES = 8

    def __init__(self, name, path):
        self.name, self.path = name, path
        self.stream, self.bus = None, None
        self.synchronized = False
        self.pending_frame = None
        self.send_queue = SimpleQueue()

        self.register_to_rest = {}
        self.framedata_to_index = {}
        self.frames = []  # squashed
        self.store_frames = False
        self.zone_to_name = ['' for x in range(HvacMonitor.NUM_ZONES)]
        HvacMonitor.IS_SYNC.labels(name=self.name).set_function(lambda s=self: s.synchronized)
        HvacMonitor.STORED_FRAMES.labels(name=self.name).set_function(lambda s=self: len(s.framedata_to_index))
        HvacMonitor.FRAME_SEQUENCE_LENGTH.labels(name=self.name).set_function(lambda s=self: len(s.frames))

    def open(self):
        LOGGER.info(f'connecting to {self.name} at {self.path}')
        self.stream = frames.StreamFactory(self.path)
        self.bus = frames.Bus(self.stream, report_crc_error=self._report_crc_error)

        HvacMonitor.RECONNECT_COUNT.labels(name=self.name).inc()

    def process_frame(self, frame):
        self.synchronized = True
        is_write = frame.func == frames.Function.WRITE
        is_ack = frame.func == frames.Function.ACK06
        if frame.length >= 3 and (is_write or is_ack):
            try:
                (name, values, rest) = frame.parse_register()
            except IndexError as e:  # then it failed to parse
                name = frame.get_printable_register()
                values = { 'ERROR': f'parsing: {e}' }
                rest = frame.data
                LOGGER.warning(f'failed to parse {name} with {rest}: {e}')
            (basename, paren, num) = name.partition('(')
            addr = frame.source if is_ack else frame.dest
            if values:
                if name == 'DeviceInfo(0104)':
                    if is_ack:
                        sa = frames.ParsedFrame.get_printable_address(frame.source)
                        self.DEVINFO.labels(name=self.name, device=sa).info(values)
                elif name == 'Temperatures(0302)':
                    for s in values['TempSensors']:
                        sa = frames.ParsedFrame.get_printable_address(frame.source)
                        if s['State'] == 1:
                            state = 'present'
                        elif s['State'] == 4:
                            state = 'missing'
                        else:
                            state = str(s['State'])
                        if s['Type'] >= 1 and s['Type'] <= 8:
                            stype = f'Zone{s["Type"]}'
                        elif s['Type'] == 0x11:
                            stype = 'OAT'
                        elif s['Type'] == 0x12:
                            stype = 'OCT'
                        elif s['Type'] == 0x14:
                            stype = 'LAT'
                        elif s['Type'] == 0x1c:
                            stype = 'HPT'
                        elif s['Type'] == 0x30:
                            stype = 'suction'
                        elif s['Type'] == 0x45:
                            stype = 'discharge'
                        elif s['Type'] == 0x4a:
                            stype = 'superheat'
                        else:
                            stype = str(s['Type'])
                        temp = s['TempTimes16']
                        self.TEMPSENSORS.labels(
                            name=self.name, device=sa, state=state, sensor_type=stype
                        ).set(temp / 16.0)
                else:
                    tablename = self.TABLE_NAME_MAP.get(basename, basename)
                    for (k, v) in values.items():
                        if is_ack and name == 'TStatZoneParams(3b03)':
                            self._set_zonename(k, v)
                        self._set_gauge(tablename, k, v)
            devicestr = frames.ParsedFrame.get_printable_address(addr)
            return (f'{devicestr}_{name}', rest)
        return (None, None)

    def set_store_frames(self, storethem):
        """When storethem is True, run() will call store_frame() for each
        frame it processes.
        """
        if storethem:
            self.register_to_rest = {}
            self.framedata_to_index = {}
            self.frames = []  # squashed
        self.store_frames = storethem

    def store_frame(self, frame, name, rest):
        """If rest is a statechange on name, store the frame."""
        (lastrest, lastframe) = self.register_to_rest.get(name, (None, None))
        self.register_to_rest[name] = (rest, frame)
        if (not rest) or lastrest == rest:
            return  # we parsed it all into Prometheus so nothing to store here
        index = self.framedata_to_index.get(frame.data)
        if index is None:
            index = len(self.framedata_to_index) + 1
            self.framedata_to_index[frame.data] = index
        w = ''
        if frame.func == frames.Function.WRITE:
            w = f'WRITE({frames.ParsedFrame.get_printable_address(frame.source)}):'
        self.frames.append((time.time(), w + name, index))

    def send_with_response(self, frame, timeout=1):
        """Send frame. Wait up to timeout seconds for a response and return it.
        Returns None on timeout or if the frame could not be sent due to a
        synchronization issue.
        """
        q = SimpleQueue()
        self.send_queue.put((frame, q, time.time() + timeout))
        return q.get()

    def _process_send_queue(self, ackframe):
        if self.pending_frame:
            (pf, pq, pexpires) = self.pending_frame
            if pf.source == ackframe.dest and pf.dest == ackframe.source:
                pq.put(ackframe)
                self.pending_frame = None
            elif pexpires < time.time():
                pq.put(None)
                self.pending_frame = None
        if ackframe.func == frames.Function.ACK06 and not self.pending_frame:
            try:
                pend = self.send_queue.get_nowait()
                if not self.bus.write(pend[0].framebytes):
                    LOGGER.info(f'{self.name} unable to write {pend[0]}; retrying')
                    self.send_queue.put(pend)  # retry
                else:
                    self.pending_frame = (frames.ParsedFrame(pend[0].framebytes), pend[1], pend[2])
            except Empty:
                pass

    ZONE_RE = re.compile(r'Zone([1-8])(.*)')
    def _set_zonename(self, itemname, v):
        zmatch = HvacMonitor.ZONE_RE.match(itemname)
        zone = int(zmatch.group(1)) if zmatch else None
        if isinstance(v, str):
            if zone and zmatch.group(2) == 'Name':
                # then itemname is a zone name, e.g. Zone1Name
                with HvacMonitor.CV:
                    if self.zone_to_name[zone-1] != v:
                        LOGGER.info(f'{self.name} zone {zone} has name {v}')
                        self.zone_to_name[zone-1] = v

    def _set_gauge(self, tablename, itemname, v, labelpair=None):
        if isinstance(v, list):
            if v and (v[0].get('Tag') is not None) and labelpair is None:
                for d in v:
                    tag = str(d['Tag'])
                    for (subkey, val) in d.items():
                        if subkey != 'Tag':
                            self._set_gauge(tablename, f'{itemname}_{subkey}', val, ('tag', tag))
            return
        elif isinstance(v, str):
            # TODO: emit as a label?
            return
        desc = ''
        divisor = 1
        (pre, times, post) = itemname.partition('Times7')
        if times and not post:
            itemname = pre
            divisor = 7.0
        (pre, times, post) = itemname.partition('Times16')
        if times and not post:
            itemname = pre
            divisor = 16.0
        for words in ['RPM', 'CFM']:
            (pre, word, post) = itemname.partition(words)
            if word:
                itemname = f'{pre}{"_" if pre else ""}{word.lower()}{"_" if post else ""}{post}'
                break
        with HvacMonitor.CV:
            def getgauge(name, desc, morelabels=[]):
                name = name.replace('(', '').replace(')', '')
                gauge = HvacMonitor.GAUGES.get(name)
                if gauge is None:
                    gauge = prometheus_client.Gauge(name, desc, ['name'] + morelabels)
                    HvacMonitor.GAUGES[name] = gauge
                return gauge

            if itemname == 'Mode' and not tablename:
                assert not labelpair, labelpair
                # the lower 5 bits are the mode; upper bits are stage number
                mode = v & 0x1f
                modegauge = getgauge('finitude_mode', 'current operating mode', ['state'])
                s = registers.HvacMode(mode).name
                modegauge.labels(name=self.name, state=s).set(mode)
                stage = v >> 5
                stagegauge = getgauge('finitude_stage', 'current operating stage')
                stagegauge.labels(name=self.name).set(stage)
                # FIXME: state and enum are incorrect if mode is AUTO and we are cooling
                state = stage * (-1 if mode == registers.HvacMode.COOL else 1)
                stateg = getgauge('finitude_state', 'current operating state')
                stateg.labels(name=self.name).set(state)
                s = 'off' if state == 0 else 'cool' if state < 0 else 'heat'
                HvacMonitor.HVACSTATE.labels(name=self.name).state(s)
            else:
                zmatch = HvacMonitor.ZONE_RE.match(itemname)
                zone = int(zmatch.group(1)) if zmatch else None
                iname = zmatch.group(2) if zmatch else itemname
                if tablename:
                    gaugename = f'finitude_{tablename}_{iname.lower()}'
                else:
                    gaugename = f'finitude_{iname}'
                if zone:
                    assert not labelpair, labelpair
                    gauge = getgauge(gaugename, desc, morelabels=['zone', 'zonename'])
                    zname = self.zone_to_name[zone-1].strip(' \0')
                    if zname:
                        gauge.labels(
                            name=self.name, zone=str(zone), zonename=zname
                        ).set(v / divisor)
                    else:
                        LOGGER.debug(f'ignoring {gaugename} in {zone}: no zonename')
                else:
                    if labelpair:
                        gauge = getgauge(gaugename, desc, morelabels=[labelpair[0]])
                        kwargs = { 'name': self.name, labelpair[0]: labelpair[1] }
                        gauge.labels(**kwargs).set(v / divisor)
                    else:
                        gauge = getgauge(gaugename, desc)
                        gauge.labels(name=self.name).set(v / divisor)

    def _report_crc_error(self):
        if self.synchronized:
            self.synchronized = False
            HvacMonitor.DESYNC_COUNT.labels(name=self.name).inc()

    def run(self):
        self.open()  # at startup, fail if we can't open
        while True:
            try:
                if self.stream is None:
                    self.open()
                frame = frames.ParsedFrame(self.bus.read())
                (name, rest) = self.process_frame(frame)
                if self.store_frames:
                    HvacMonitor.FRAME_COUNT.labels(
                        name=self.name,
                        source=frames.ParsedFrame.get_printable_address(frame.source),
                        dest=frames.ParsedFrame.get_printable_address(frame.dest),
                        func=frame.get_function_name(),
                        register=name or frame.get_register() or 'unknown',
                    ).inc()
                    self.store_frame(frame, name, rest)
                else:
                    HvacMonitor.FRAME_COUNT.labels(name=self.name).inc()
                if frame.func in (frames.Function.ACK06,
                                  frames.Function.ACK02,
                                  frames.Function.NACK):
                    self._process_send_queue(frame)
            except (OSError, frames.CarrierError):
                LOGGER.exception('exception in frame processor, reconnecting')
                self.stream, self.bus = None, None
                time.sleep(1) # rate limiting

class Finitude:
    def __init__(self, config):
        self.config = config
        port = self.config.get('port')
        if not port:
            self.config['port'] = 8000
        self.monitors = []

    def start_metrics_server(self, port=0):
        if not port:
            port = self.config['port']
        LOGGER.info(f'serving metrics on port {port}')
        prometheus_client.start_http_server(port)

    def start_listeners(self, listeners={}):
        if not listeners:
            listeners = self.config['listeners']
        self.monitors = [ HvacMonitor(name, path) for (name, path) in listeners.items() ]
        for m in self.monitors:
            threading.Thread(target=m.run, name=m.name).start()

    def start_sniffserver(self, port=0):
        if not port:
            port = self.config.get('sniffserver', 0)
        if port:
            for m in self.monitors:
                m.set_store_frames(True)
                # the sniffserver itself may call set_store_frames()
            sniffserver.start_sniffserver(port, self.monitors)


def main(args):
    logging.basicConfig(level=logging.INFO)
    configfile = 'finitude.yml'
    if len(args) > 1:
        configfile = args[1]

    config = yaml.safe_load(open(configfile, 'rt')) or {}
    if config:
        LOGGER.info(f'using configuration file {configfile}')
    else:
        LOGGER.info(f'configuration file {configfile} was empty; ignored')
    f = Finitude(config)
    f.start_metrics_server()
    f.start_listeners()
    f.start_sniffserver()
    # process will not exit until all threads terminate, which is never


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
