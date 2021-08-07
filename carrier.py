#!/usr/bin/python

# originally from https://github.com/3tones/brybus

import serial
import struct
import time

class stream:
  'connect to a file or serial port'
  
  def __init__(self, type, path):
    assert self.type == "S"
    self.ser = serial.Serial(path, 38400)
      
  def read(self, bytes):
    return self.ser.read(bytes)

  def write(self, data):
    self.ser.write(data)
  
  def inWaiting(self):
    return self.ser.inWaiting()

class bus:
  'functions to read/write from the carrier/bryant bus'
  #attaches to the stream and handles specifics of timing and framing

  def __init__(self, stream):
    self.stream = stream
    self.locked = 0
    self.starttime = 0
    self.timetrigger = False
    self.lastfunc = ''
    self.timeout = 0.02
    self.buf= ""
  
  def read(self):
    frame = ""
    self.locked = 0

    # make sure we have enough data in the buffer to check for the size of the frame
    while len(self.buf) < 10:
      self.buf += self.stream.read(1)
	
    # fill the buffer to the frame size, then check the crc
    while not self.locked:
      frame_len = ord(self.buf[4])+10
      if len(self.buf) >= frame_len:
        frame = self.buf[:frame_len]
		#calculate crc of the frame
        crc16 = 0x0000
        for ch in frame:
          crc16 = calcByte(ch, crc16)
        if crc16 == 0:
          self.locked = 1
        else:
          print "SEEKING"
          self.buf = self.buf[1:]
      else:
        self.buf += self.stream.read(1)
    
    # set lastfunc for testing before write
    self.lastfunc = ByteToHex(frame[7])
	
    # cut data that will be returned off the beginning of the buffer
    self.buf = self.buf[frame_len:]

    return frame
  
  def write(self, data):
    # blocking call to test when it is ok to write - then write if OK
    # return 0 = no action
    # return 1 = item written
    # return 2 = paused, but no write
    
    # mark the current time
    self.starttime = time.clock()
    self.timetrigger=True
  
    # wait for data to become available - inWaiting is non blocking
    self.pause = False
    self.writeok = False
    while not self.inWaiting():
      if self.timetrigger and ((self.starttime + self.timeout) < time.clock()) and (self.lastfunc=='06'):
        self.pause=True
        if data != '':
          #TODO add "safe mode" to block invalid functions
          self.stream.write(data)
          self.writeok=True
        self.timetrigger=False
    if self.writeok:
      return 1
    if self.pause:
      return 2
    return 0
    
  def inWaiting(self):
    return self.stream.inWaiting()

class frame:
  'this class represents a frame from the bus'
  
  def __init__(self,data,type,dst='',src='',func=''):
    if type == "B": #binary
      self.raw = data
    if type == "S": #string
      self.raw = HexToByte(data)
    if type == "C": #create frame
      self.len_int = len(data)/2
      self.len = "{0:02X}".format(self.len_int)
        #formatting string:
        #0: first parameter
        #0  fill with zeros
        #2  fill to n chars
        #x  hex, uppercase
      self.raw = HexToByte(dst + src + self.len + '0000' + func + data) 

    #parse out the parts of the frame  
    self.dst = ByteToHex(self.raw[0:2])
    self.src = ByteToHex(self.raw[2:4])
    self.len = ByteToHex(self.raw[4])
    self.len_int = int(self.len,16)
    self.func = ByteToHex(self.raw[7])
    self.ts = time.clock()
    
	#set the crc value to zero before updating it
    self.crc16 = 0x0000;

    #Note: the length of the entire frame minus 8 for the header, and 2 for the crc should be the length given in the frame
    if len(self.raw)-8-2 == self.len_int:
      #if this frame already has a CRC, check it
      self.data = ByteToHex(self.raw[8:8+self.len_int])
      self.crc = ByteToHex(self.raw[8+self.len_int:]) 
      #check crc
      for ch in self.raw[:8+self.len_int]:
          self.crc16 = calcByte(ch, self.crc16)

      self.crccalc = ByteToHex(struct.pack('<H',self.crc16))
      #TODO put a flag for valid CRC
    else:
      #if it does not have a CRC, add it (used when making frames)
      for ch in self.raw:
          self.crc16 = calcByte(ch, self.crc16)
      self.crc = ByteToHex(struct.pack('<H',self.crc16)) 

      self.raw += struct.pack('<H',self.crc16)
      self.data = ByteToHex(self.raw[8:8+self.len_int])

  def print_str(self):
    return ByteToHex(self.raw)
	
class queueitem:
  'a single item to put on the bus - used in the queue'
  #the response is intentionally filled with garbage to start
  def __init__(self,f):
    self.frame = f
    self.response = frame('000130010100000B000000','S')
    self.done = False
  
  def print_str(self):
    return self.frame.print_str()+' '+self.response.print_str()+' '+str(self.done)

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
  
  #TODO remove frame from queue
  #def popframe(self,index):
  
  #print the queue
  def printqueue(self):
    for k,v in self.queue.iteritems():
      print k,v.print_str()

  def print_str(self):
    r = ""
    for k,v in self.queue.iteritems():
      r += str(k) + " " + v.print_str() + '\n'
    return r
	  
  def printstatus(self):
    total = len(self.queue)
    done = 0
    for k,v in self.queue.iteritems():
      if v.done==True:
        done+=1
    return str(done)+'/'+str(total)
	
#==================== AUX FUNCTIONS ===================
#These are all snippets of code gained elsewhere on the Internet.

#Byte-Hex Conversions
#from http://code.activestate.com/recipes/510399-byte-to-hex-and-hex-to-byte-string-conversion/

def ByteToHex( byteStr ):
	return ''.join( [ "%02X" % ord( x ) for x in byteStr ] ).strip()

def HexToByte( hexStr ):
  bytes = []
  hexStr = ''.join( hexStr.split(" ") )
  for i in range(0, len(hexStr), 2):
    bytes.append( chr( int (hexStr[i:i+2], 16 ) ) )
  return ''.join( bytes )	

#Table based CRC calculation  
#I initially used crcmod, but it wasn't fast enough on an rPi, so I found this.
#http://www.digi.com/wiki/developer/index.php/Python_CRC16_Modbus_DF1
INITIAL_MODBUS = 0xFFFF
INITIAL_DF1 = 0x0000

table = (
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
0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040 )

def calcByte( ch, crc):
    """Given a new Byte and previous CRC, Calc a new CRC-16"""
    if type(ch) == type("c"):
        by = ord( ch)
    else:
        by = ch
    crc = (crc >> 8) ^ table[(crc ^ by) & 0xFF]
    return (crc & 0xFFFF)

def calcString( st, crc):
    """Given a binary string and starting CRC, Calc a final CRC-16 """
    for ch in st:
        crc = (crc >> 8) ^ table[(crc ^ ord(ch)) & 0xFF]
    return crc
