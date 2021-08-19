"""
finitude.py

Exports runtime data from a Carrier Infinity or Bryant Evolution HVAC system
to Prometheus.

Prometheus can query us very often (every second if desired) because we are
constantly listening to the HVAC's RS-485 bus and updating our internal state.
"""

import logging, prometheus_client, re, threading, time, yaml

import frames
import sniffserver


class RequestError(Exception):
    pass


LOGGER = logging.getLogger('finitude')


class HvacMonitor:
    FRAME_COUNT = prometheus_client.Counter('finitude_frames',
                                            'number of frames received', ['name'])
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
            (name, values, rest) = frame.parse_register()
            (basename, paren, num) = name.partition('(')
            addr = frame.dest
            if values and is_ack:
                addr = frame.source
                if basename == 'DeviceInfo':
                    self.DEVINFO.labels(name=self.name, device=frames.ParsedFrame.get_printable_address(frame.source)).info(values)
                else:
                    tablename = self.TABLE_NAME_MAP.get(basename, basename)
                    for (k, v) in values.items():
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
        if not rest:
            return  # we parsed it all, so nothing to store
        (lastrest, lastframe) = self.register_to_rest.get(name, (None, None))
        if lastrest == rest:
            return
        self.register_to_rest[name] = (rest, frame)
        index = self.framedata_to_index.get(frame.data)
        if index is None:
            index = len(self.framedata_to_index) + 1
            self.framedata_to_index[frame.data] = index
        w = ''
        if frame.func == frames.Function.WRITE:
            w = f'WRITE({frames.ParsedFrame.get_printable_address(frame.source)}):'
        self.frames.append((time.time(), w + name, index))

    ZONE_RE = re.compile(r'Zone([1-8])(.*)')
    def _set_gauge(self, tablename, itemname, v):
        zmatch = HvacMonitor.ZONE_RE.match(itemname)
        zone = int(zmatch.group(1)) if zmatch else None
        if isinstance(v, str):
            if zone and zmatch.group(2) == 'Name' and not tablename:
                # then itemname is a zone name, e.g. Zone1Name
                with HvacMonitor.CV:
                    if self.zone_to_name[zone-1] != v:
                        LOGGER.info(f'{self.name} zone {zone} has name {v}')
                        self.zone_to_name[zone-1] = v
            # TODO: emit as a label?
            return
        desc = ''
        divisor = 1
        (pre, times, post) = itemname.partition('Times7')
        if times and not post:
            itemname = pre
            divisor = 7
        (pre, times, post) = itemname.partition('Times16')
        if times and not post:
            itemname = pre
            divisor = 16
        for words in ['RPM', 'CFM']:
            (pre, word, post) = itemname.partition(words)
            if word:
                itemname = f'{pre}{"_" if pre else ""}{word.lower()}{"_" if post else ""}{post}'
                break
        nonzone = zmatch.group(2) if zmatch else itemname
        if tablename:
            gaugename = f'finitude_{tablename}_{nonzone.lower()}'
        else:
            gaugename = f'finitude_{nonzone}'
        with HvacMonitor.CV:
            def getgauge(name, desc, morelabels=[]):
                gauge = HvacMonitor.GAUGES.get(name)
                if gauge is None:
                    gauge = prometheus_client.Gauge(name, desc, ['name'] + morelabels)
                    HvacMonitor.GAUGES[name] = gauge
                return gauge

            if itemname == 'Mode' and not tablename:
                # the lower 5 bits are the mode; upper bits are stage number
                mode = v & 0x1f
                modegauge = getgauge('finitude_mode', 'current operating mode', ['state'])
                s = frames.HvacMode(mode).name
                modegauge.labels(name=self.name, state=s).set(mode)
                stage = v >> 5
                stagegauge = getgauge('finitude_stage', 'current operating stage')
                stagegauge.labels(name=self.name).set(stage)
                # FIXME: state and enum are incorrect if mode is AUTO and we are cooling
                state = stage * (-1 if mode == frames.HvacMode.COOL else 1)
                stateg = getgauge('finitude_state', 'current operating state')
                stateg.labels(name=self.name).set(state)
                s = 'off' if state == 0 else 'cool' if state < 0 else 'heat'
                HvacMonitor.HVACSTATE.labels(name=self.name).state(s)
            else:
                if zone:
                    gauge = getgauge(gaugename, desc, morelabels=['zone', 'zonename'])
                    zname = self.zone_to_name[zone-1].strip(' \0')
                    if zname:
                        gauge.labels(
                            name=self.name, zone=str(zone), zonename=zname
                        ).set(v / divisor)
                    else:
                        LOGGER.debug(f'ignoring {gaugename} in {zone}: no zonename')
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
                HvacMonitor.FRAME_COUNT.labels(name=self.name).inc()
                (name, rest) = self.process_frame(frame)
                if self.store_frames:
                    self.store_frame(frame, name, rest)
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
