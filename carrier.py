"""
originally from https://github.com/3tones/brybus

See also https://github.com/nebulous/infinitude/issues/115
and https://github.com/Will1604/infinitive for some fixes to infinitive in Go
and https://github.com/acd/infinitive/issues/9
"""

import serial

import select
import socket
import struct
import time


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
    self.ser = serial.Serial(path, 38400)

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

  def __init__(self, stream):
    self.stream = stream
    self.lastfunc = None
    self.buf = b''

  def _read_until(self, size):
    """Read data until self.buf is at least size characters.
    """
    while len(self.buf) < size:
      self.buf += self.stream.read(size - len(self.buf))

  def read(self):
    """Discard data until we find a valid frame boundary. Return the first valid frame,
       leaving any residual data in self.buf.
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
      print('.', end='')
      self.buf = self.buf[1:]

  def write(self, data):
    # nonblocking call to test when it is ok to write - then write if OK
    # return 0 = no action
    # return 1 = item written

    assert data

    if (not self.stream.can_read) and self.lastfunc == 0x06:
      self.stream.write(data)
      return 1
    return 0
    

class OldFrame:
  """A frame from the bus."""
  
  def __init__(self, data, type, dst='', src='', func=''):
    self.crcer = CRC16()
    if type == "B": # binary
      self.raw = data
    if type == "S": # string
      self.raw = HexToByte(data)
    if type == "C": # create frame
      self.len_int = len(data) / 2
      self.len = "{0:02X}".format(self.len_int)
      # formatting string:
      #   0: first parameter
      #   0  fill with zeros
      #   2  fill to n chars
      #   x  hex, uppercase
      self.raw = HexToByte(dst + src + self.len + '0000' + func + data) 

    # parse out the parts of the frame  
    self.dst = ByteToHex(self.raw[0:2])
    self.src = ByteToHex(self.raw[2:4])
    self.len = ByteToHex(self.raw[4])
    self.len_int = int(self.len, 16)
    self.func = ByteToHex(self.raw[7])
    self.ts = time.clock()
    
    # the length of the entire frame minus 8 for the header and 2 for the crc
    # should be the length given in the frame
    if len(self.raw) - 8 - 2 == self.len_int:
      # if this frame already has a CRC, check it
      self.data = ByteToHex(self.raw[8:8+self.len_int])
      self.crc = ByteToHex(self.raw[8+self.len_int:]) 
      # check crc
      crc16 = self.crcer.calculate(self.raw[:8+self.len_int])
      self.crccalc = ByteToHex(struct.pack('<H', crc16))
      # TODO put a flag for valid CRC
    else:
      # if it does not have a CRC, add it (used when making frames)
      crc16 = self.crcer.calculate(self.raw)
      self.crc = ByteToHex(struct.pack('<H', crc16)) 
      self.raw += struct.pack('<H', crc16)
      self.data = ByteToHex(self.raw[8:8+self.len_int])

  def __str__(self):
    return self.raw


class queueitem:
  'a single item to put on the bus - used in the queue'
  #the response is intentionally filled with garbage to start
  def __init__(self, f):
    self.frame = f
    self.response = frame('000130010100000B000000','S')
    self.done = False
  
  def __str__(self):
    return f'{self.frame} {self.response} {self.done}'

class writequeue:
  'a queue to hold items and their responses to/from the bus'
  def __init__(self):
    self.queue = {}
    self.index = 0
  
  #put a new frame on the queue
  def pushframe(self,f):
    self.queue[self.index] = queueitem(f) 
    self.index+=1
    return self.index-1 
  
  #take any frame and see if it is a response
  #this should be checked immediately after writing the frame for best results
  #this depends on writeframe() returning the same thing when it was called to write
  #  and the following frame is the response based on a swapped src/dst.
  #  this is the best we can do since an error can be a response and there is no for sure match
  def checkframe(self,frame):
    for k,v in self.queue.iteritems():
      if v.frame.src==frame.dst and v.frame.dst==frame.src and v.frame.raw==self.writeframe():
        v.response = frame
        v.done = True
        break
  
  #return raw frame to be written to the bus
  def writeframe(self):
    for k in sorted(self.queue.keys()):
      if self.queue[k].done==False:
        return self.queue[k].frame.raw
        break
    return ''
  
  #test function to force all items done
  def test(self):
    for k,v in self.queue.iteritems():
      v.done = True    
  
  #print the queue
  def printqueue(self):
    for k,v in self.queue.iteritems():
      print(k, str(v))

  def __str__(self):
    r = ""
    for k,v in self.queue.iteritems():
      r += str(k) + " " + str(v) + '\n'
    return r
	  
  def printstatus(self):
    total = len(self.queue)
    done = 0
    for k,v in self.queue.iteritems():
      if v.done==True:
        done+=1
    return str(done)+'/'+str(total)
	
# from http://code.activestate.com/recipes/510399-byte-to-hex-and-hex-to-byte-string-conversion/

def ByteToHex(data):
  """Given a bytes object data, returns a string of hex digits, two digits per byte in data."""
  return ''.join(['%02X' % x for x in data])

def HexToByte(hex):
  """Given a string of hex digits, two digits per byte, returns a bytes object."""
  data = []
  nospaces = ''.join(hex.split(' '))
  for i in range(0, len(nospaces), 2):
    data.append(int(nospaces[i:i+2], 16))
  return bytes(data)

# table based CRC calculation from
# http://www.digi.com/wiki/developer/index.php/Python_CRC16_Modbus_DF1

class CRC16:
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
  bus = Bus(stream)
  print(bus.read())

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
