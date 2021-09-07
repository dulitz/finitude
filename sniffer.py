"""
sniffer.py

Reads all packets on the ABCD bus. Tracks all devices which appear as source or destination.
For each source of a READ packet, tracks destination.
For each destination of a READ packet, tracks (source, register).
For each source of an ACK06 packet, tracks register and response data.
Track all other packets.
"""

from finitude import frames

import socket
import sys
import time

get_printable_address = frames.ParsedFrame.get_printable_address

class Sniffer:
    def __init__(self, stream):
        self.stream = stream
        self.bus = frames.Bus(stream, report_crc_error=lambda: print('.', end='', file=sys.stderr))

        self.devices = set()
        self.readsource_to_dests = {}
        self.readdest_to_sourceregisters = {}
        self.acksource_to_registerdata = {}
        self.nacksource_to_register = {}
        self.sourcedest_to_register = {}
        self.otherframes = []

    def read_one_frame(self):
        return frames.ParsedFrame(self.bus.read())

    def process_frame(self, frame):
        self.devices.add(frame.source)
        self.devices.add(frame.dest)
        if frame.func == frames.Function.READ:
            Sniffer._add(self.readsource_to_dests, frame.source, frame.dest)
            Sniffer._add(self.readdest_to_sourceregisters, frame.dest, (frame.source, frame.data))
            self.sourcedest_to_register[(frame.source, frame.dest)] = frame.data
        elif frame.func == frames.Function.ACK06:
            register = self.sourcedest_to_register.get((frame.dest, frame.source))
            Sniffer._add(self.acksource_to_registerdata, frame.source, str(frame))
        elif frame.func == frames.Function.NACK:
            register = self.sourcedest_to_register.get((frame.dest, frame.source))
            Sniffer._add(self.nacksource_to_register, frame.source, register)
        else:
            self.otherframes.append(frame)

    @staticmethod
    def _add(map, key, value):
        values = map.get(key)
        if values is None:
            values = set()
            map[key] = values
        values.add(value)

def main(args, outputfile):
    started = time.time()
    sniffer = Sniffer(frames.StreamFactory(args[1]))
    frame = sniffer.read_one_frame()
    print(f'synchronized at: {frame}', file=outputfile)

    nframes = 1
    try:
        while True:
            sniffer.process_frame(frame)
            frame = sniffer.read_one_frame()
            nframes += 1
            if 0 == nframes % 100:
                print(f'{nframes}: {len(sniffer.devices)} devices, {len(sniffer.otherframes)} other frames', file=outputfile)
    except socket.timeout as ex:
        print(f'caught exception {ex}', file=outputfile)
    except KeyboardInterrupt as ex:
        print(f'caught KeyboardInterrupt', file=outputfile)

    def devicelist(devices):
        return ' '.join(sorted([get_printable_address(d) for d in devices]))

    elapsed = round(time.time() - started, 2)
    print(f'read {nframes} frames total in {elapsed} sec, {round(nframes/elapsed, 2)} frames/sec')
    print(f'observed devices {devicelist(sniffer.devices)}')
    for (source, dests) in sorted(sniffer.readsource_to_dests.items()):
        print(f'{get_printable_address(source)} queried {devicelist(dests)}')
    for (dest, sourceregisters) in sorted(sniffer.readdest_to_sourceregisters.items()):
        print(f'{get_printable_address(dest)} was queried:')
        for (source, register) in sorted(sourceregisters):
            print(f'  by {get_printable_address(source)} for {frames.bytestohex(register)}')
    for (source, registerdata) in sorted(sniffer.acksource_to_registerdata.items()):
        print(f'\n{get_printable_address(source)} ACKed:')
        for rd in registerdata:
            print(rd)
    for (source, registers) in sorted(sniffer.nacksource_to_register.items()):
        rvals = ' '.join([frames.bytestohex(r) for r in sorted(registers)])
        print(f'{get_printable_address(source)} NAKed registers {rvals}')
    print(f'\n{len(sniffer.otherframes)} other frames:')
    for f in sniffer.otherframes:
        print(f)

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv, sys.stderr))

"""
Usage: python3 sniffer.py /dev/ttyUSB0
Usage: python3 sniffer.py telnet://192.168.0.7:26


"""
