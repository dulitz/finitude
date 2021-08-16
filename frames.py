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

from enum import Enum, IntEnum


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
    """Discard data until we find a valid frame boundary. Return the first valid frame,
    leaving any residual data in self.buf.

    SocketStream may raise socket.timeout. Raises CarrierError if remote end closes the
    connection.
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
    """If data can be read without blocking, or if the last frame was something other than
    ACK06, return False immediately. Otherwise write data and return True. Note that this
    relies on there being a thermostat or SAM in the system to make requests that are ACKed.
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


class Field(Enum):
    UNKNOWN = 0
    UTF8 = 1   # NUL-padded at the end
    NAME = 2   # 12-byte NUL-padded UTF-8 name
    UINT8 = 3
    INT8 = 4
    UINT16 = 5


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

  # register info from https://github.com/acd/infinitive/blob/master/infinitive.go
  # and https://github.com/acd/infinitive/blob/master/tables.go
  REPEATED_8_ZONES = 0
  REGISTER_INFO = {
    '000104': ('DeviceInfo', [(48, Field.UTF8, 'Module'), (16, Field.UTF8, 'Firmware'), (20, Field.UTF8, 'Model'), (36, Field.UTF8, 'Serial')]),
    '000306': ('AirHandler06', [(1, Field.UNKNOWN), (1, Field.UINT16, 'BlowerRPM')]),
    # State & 0x03 != 0 when electric heat is on
    '000316': ('AirHandler16', [(1, Field.UINT8, 'State'), (3, Field.UNKNOWN), (1, Field.UINT16, 'AirflowCFM')]),
    # DamperPosition is 0xff for a zone not connected to this device
    '000319': ('DamperState', [(REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')]),
    # changes from infinitive: first 3 unknown bytes
    '003b02': ('TStatCurrentParams', [(3, Field.UNKNOWN), (REPEATED_8_ZONES, Field.UINT8, 'CurrentTemp'), (REPEATED_8_ZONES, Field.UINT8, 'CurrentHumidity'), (1, Field.UNKNOWN), (1, Field.INT8, 'OutdoorAirTemp'), (1, Field.UINT8, 'ZonesUnoccupied'), (1, Field.UINT8, 'Mode'), (5, Field.UNKNOWN), (1, Field.UINT8, 'DisplayedZone')]),
    # changes from infinitive: first 3 unknown bytes
    '003b03': ('TStatZoneParams', [(3, Field.UNKNOWN), (REPEATED_8_ZONES, Field.UINT8, 'FanMode'), (1, Field.UINT8, 'ZonesHolding'), (REPEATED_8_ZONES, Field.UINT8, 'CurrentHeatSetpoint'), (REPEATED_8_ZONES, Field.UINT8, 'CurrentCoolSetpoint'), (REPEATED_8_ZONES, Field.UINT8, 'CurrentHumiditySetpoint'), (1, Field.UINT8, 'FanAutoConfig'), (1, Field.UNKNOWN), (REPEATED_8_ZONES, Field.UINT16, 'HoldDuration'), (REPEATED_8_ZONES, Field.NAME, 'Name')]),
    '003b04': ('TStatVacationParams', [(1, Field.UINT8, 'Active'), (1, Field.UINT16, 'DaysTimes7'), (1, Field.UINT8, 'MinTemp'), (1, Field.UINT8, 'MaxTemp'), (1, Field.UINT8, 'MinHumidity'), (1, Field.UINT8, 'MaxHumidity'), (1, Field.UINT8, 'FanMode')]),
    '003e01': ('HeatPump01', [(1, Field.UINT16, 'OutsideTempTimes16'), (1, Field.UINT16, 'CoilTempTimes16')]),
    # shift StageShift1 right by one bit to get the stage number
    # higher stage numbers correspond to auxilliary heat on
    '003e02': ('HeatPump02', [(1, Field.UINT8, 'StageShift1')]),
    }
  def _get_register_info(self):
    assert (self.func == Function.READ or
            self.func == Function.WRITE or
            self.func == Function.ACK06), self.func
    assert self.length >= 3, self.length
    k = bytestohex(self.data[0:3])
    k2 = k[2:] if k.startswith('00') else k
    (name, fmt) = self.REGISTER_INFO.get(k, ('register', []))
    return (f'{name}({k2})', fmt)

  def get_register(self):
    if (self.func == Function.READ or
        self.func == Function.WRITE or
        self.func == Function.ACK06) and self.length >= 3:
      k = bytestohex(self.data[0:3])
      name = self.REGISTER_INFO.get(k, (None, []))[0]
      return name if name is not None else k[2:] if k.startswith('00') else k
    return None

  def get_printable_register(self):
    return self._get_register_info()[0]

  def parse_register(self):
    def parse_field(cursor, reps, field):
      if field == Field.NAME:
        assert reps == 1, (reps, field)
        reps, field = 12, Field.UTF8
      if field == Field.UTF8:
        assert reps > 0, (reps, field)
        return (cursor[0:reps].decode().strip('\0'), cursor[reps:])
      assert reps == 1, (reps, field)
      if field == Field.UINT8:
        return (cursor[0], cursor[1:])
      if field == Field.INT8:
        return (struct.unpack('>b', cursor[0:1])[0], cursor[1:])
      if field == Field.UINT16:
        return (struct.unpack('>H', cursor[0:2])[0], cursor[2:])
      assert False, (reps, field)

    (name, fmt) = self._get_register_info()
    if not fmt:
      return (name, {}, self.data)
    cursor = self.data[3:]
    values = {}
    for (reps, field, *fieldname) in fmt:
      if reps == self.REPEATED_8_ZONES:
        assert len(fieldname) == 1, (reps, field, *fieldname)
        for zone in range(8):
          (value, cursor) = parse_field(cursor, 1, field)
          values[f'Zone{zone+1}{fieldname[0]}'] = value
      elif field == Field.UNKNOWN:
        assert not fieldname, (reps, field, *fieldname)
        assert reps > 0, (reps, field, *fieldname)
        cursor = cursor[reps:]
      else:
        assert len(fieldname) == 1, (reps, field, *fieldname)
        (value, cursor) = parse_field(cursor, reps, field)
        assert fieldname[0] not in values, (values, (reps, field, *fieldname))
        values[fieldname[0]] = value
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


class FanMode(IntEnum):
  AUTO = 0
  LOW = 1
  MEDIUM = 2
  HIGH = 3


class HvacMode(IntEnum):
  HEAT = 0      # heat source: "system in control"
  COOL = 1
  AUTO = 2
  ELECTRIC = 3  # heat source: electric only FIXME: is this furnace also?
  HEATPUMP = 4  # heat source: heat pump only
  OFF = 5


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


def main(args):
  stream = StreamFactory(args[1])
  bus = Bus(stream, report_crc_error=lambda: print('.', end='', file=sys.stderr))
  while True:
    frame = ParsedFrame(bus.read())
    print(frame)

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
