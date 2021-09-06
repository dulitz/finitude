"""
frames.py -- framing protocol for Carrier Infinity and Bryant Evolution HVAC systems.

Portions based on https://github.com/3tones/brybus

See also https://github.com/nebulous/infinitude/issues/115
and https://github.com/Will1604/infinitive for some fixes to infinitive in Go
and https://github.com/acd/infinitive/issues/9
"""

import serial

import select
import socket
import struct
import sys
import time

from enum import IntEnum

from .registers import FanMode, HvacMode, Field, REGISTER_INFO, REPEATED_8_ZONES


class CarrierError(Exception):
  pass


class SerialStream:
  """Connect to a serial port."""
  
  def __init__(self, path):
    self.path = path
    self.ser = None
    self.open()

  def open(self):
    assert self.ser is None, self.ser
    self.ser = serial.Serial(self.path, 38400)

  def read(self, numbytes):
    return self.ser.read(numbytes)

  def write(self, data):
    self.ser.write(data)

  @property
  def can_read(self):
    return self.ser.in_waiting > 0

  def close(self):
    self.ser.close()
    self.ser = None


class SocketStream:
  """Connect to a TCPv4 socket."""
  
  def __init__(self, host, port, timeout=10):
    # create a blocking TCP connection
    self.hostport = (host, port)
    self.timeout = timeout
    self.sock = None
    self.open()

  def open(self):
    assert self.sock is None, self.sock
    self.sock = socket.create_connection(self.hostport, timeout=self.timeout)

  def read(self, numbytes):
    """Raises socket.timeout if no data is received within the timeout.
    If data is received but synchronization does not occur, the timeout will not trigger.
    If read() returns b'', the remote end closed the connection cleanly.
    """
    b = self.sock.recv(numbytes)
    if not b:
      self.close()
    return b

  def write(self, data):
    self.sock.sendall(data)

  @property
  def can_read(self):
    (readable, writable, xable) = select.select([self.sock], [], [], timeout=0)
    return len(readable) > 0

  def close(self):
    self.sock.close()
    self.sock = None


def StreamFactory(where):
  """
  where is either a URL or a path to a serial device. If a URL it must have a scheme of
  either telnet:// or file://.
  """
  (scheme, sep, rest) = where.partition('://')
  if not sep:
    return SerialStream(where)
  if scheme == 'file':
    return SerialStream(rest)
  if scheme == 'telnet':
    (host, colon, port_no_default) = rest.partition(':')
    port = int(port_no_default) if colon else 23
    return SocketStream(host, port)
  raise CarrierError(f'unknown scheme {scheme} in StreamFactory({where})')


class Bus:
  """Parses the stream into frames.

  After creating an instance, call read() repeatedly to read an entire frame.
  """

  def __init__(self, stream, report_crc_error=None):
    self.stream = stream
    self.report_crc_error = report_crc_error
    self.lastfunc = None
    self.buf = b''

  def _read_until(self, size):
    """Read data until self.buf is at least size characters.
    """
    while len(self.buf) < size:
      readbytes = self.stream.read(size - len(self.buf))
      if not readbytes:
        raise CarrierError('connection closed [no data] while reading')
      self.buf += readbytes

  def read(self):
    """Discard data until we find a valid frame boundary. Return the first valid
    frame, leaving any residual data in self.buf.

    SocketStream may raise socket.timeout. Raises CarrierError if remote end
    closes the connection.
    """
    # make sure we have enough data in the buffer to check for the size of the frame
    self._read_until(10)
	
    crcer = CRC16()
    while True:
      frame_len = self.buf[4] + 10
      self._read_until(frame_len)
      frame = self.buf[:frame_len]
      crc = crcer.calculate(frame)
      if crc == 0:
        self.buf = self.buf[frame_len:]
        self.lastfunc = frame[7]
        return frame
      if self.report_crc_error:
        self.report_crc_error()
      self.buf = self.buf[1:]

  def write(self, data):
    """If data can be read without blocking, or if the last frame was
    something other than ACK06, return False immediately. Otherwise
    write data and return True. Note that this relies on there being a
    thermostat in the system to make requests that are ACKed.
    """
    assert data
    if (not self.stream.can_read) and self.lastfunc == Function.ACK06:
      self.stream.write(data)
      return True
    return False


