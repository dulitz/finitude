"""
finitude.py

Exports runtime data from a Carrier Infinity or Bryant Evolution HVAC system
to Prometheus.

Prometheus can query us very often (every second if desired) because we are
constantly listening to the HVAC's RS-485 bus and updating our internal state.
"""

import json, logging, prometheus_client, threading, time, yaml

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

    def __init__(self, name, path):
        self.name, self.path = name, path
        self.stream, self.bus = None, None
        self.synchronized = False
        self.register_to_rest = {}
        self.framedata_to_index = {}
        self.frames = []  # squashed
        self.store_frames = False
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
        if frame.func == frames.Function.ACK06 and frame.length >= 3:
            (name, values, rest) = frame.parse_register()
            (basename, paren, num) = name.partition('(')
            if values:
                if basename == 'DeviceInfo':
                    self.DEVINFO.labels(name=self.name, device=frames.ParsedFrame.get_printable_address(frame.source)).info(values)
                else:
                    tablename = self.TABLE_NAME_MAP.get(basename, basename)
                    for (k, v) in values.items():
                        self._set_gauge(tablename, k, v)
            return (name, rest)
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
        (lastrest, lastframe) = self.register_to_rest.get(name) if rest else None
        if lastrest == (rest or None):
            return
        self.register_to_rest[name] = (rest, frame)
        index = self.framedata_to_index.get(frame.data)
        if index is None:
            index = len(self.framedata_to_index) + 1
            self.framedata_to_index[frame.data] = index
        self.frames.append((time.time(), name, index))

    def _set_gauge(self, tablename, itemname, v):
        if isinstance(v, str):
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
        if tablename:
            gaugename = f'finitude_{tablename}_{itemname.lower()}'
        else:
            gaugename = f'finitude_{itemname}'
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
