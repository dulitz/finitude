"""
analysis.py

wget http://[your_IP]:8001/sniffserver.json
"""

import json, time

def register_histogram(sequence):
    register_to_count = {}
    for (ts, regname, index, changes) in sequence:
        count = register_to_count.get(regname, 0)
        register_to_count[regname] = count + 1
    c = sorted([(count, reg) for (reg, count) in register_to_count.items()])
    return [(reg, count) for (count, reg) in c]

def print_register_histogram(seq, key=None):
    duration = seq[-1][0] - seq[0][0]
    print(f'\nhistogram for {key}, {len(seq)} ACK06 frames in {round(duration, 2)} sec')
    hist = register_histogram(seq)
    for (name, count) in hist:
        if count > 1:
            print(f'{name} {count} changes (every {round(duration/count, 2)} sec)')
    once = ', '.join([name for (name, count) in hist if count == 1])
    if once:
        print('no changes:', once)
    return hist

def print_byte_histogram(sequence, register):
    pos_to_bytes = {}
    for (ts, regname, index, changes) in sequence:
        if register == regname and changes:
            if isinstance(changes, list):
                for (pos, old, new) in changes:
                    b = pos_to_bytes.get(pos)
                    if b is None:
                        b = [old]
                        pos_to_bytes[pos] = b
                    b.append(new)
            elif isinstance(changes, str):
                print(f'{changes} at {time.ctime(ts)}')
            else:
                print(f'more than {changes} changes at {time.ctime(ts)}')
    h = sorted([(len(b), pos, b) for (pos, b) in pos_to_bytes.items()])
    for (count, pos, b) in h:
        print(f'{register} byte offset {pos}: {count} changes: {b}')
    return h

def print_byte_changes(sequence, register, pos, key=None):
    oldest = None
    time_byte = []
    for (ts, regname, index, changes) in sequence:
        if register == regname and changes and isinstance(changes, list):
            for (changepos, old, new) in changes:
                if pos == changepos:
                    if not time_byte:
                        oldest = old
                    time_byte.append((ts, new))
    if not time_byte:
        print(f'{key}: {register} offset {pos} did not change')
        return time_byte
    print(f'{key}: {register} byte offset {pos} had initial value {hex(oldest)}')
    last_ts = 0
    for (ts, b) in time_byte:
        if last_ts:
            print(f'{time.ctime(ts)} ({round(ts-last_ts, 1)} sec): {hex(b)}')
        else:
            print(f'{time.ctime(ts)} (initial): {hex(b)}')
        last_ts = ts
    return time_byte

# you'll need to change this filename to be a filename you have...

js = json.load(open('sniffserver-15Aug-hot-day-w-writes.json'))
loseq = js['system1']['sequence']
upseq = js['system2']['sequence']

system1 = register_histogram(loseq)
system2 = register_histogram(upseq)
lset = set([r for (r, c) in system1])
uset = set([r for (r, c) in system2])


first = min(upseq[0][0], loseq[0][0])
last = max(upseq[-1][0], loseq[-1][0])

print(f'from {time.ctime(first)} to {time.ctime(last)}, duration {round((last-first)/3600,3)} hours')

print('registers in both:', uset & lset)
print('only in system1:', lset - uset)
print('only in system2:', uset - lset)

print_register_histogram(loseq, 'system1')
print_register_histogram(upseq, 'system2')

bup = print_byte_histogram(upseq, 'AirHandler06(0306)')
print_byte_changes(upseq, 'AirHandler06(0306)', 3, key='system2')
blo = print_byte_histogram(loseq, 'AirHandler06(0306)')
print_byte_changes(loseq, 'AirHandler06(0306)', 3, key='system1')

# to try to isolate status changes resulting from a settings change,
# start by identifying the earliest possible settings change time and the latest
# possible settings change time.

def time_bounded_sequence(seq, earliest=0, latest=time.time()):
    start_condition = {v[1]: v for v in seq if v[0] < earliest}
    end_condition = {}
    for v in seq:
        if v[0] > latest and v[1] not in end_condition:
            end_condition[v[1]] = v
    return [v for v in start_condition.values()] + [v for v in seq if v[0] >= earliest and v[0] <= latest] + [v for v in end_condition.values()]

s = time_bounded_sequence(upseq, 1628904298, 1628904298+240)
print_register_histogram(s, 'living')
print_byte_histogram(s, 'register(0304)')
print_byte_histogram(s, 'register(0319)')

# system1 reports BlowerRPM but not AirflowCFM

# AirHandler06 has BlowerRPM
#   system2: bytes 3, 4, 6, 12 relatively few changes
#        bytes 5, 7: many changes (byte 7 eligible to change every 60 sec)
#   system1: bytes 6 and 7 same number of changes (154), bytes 4 and 12 more (~240),
#        byte 5: most changes (344)

# AirHandler06(0306) offset 3 [changes for system2 only] is usually 1
#   pulses to 0 for durations: 234, 60, 51, 297.1, 60.3, 60, 60 sec
#   1 durations: 5458, 1446, 5468, 1617, 13748, 50974, 4624 sec
# 0 pulses at 13:48, 14:14, 15:46 [long], 16:17, 20:07, 10:18, 11:36
# 1 from 12:17 to 13:48, 13:49 to 14:13, 14:14 5o 15:45, 15:50 to 16:17,
# 16:18 to 20:07, 20:08 to 10:18, 10:19 to 11:36, 11:37 to ...