class AssembledFrame:
  def __init__(self, dest, source, func, data=b'', crc=None, pid=0, ext=0):
    length = len(data)
    assert length <= 255, length
    self.frame = b''.join([dest, source, bytes([length, pid, ext, func]), data])
    crcer = CRC16()
    self.crc = crcer.calculate(self.frame)
    if crc is not None:
      assert crc == self.crc, (crc, self.crc)

  @property
  def framebytes(self):
    return self.frame + struct.pack('<H', self.crc)

  def __str__(self):
    return 'AssembledFrame:' + str(ParsedFrame(self.framebytes))


class ParsedFrame:
  def __init__(self, framebytes):
    self.framebytes = framebytes
    # frame is 8 byte header, self.length data bytes, and 2 byte CRC
    assert len(self.framebytes) == 8 + self.length + 2, (len(self.framebytes), self.length+10)

  @property
  def dest(self):
    """First byte is the address, second byte is the bus. Bus is always 0x1."""
    return self.framebytes[0:2]

  @property
  def source(self):
    """First byte is the address, second byte is the bus. Bus is always 0x1."""
    return self.framebytes[2:4]

  @property
  def length(self):
    return self.framebytes[4]

  @property
  def pid(self):
    """PID is always zero."""
    return self.framebytes[5]

  @property
  def ext(self):
    """EXT is always zero."""
    return self.framebytes[6]

  @property
  def func(self):
    return self.framebytes[7]

  @property
  def data(self):
    return self.framebytes[8:8+self.length]

  def is_crc_valid(self):
    crcer = CRC16()
    dataend = 8 + self.length
    calculated_crc = crcer.calculate(self.framebytes[0:dataend])
    stored_crc = struct.unpack('<H', self.framebytes[dataend:dataend+2])[0]
    return calculated_crc == stored_crc

  def get_function_name(self):
    try:
      return Function(self.func).name
    except ValueError:
      return f'UNKNOWN({self.func})'

  @staticmethod
  def get_printable_address(source_or_dest):
    address = source_or_dest[0]*256 + source_or_dest[1]
    return hex(address)

  def _get_register_info(self):
    assert (self.func == Function.READ or
            self.func == Function.WRITE or
            self.func == Function.ACK06), self.func
    assert self.length >= 3, self.length
    k = bytestohex(self.data[0:3])
    k2 = k[2:] if k.startswith('00') else k
    (name, fmt) = REGISTER_INFO.get(k, ('register', []))
    return (f'{name}({k2})', fmt)

  def get_register(self):
    if (self.func == Function.READ or
        self.func == Function.WRITE or
        self.func == Function.ACK06) and self.length >= 3:
      k = bytestohex(self.data[0:3])
      name = REGISTER_INFO.get(k, (None, []))[0]
      return name if name is not None else k[2:] if k.startswith('00') else k
    return None

  def get_printable_register(self):
    return self._get_register_info()[0]

  def parse_register(self):
    (name, fmt) = self._get_register_info()
    if not fmt:
      return (name, {}, self.data)
    cursor = self.data[3:]
    values = {}
    unknowns = 0
    def parseone(values, cursor, reps, field, *fieldname):
      assert len(fieldname) == 1, (reps, field, *fieldname)
      (value, newcursor) = Field.parse(cursor, reps, field)
      assert fieldname[0] not in values, (values, (reps, field, *fieldname))
      values[fieldname[0]] = value
      return newcursor
    for (reps, field, *fieldname) in fmt:
      if reps == REPEATED_8_ZONES:
        assert len(fieldname) == 1, (reps, field, *fieldname)
        for zone in range(8):
          (value, cursor) = Field.parse(cursor, 1, field)
          values[f'Zone{zone+1}{fieldname[0]}'] = value
      elif field == Field.UNKNOWN:
        assert not fieldname, (reps, field, *fieldname)
        assert reps > 0, (reps, field, *fieldname)
        for r in range(reps):
          values[f'{name}_unk{unknowns}_{r}'] = cursor[r]
        cursor = cursor[reps:]
        unknowns += 1
      elif field == Field.REPEATING:
        assert reps == 0, (reps, field, *fieldname)
        assert len(fieldname) == 1, (reps, field, *fieldname)
        dictname = fieldname[0]
        allreps = []
        while cursor:
          found = False
          v = {}
          for (reps, field, *fieldname) in fmt:
            if found:
              cursor = parseone(v, cursor, reps, field, *fieldname)
            elif field == Field.REPEATING:
              found = True
          assert v, (fmt, cursor)
          allreps.append(v)
        values[dictname] = allreps
        return (name, values, cursor)
      else:
        cursor = parseone(values, cursor, reps, field, *fieldname)
    return (name, values, cursor)

  def __str__(self):
    pid = f' {self.pid}' if self.pid else ''
    ext = f' {self.ext}' if self.ext else ''
    if self.func == Function.READ:
      data = self.get_printable_register()
    elif self.func == Function.WRITE:
      data = f'{self.get_printable_register()} value {bytestohex(self.data[3:])} {self.data[3:] if len(self.data) > 4 else ""}'
    elif self.func == Function.ACK06 and len(self.data) > 3:
      (name, values, remainbytes) = self.parse_register()
      valstr = ', '.join([f'{k}:{repr(v)}' for (k, v) in values.items()])
      remainder = f'{bytestohex(remainbytes)} {remainbytes}' if remainbytes else ''
      data = f'{name} values {remainder}' if not values else f'{name} {valstr} unparsed:{remainder}' if remainder else f'{name} {valstr}'
    else:
      data = f'{bytestohex(self.data)} {self.data if len(self.data) > 3 else ""}'
    crc = '' if self.is_crc_valid() else ' CRC BAD'
    return f'to {self.get_printable_address(self.dest)} from {self.get_printable_address(self.source)} len {self.length}{pid}{ext} {self.get_function_name()}({hex(self.func)}) {data}{crc}'


