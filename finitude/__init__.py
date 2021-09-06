"""__init__.py for finitude

We let you read and write frames on a Bus.

So you need to create a Bus. It wants a stream to read from and write to.
Create a stream by passing a URI to StreamFactory().

Example:

stream = StreamFactory('/dev/ttyUSB0')
### if using an Ethernet/RS-485 bridge: StreamFactory('telnet://localhost:2626')
bus = Bus(stream)

# read TStatCurrentParams from the thermostat -- we say we are address 3001
fts = FrameToSend(bus, '3001', '2001', Function.READ, register='003b02')

while True:
    parsedframe = bus.read()
    dest = ParsedFrame.get_printable_address(parsedframe.dest)
    if dest == '3001':
        if parsedframe.func == Function.ACK06:
            # yay, someone sent us data! probably the thermostat!
            print(parsedframe)
        elif parsedframe.func == Function.NACK:
            print('oh no the thermostat hates us')
            print(parsedframe)
    if fts:
        if bus.write(fts.frame.framebytes):
            print('we wrote it')
            fts = None  # we shouldn't write it again just yet
        else:
            print("we didn't write it")
"""

from . import frames
from . import registers
from . import finitude


CarrierError = frames.CarrierError

StreamFactory = frames.StreamFactory
Bus = frames.Bus
Function = frames.Function
AssembledFrame = frames.AssembledFrame
ParsedFrame = frames.ParsedFrame
FrameToSend = frames.FrameToSend

FanMode = registers.FanMode
HvacMode = registers.HvacMode

Finitude = finitude.Finitude
