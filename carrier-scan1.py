#!/usr/bin/python

# originally from https://github.com/3tones/brybus

import time
scriptstart =  time.time()
import csv

import brybus
import ConfigParser

cfg = ConfigParser.ConfigParser()
cfg.read('brybus.cfg')
serialport = cfg.get('brybus','serialport')
scan_registers = cfg.get('scanner','scan_registers')
scan_data = cfg.get('scanner','scan_data')

def scantable():
  #load data from csv
  print "Loading table information"
  
  #load CSV into memory
  registers = []
  tfin = csv.reader(open(scan_registers, 'rb'))
  for row in tfin:
    registers.append(row)
  
  scan_q = brybus.writequeue()
  
  print "Building Queue"
  for r in registers:
    reg = '00' + r[1] + r[6]
    f = brybus.frame(reg,'C',r[0],'3001','0B')
    scan_q.pushframe(f)
          
  return scan_q  

#=======main========

q = scantable()
q.printqueue()

#setup the stream and bus
s = brybus.stream('S',serialport)
b = brybus.bus(s)

while(1):
  #write
  wf_raw = q.writeframe()
  wf = brybus.frame(wf_raw,"B")
  w = b.write(wf_raw)
  
  f = brybus.frame(b.read(),"B")
  if w==1:
    print "write", q.printstatus()
    print wf.dst,wf.src,wf.len,wf.func,wf.data,wf.crc
    print f.dst,f.src,f.len,f.func,f.data,f.crc
  q.checkframe(f)
  
  #test for end of queue
  if q.writeframe() == '':
    q.printqueue()
	
    f = open(scan_data, 'w')
    f.write(q.print_str())
    f.close()
	
    print "Seconds Elapsed:",(time.time()-scriptstart)
    exit()