class Function(IntEnum):
  ACK02 = 0x02
  ACK06 = 0x06
  READ = 0x0b
  WRITE = 0x0c
  NACK = 0x15
  ALARM = 0x1e
  CHGTBN = 0x10  # change table name
  RDOBJ = 0x22
  RDVAR = 0x62
  FORCE = 0x63
  AUTO = 0x64
  LIST = 0x75


def bytestohex(rbytes):
  return ''.join(['%02x' % b for b in rbytes]) if rbytes else str(rbytes)


class CRC16:
  """Table based CRC calculation from
     http://www.digi.com/wiki/developer/index.php/Python_CRC16_Modbus_DF1
  """
  TABLE = (
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
    0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
    0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
    0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
    0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
    0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
    0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
    0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
    0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
    0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
    0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
    0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
    0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
    0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
    0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
    0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
    0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
    0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
    0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
    0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
    0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
    0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
    0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
    0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
    0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
    0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
    0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
    0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
    0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
    0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040
  )

  def _calculate_one_cycle(self, b, crc):
    """Given a new byte and previous CRC-16, return the new CRC-16."""
    crc = (crc >> 8) ^ self.TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFFFF

  def calculate(self, bytesin, crc=0):
    for b in bytesin:
      crc = self._calculate_one_cycle(b, crc)
    return crc


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
    self.frame = AssembledFrame(FrameToSend.convert_word_to_bytes(dest),
                                FrameToSend.convert_word_to_bytes(source),
                                func,
                                regb + maskb + datab)
    self.sent = False

  def process(self, frame):
    """Send frame if we haven't sent it yet and if we can. If a sent frame
    has been acknowledged, return True; if not return False.
    """
    if frame.func == Function.ACK06 and not self.sent:
      self.sent = self.bus.write(self.frame.framebytes)
      if not self.sent:
        print('failed to send frame, retrying...', file=sys.stderr)
    if self.sent and frame.source == self.frame.dest and frame.dest == self.frame.source and frame.func in (Function.ACK06, Function.ACK02, Function.NACK):
      print(f'transaction complete with {frame}', file=sys.stderr)
      return True
    return False

  @staticmethod
  def convert_word_to_bytes(word):
    if len(addr) != 4:
      raise CarrierError(f'{addr} is invalid')
    assert int(addr, 16)  # raises ValueError if not valid hex
    return bytes([0, int(addr[0:2], 16), int(addr[2:], 16)])

def main(args):
  """
  All args except the first are ignored. The first is a special file or URI of
  the RS-485 bus adapter. We write nothing to the bus and simply print one line
  for each frame we see on the bus.
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

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