# AirHandler06(0306) offset 4 [changes for system2 only]
#   some kind of "how hard am I working" number
#   0 1 2 3 2 1 2 3 4 3 2 1 0 1 3 2 1 0 1 2 3 4 3 4
# 1 02:35-08:46
# 0 to 08:47
# 1 to 09:50
# 2 to 10:11
# 3 to 10:34
# 2 to 10:35
# 1 to 11:10
# 2 to 11:36
# 3 to 12:06
# 4 to 21:50
# 3 to 22:11
# 2 to 22:46
# 1 to 00:36:02
# 0 to 00:36:04
# 1 to 00:38:14
# 3 to 00:38:20
# 2 to 00:39
# 1 to 08:33:03
# 0 to 08:33:15
# 1 to 09:30
# 2 to 10:09
# 3 to 10:58
# 4 to 11:25
# 3 to 11:38, then 4

# offset 6 is another that gets higher the harder it works

# offset 7 changes in both systems but this is about
# [system1 only]
#   0xc9, 0x0, 0x59 cycling; mostly 0 when off; mostly 0x59 other times
#   0    12:55
#   0x30 13:00 for 72 sec
#   0x87 13:01 for 60 sec
#   0    13:02 for 510 sec
# 02:38-03:39 nothing: 0x0 from 2:40 to 3:38, then 0x59 for 2 min then 0xc9 for 2.5 min
# 0x0 looks like off
# 0x59 looks like on
# 0xc9 looks like a minimum off time
#   
# [system2 only]
#   eligible to change every minute
#   0 overnight (not night of the 12th but 06:00-08:46 on 12th)
#   looks like 2's complement but doesn't behave that way
#   05:45 0xf8 (walk since 02:36)
#   06:00 0x00
#   08:46 0x5e
#   08:47 0xf4 (then walk)
#   09:33 0xf0
#   09:48 0x00 (then walk)
#   10:11 0x5a (then walk)
#   10:33 0x55
#   10:34 0xe9
#   11:02 0xf0
#   11:10 0x02
#   11:32 0xf7
#   11:36 0x58 (and walk)
#   12:03 0x4c
#   12:05 0x3a (so not 7 bit 2's complement)
#   12:41 0x33
#   12:42 0xde (and walk)
#   12:58 0x5b (and walk)
#   20:17 0x7e
#   20:18 0x80 (so not 8 bit 2's complement)
#   21:09 0xfc
#   21:23 0x44
#   22:03 0x65
#   22:05 0x05
#   00:36 0xa5
#   00:38 0x70
#   00:39 0x4e
#   00:43 0x00
#   08:33 0x61
#   08:34 0xf8
#   10:06 0x5d ...
#   11:56 0x3c

# ***********
# *********** damper control module
#
# goal: determine which zones' dampers are open and how much
#
# system2 device 6001 is Excalibur 4-zone damper control
#
# first find all registers the damper control has reported
# for (reg, frame) in analysis.js['system2']['frames_by_register']:
#     if frame.find('0x6001') != -1: print(frame)
#
# then for each register of interest
# bup = analysis.print_byte_histogram(analysis.upseq, 'WRITE(0x2001):register(0308)')
#
# to get more specific:
# from datetime import datetime
# for v in analysis.upseq:
#     if v[1].find('register(0308)') != -1:
#         print(datetime.fromtimestamp(v[0]).ctime(), v[1:])
#
# register(0302) to 0x2001 from 0x6001 len 27 ACK06(0x6) register(0302) values 000302010104da010204e0010305070404000004140000041c0000 b'\x00\x03\x02\x01\x01\x04\xda\x01\x02\x04\xe0\x01\x03\x05\x07\x04\x04\x00\x00\x04\x14\x00\x00\x04\x1c\x00\x00'
#    thermostat asked damper for its status and damper replied with this
#    0302 is reported in system1 system by the NIM (00030204110000)

# register(0308) to 0x6001 from 0x2001 len 11 WRITE(0xc) register(0308) value 0a050f0000000000 b'\n\x05\x0f\x00\x00\x00\x00\x00'
#    thermostat told damper to make these changes
#    0308 is never requested and is only written by system2 thermostat
#    0a 05 0f 00 00 00 00 00 is 8 bytes -- 4 zone damper with 3 zones connected
#    four distinct values before 17:00
#      15:09     09 03 (the rest are unchanged)
#      15:30:57  09 04
#      16:22:53  0a 04
#      16:33:55  0a 05

# register(0319) to 0x2001 from 0x6001 len 11 ACK06(0x6) register(0319) values 0003190a050f00ffffffff b'\x00\x03\x19\n\x05\x0f\x00\xff\xff\xff\xff'
#    thermostat asked damper for its status and damper replied with this
#    0319 is only reported by damper, not by anything in the system1 system
#    0a 05 0f 00 ff ff ff ff is 8 bytes -- 4 zone damper with 3 zones connected
#    at 14:22 MBR temp stepped up to 77 (setpoint 76)
#    at 17:08 Guest temp stepped up to 78 (setpoint 77)
#    Kitchen and Living reached 80 at 15:58, 79 at 14:23 (setpoint 77)
#    
#    four distinct values before 17:00
#      15:09     09 03 (rest are unchanged)
#      15:31:03  09 04
#      16:22:55  0a 04
#      16:34:00  0a 05

# register(3404) to 0x6001 from 0x2001 len 4 WRITE(0xc) register(3404) value 00 
#    thermostat told damper to make theis change
#    3404 is written by both systems but did not change in two hours to evening
#    system2 value 30, system1 value 15 (0x1e, 0x0f)
