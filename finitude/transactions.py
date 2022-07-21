"""
transactions.py -- read or write a register from/to a device on the bus
"""

from .frames import AssembledFrame, Function, FinitudeError


class RetryableFinitudeError(FinitudeError):
    """There was an error but you should retry and it might work."""
    pass


class FrameToSend:
    def __init__(self, bus, source, dest, funcstr, register='', mask='', data=''):
        self.bus = bus
        for f in Function:
            if f.name == funcstr:
                func = f.value
                break
        else:
            raise Exception(f'unknown function {funcstr}')

        regb = (bytes([0]) + FrameToSend.convert_word_to_bytes(register)) if register else b''
        maskb = (bytes([0]) + FrameToSend.convert_word_to_bytes(mask)) if mask else b''
        datab = bytes([int(hi + lo, 16) for (hi, lo) in zip(*([iter(data)]*2))])
        self.frame = AssembledFrame(
            FrameToSend.convert_word_to_bytes(dest),
            FrameToSend.convert_word_to_bytes(source),
            func,
            regb + maskb + datab
        )
        self.sent = False

    def process(self, frame):
        """Frame is a frame read from the bus. Send if we haven't sent yet and
        if the bus is in a sendable condition. Return True if frame
        acknowledges the sent frame; otherwise return False.
        """
        if frame.func == Function.ACK06 and not self.sent:
            self.sent = self.bus.write(self.frame.framebytes)
            if not self.sent:
                raise RetryableFinitudeError('could not write to bus. please retry')
        return (self.sent and
                frame.source == self.frame.dest and
                frame.dest == self.frame.source and
                frame.func in (Function.ACK06, Function.ACK02, Function.NACK))

    @staticmethod
    def convert_word_to_bytes(word):
        if len(addr) != 4:
            raise FinitudeError(f'{addr} is invalid')
        assert int(addr, 16)  # raises ValueError if not valid hex
        return bytes([0, int(addr[0:2], 16), int(addr[2:], 16)])


def main(args):
    """Requires either one argument or between 5 and 8. The first argument
    must be a special file or URI of the RS-485 bus adapter.

    With additional arguments we send a frame with function
    "func". Otherwise we send nothing.

    Either way we read frames forever and print one line for each frame
    we see on the bus.
    """
    if len(args) != 2 and (len(args) < 5 or len(args) > 8):
        print(f'''Usage: {args[0]} URI_of_bus_adapter dest source func data
Usage: {args[0]} URI_of_bus_adapter dest source READ register
Usage: {args[0]} URI_of_bus_adapter dest source WRITE register [mask] data''', file=sys.stderr)
        return 1

    stream = StreamFactory(args[1])
    bus = Bus(stream, report_crc_error=lambda: print('.', end='', file=sys.stderr))
    if len(args) >= 5:
        (dest, source, func, data) = (args[2], args[3], args[4], args[5])
        register = ''
        mask = ''
        if func == 'READ':
            assert len(args) == 6, args
            register = data
            data = ''
        elif func == 'WRITE':
            assert len(args) == 8, args
            register = data
            mask = args[6]
            data = args[7]
        else:
            assert len(args) == 5, args
        pending = FrameToSend(bus, dest, source, func, register, mask, data)
    else:
        pending = None

    while True:
        frame = ParsedFrame(bus.read())
        print(frame)
        if pending and pending.process(frame):
            pending = None
