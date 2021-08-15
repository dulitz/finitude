"""
Scans all tables on all devices.

Originally from https://github.com/3tones/brybus

See also https://github.com/nebulous/infinitude/wiki/Infinity---interpreting-data
for more helpful information.
"""

import sys
import time

import carrier


class Scanner:
  def __init__(self, bus):
    self.bus = bus

  def get_devices(self, timelimit=10):
    """Read the bus for timelimit seconds to determine a list of devices.
    """
    starttime = time.time()
    devices = set()
    while time.time() - starttime < timelimit:
      frame = carrier.ParsedFrame(self.bus.read())
      devices.add(frame.source)
      devices.add(frame.dest)
    return devices

  def scan_tables(self, devices, timeout=0.1):
    """Using the set of devices, build a queue of all possible tables, and scan them all.
    timeout is the number of seconds before we give up on getting a response and send
    another request.
    """
    source = bytes([0x30, 0x01])
    func = 0x0b
    responses = []
    for d in devices:  # shorten this for testing
      numtables = 64
      print(f'destination {carrier.ParsedFrame.get_printable_address(d)} scanning {numtables} tables', file=sys.stderr)
      for t in range(1, numtables):
        data = bytes([0, t, 1])
        while not self.bus.write(carrier.AssembledFrame(d, source, func, data).framebytes):
          print('w', end='', file=sys.stderr)
        print('S', end='', file=sys.stderr)
        starttime = time.time()
        while time.time() - starttime < timeout:
          data = self.bus.read()
          if data:
            response = carrier.ParsedFrame(data)
            if response.dest == source and response.source == d:
              assert response.pid == 0, response.pid
              assert response.ext == 0, response.ext
              print('R', end='', file=sys.stderr)
              responses.append((d, t, response))
              break
            else:
              print('.', end='', file=sys.stderr)
          else:
            print('0', end='', file=sys.stderr)
        else:
          responses.append((d, t, None))
    return responses

  def filter_registers(self, responses):
    # this is where I stopped work


def main(args):
  stream = carrier.StreamFactory(args[1])
  bus = carrier.Bus(stream)
  scanner = Scanner(bus)
  devices = scanner.get_devices()
  # uncomment the next line(s) to force items into the device list
  # devices.add('1F01')
  # devices.add('2001')
  print('devices:', ' '.join(sorted([carrier.ParsedFrame.get_printable_address(d) for d in devices])), file=sys.stderr)

  responses = scanner.scan_tables(devices)
  registers = scanner.filter_registers(responses)

  return 0

if __name__ == '__main__':
    import sys
    scriptstart = time.time()
    retval = main(sys.argv)
    print(f'finished in {time.time() - scriptstart} seconds')
    sys.exit(retval)


#use the output of the scan to build a list of valid devices and tables

def old(phase, ph1_q):
    # scan_registers=cfg.get('scanner','scan_registers')

    tables=[]
    
    # print "==start table definition variable=="
    # show all queue items where there was not an error - info only
    for k,v in ph1_q.queue.iteritems():
      if v.response.func != '15':
       print(v.frame.dst, v.frame.data[2:4], v.response.data[30:32])
    

    # print "==start all valid table row combinations =="    
    #write csv to console to build final output
    f = open(scan_registers, 'w')
	
    for k,v in ph1_q.queue.iteritems():
      #for responses that were not an error
      if v.response.func not in  ['15','01']:
        #use the first part of the table definition on each row to output 
        output = ''
        output += v.frame.dst + ','
        output += v.frame.data[2:4] + ','
        output += v.response.data[6:10] + ','
        #ignore non printable characters - replace with question mark
        output += "".join([x if 31 < ord(x) < 128 else '?' for x in v.response.data[10:26].decode('hex')]) + ','
        output += v.response.data[26:30] + ','
        output += v.response.data[30:32] + ','
        #loop over the end of the table definition to define the rows in the table
        #print v.response.data[30:32], v.response.data
        for r in range(0,int(v.response.data[30:32],16)):
          thisrow = 32+4*r
          #if 0000 is the row definition, it does not exist, so don't print it
          if v.response.data[thisrow:thisrow+4] != '0000':
            row_output = "{0:02X}".format(r+1)+ ','
            row_output += v.response.data[thisrow:thisrow+2] + ','
            row_output += v.response.data[thisrow+2:thisrow+4]
            print(output+row_output)
            f.write(output+row_output+'\n')
