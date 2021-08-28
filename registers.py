"""
registers.py

register info from https://github.com/acd/infinitive/blob/master/infinitive.go
and https://github.com/acd/infinitive/blob/master/tables.go

See also
https://github.com/nebulous/infinitude/wiki/Infinity---interpreting-data
"""

import struct

from enum import Enum, IntEnum


class FanMode(IntEnum):
  AUTO = 0
  LOW = 1
  MEDIUM = 2
  HIGH = 3


class HvacMode(IntEnum):
  HEAT = 0      # heat source: "system in control"
  COOL = 1
  AUTO = 2
  # FIXME: is "ELECTRIC" the mode for "furnace only" for a gas furnace w/ heat pump?
  # TODO: SAM cannot set EHEAT "emergency heat" on Touch thermostats -- does this
  # fail to work as a mode for Touch thermostats when we try to set it?
  ELECTRIC = 3  # heat source: electric only
  HEATPUMP = 4  # heat source: heat pump only
  OFF = 5

  
class Field(Enum):
    UNKNOWN = 0
    UTF8 = 1   # NUL-padded at the end
    NAME = 2   # 12-byte NUL-padded UTF-8 name
    UINT8 = 3
    INT8 = 4
    UINT16 = 5
    # INT16 = 6  # not implemented
    REPEATING = 99  # the rest of the fields may repeat 0 or more times

    @staticmethod
    def parse(cursor, reps, field):
        """cursor is a bytes object, reps is a count of repetitions, and
        field is one of our enum members. We return a tuple
          (value, nextcursor)
        where value is the parsed value of the field and nextcursor is cursor
        after consuming the field.
        """
        if field == Field.NAME:
            assert reps == 1, (reps, field)
            reps, field = 12, Field.UTF8
        if field == Field.UTF8:
            assert reps > 0, (reps, field)
            return (cursor[0:reps].decode(errors='ignore').strip('\0'), cursor[reps:])
        assert reps == 1, (reps, field)
        if field == Field.UINT8:
            return (cursor[0], cursor[1:])
        if field == Field.INT8:
            return (struct.unpack('>b', cursor[0:1])[0], cursor[1:])
        if field == Field.UINT16:
            return (struct.unpack('>H', cursor[0:2])[0], cursor[2:])
        assert False, (reps, field)


REPEATED_8_ZONES = -1

_REGINFO = [
  (1, Field.UINT8, 'Unknown1'),  # often 0
  (1, Field.UINT8, 'Unknown2'),  # 0x20, 0x21, 0x30, ...
  (8, Field.UTF8, 'TableName'),
  (1, Field.UINT8, 'Unknown3'),  # 0 or 1
  (1, Field.UINT8, 'Unknown4'),  # 0xbc, 0x19, 0x63, ...
  (1, Field.UINT8, 'NumRegisters'),
  (0, Field.REPEATING, 'Registers'), # one rep per register in NumRegisters
  # Registers in this table may still return NACK if you try to read them;
  # maybe they are unreadable in certain modes, or maybe something else.
  # Length and type both 0xde mean register does not exist under some
  # conditions (all conditions?): heat pump 5201.
  (1, Field.UINT8, 'Length'),    # if 0, register does not exist
  (1, Field.UINT8, 'Type'),  # 0: does not exist, 1: read-only, 3: read-write
  ]

REGISTER_INFO = {
  #######################################################
  # table 01 DEVCONFG

  # RegInfo01 is read-only from all devices (unread)
  # no response 6001, 9201
  '000101': ('RegInfo01', _REGINFO),

  # AddressInfo is read-only from all devices (unread)
  # NACK 0a from 2001
  '000102': ('AddressInfo', [
    (1, Field.UINT8, 'DeviceClass'),  # MSB of the address
    (1, Field.UINT8, 'DeviceBus'),    # LSB of the address
    (1, Field.UINT8, 'Unknown'),      # zero
    ]),

  # read-only from 4001, 5201, 6001, 8001 (unread)
  # NACK 0a from 2001, no response 9201
  '000103': ('UnknownInfo0103', [
    (1, Field.UINT8, 'Unknown1'),  # 0x60
    (1, Field.UINT8, 'Unknown2'),  #    0
    (1, Field.UINT8, 'Unknown3'),  #    0
    (1, Field.UINT8, 'Unknown4'),  #    0
    ]),

  # DeviceInfo is read-only from all devices (read by thermostat and SAM)
  '000104': ('DeviceInfo', [
    (48, Field.UTF8, 'Module'),
    (16, Field.UTF8, 'Firmware'),
    (20, Field.UTF8, 'Model'),
    (36, Field.UTF8, 'Serial')
  ]),

  # 0105: 01 followed by all zeroes from 4001, 5201, 6001, and 9201
  # NACK from 2001, no response from 8001

  # 0106: 0000 6358 5800 for 4001, 5201, 8001
  # NACK from 2001, no response from 6001

  # DEVCONFG has documented all registers in RegInfo01

  #######################################################
  # table 02 SYSTIME

  # RegInfo02 is read-only, unread
  # no response from 6001, 8001, 9201
  '000201': ('RegInfo02', _REGINFO),

  # SysTime and SysDate are read/write, non-segmented.
  # Thermostat broadcasts updated time and date every minute.
  '000202': ('SysTime', [
    (1, Field.UINT8, 'Hour'),
    (1, Field.UINT8, 'Minute'),
    (1, Field.UINT8, 'DayOfWeek')  # 0 = Sunday, 6 = Saturday
  ]),
  '000203': ('SysDate', [
    (1, Field.UINT8, 'Day'),
    (1, Field.UINT8, 'Month'),
    (1, Field.UINT8, 'Year')
  ]),

  # only thermostat has 0205, 0206, 0207, 0208, 0209, 020a

  # 0205 both systems: 0000 5000 4eff ff00 004e 4e4e 4e00 6d79 4856 4143 0000000000000000000000000000000000000000000000000000 6876 6163 7379 7374 656d 000000000000000000000000000000000000000000 0009 ffff ffff ffff 0000 0000

  # 0206 both systems: 0000 0000 0000 0000

  # 0207 both systems: 0000 0000

  # 0208 both systems: 0000

  # 0209 both systems: 0103 02b9 0309 0143

  # 020a both systems: 0000

  # SYSTIME has documented all registers in RegInfo02

  #######################################################
  # table 03 INGUI for thermostat 2001

  # 0301 same as RLCSMAIN
  # 0302 present but different from Temperatures
  # 0303-0309 NACK
  # 030a: 1111 1111 1111 1111 1111 1111 1111
  # 031c: NACK

  # INGUI has documented all registers in RegInfo03

  #######################################################
  # table 03 RLCSMAIN 4001, 5201

  # TODO: document r/w for all RegInfo registers in all tables

  # 4001 has 0304, 0305 (r/w), 0306, 0307-0308 (r/w), 030a, 030b-030c (r/w),
  #      030d-0317, 0318 (r/w), 0319, 031c (r/w)
  # 6001 has 0308 (r/w), 030a-0315, 0317, 0318 (r/w), 0319
  # SAM 9201 has 030c (r/w), 030d, 030e, 030f, 0312 (r/w)

  # RegInfo03 is read-only (unread)
  # 8001 no response
  '000301': ('RegInfo03', _REGINFO),

  # Temperatures is read-only 4001, 5201, 6001, 8001 (read by thermostat 2001)
  '000302': ('Temperatures', [
    # types 01, 02, 03, 04 ... 08, 0x14, and 1c from damper control
    # types 0x11, 0x14, and 02 from air handler (all open circuit in our systems)
    # types 0x11, 0x12, 0x30, 4a, 4b, 0x45 from heat pump (all present on system 2)
    #    zone temperature sensors 01, 02, ... 08
    #    outdoor air temperature is type 17 (0x11)
    #    LAT (leaving air temperature) is type 20 (0x14)
    #    HPT (heat pump temperature) is type 28 0x1c
    #    outdoor coil temperature is type 48 (0x30)
    #    discharge line temperature is type 69 (0x45)
    #    type 74 (0x4a) seems to be a difference: usually 0 or 1, goes up
    #       when system in use
    #    type 75 (0x4b) is about 6 degrees less than OAT in all conditions
    #    suction tube temperature is type 18? 18 goes up somewhat during use
    (0, Field.REPEATING, 'TempSensors'),
    (1, Field.UINT8, 'State'),  # 01 = connected, 04 = open circuit
    (1, Field.UINT8, 'Type'),
    (1, Field.UINT16, 'TempTimes16'),
    # 0x8001 ends at 1 rep, 0x4001 ends at 3 reps, 0x5201 and 0x6001 end at 6 reps
  ]),

  # read-only heat pump 5201 (from thermostat 2001)
  # 6001, 8001: no response
  '000303': ('UntitledHeatPump', [
    (4, Field.UNKNOWN),  # 01 30 0b f0
  ]),

  # 0304 read-only (unread)
  # 5201: 0118 003c 0117 00e9 0541 0000 0044 0000
  # 6001: no response
  # 8001: NACK 0a

  # 0305
  # 5201: NACK 0a
  # 6001, 8001: no response

  # Infinitive: read-only air handler 4001, 4101, 4201
  # 5201: NACK 0a
  # 6001: no response
  # 8001: no response
  '000306': ('AirHandler06', [
    (1, Field.UNKNOWN),
    (1, Field.UINT16, 'BlowerRPM')
  ]),

  # read-write unsegmented air handler 0x4001 (from themostat 0x2001)
  # 4001: 00 00 00 (possibly one more byte when writing, in some conditions??)
  # 5201: NACK 0a
  # 6001: no response
  # 8001: no response
  '000307': ('UntitledAirHandler07', [
    (3, Field.UNKNOWN)
  ]),

  # DamperControl is read-write, non-segmented, to damper control 0x6001
  # (by thermostat 0x2001). DamperState(0319) is the corresponding read-only
  # state register. Each damper control module will ignore either
  # zones 1-4 or zones 5-8 according to DIP switch settings.
  # 4001: 00 00
  # 5201: NACK 0a
  # 8001: NACK 0a
  '000308': ('DamperControl', [
    (REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')  # 0 closed, 0xf full open
  ]),

  # 0309
  # 4001, 5201: NACK 0a
  # 6001, 8001: no response

  # 030a
  # 4001, 6001: no response
  # 5201: 03 03 03 05 05 20 00 30 0001 0000 0000
  # 8001: 0c 00 00 00 00 00 00 00 0000 0000 0000

  # 030b
  # 4001, 5201, 6001: 0000 0000
  # 8001: no response

  # 030c
  # 4001, 5201, 6001, 8001: 4949 ("II")

  # read-only from all devices including SAM (by thermostat 0x2001)
  # 7 bytes usually all zeroes; heat pump 14 bytes usually all zeroes;
  # SAM 3d 3f 00 0000 0000 alternates with 3f 00 00 0000 0000
  # '00030d':

  # are these counters?
  '00030e': ('UnknownOneByte', [
    (0, Field.REPEATING, 'OneByte'),
    (1, Field.UINT8, 'Tag'),
    (1, Field.UINT8, 'Value'),
  ]),
  # 4001 system 1: 0c00 0d00 0e00 0f00 1500 1600 1700 1800 1900 1f00 20ff 2110 2202 2300 2900 2a02 2bff 2c00 2d00
  # 4001 system 2: 0c00 0d24 0e78 0f00 1500 1600 1700 1800 1900 1fff 20ff 2176 22ff 2300 2900 2aff 2bff 2c00 2d00
  # 5201: 1900 1f00 2d00 3000 3400 3500 3600 3700 3800 3900 3a00 4200 4300 4404 4500 4700 4a00 4c00 5200 5300 5400 5600 5800 5f00 6000 6100 6202 6301 0000000000000000000000000000000000000000000000000000000000000000000000000000
  # 6001: no response
  # 8001: 1006 2d00 2e09 3500

  # are these counters?
  # the tags are related to the tags in register 030e
  '00030f': ('UnknownTwoByte', [
    (0, Field.REPEATING, 'TwoByte'),
    (1, Field.UINT8, 'Tag'),
    (1, Field.UINT16, 'Value'),
  ]),
  # 4001: 0c0000 0d0000 0e0000 0f0000 150000 160000 170000 180000 190000 1f0000 200263 210012 220003 230000 290000 2a0003 2b26d8 2c0000 2d0000
  # 5201: 190000 1f0000 2d0000 300000 340000 350000 360000 370000 380000 390000 3a0000 420000 430000 440004 450000 470000 4a0000 4c0000 520000 530000 540000 560000 580000 5f0000 600000 610000 620002 630001 serialnumber[343431393033323031393000323031394530393631322020202020202020202020202020] 368fc2060e5872000000000000f601a78d4411010f
  # 6001: 100006 18000a 2d0000 2e0001 340000 360000 370000
  # 8001: 100006 2d0000 2e0009 350000

  # are these counters?
  # seems to be the same as 0314 (except for 6001)
  '000310': ('UnknownThreeByte', [
    (0, Field.REPEATING, 'ThreeByte'),
    (1, Field.UINT8, 'Tag'),
    (1, Field.UINT8, "Unknown"),
    (1, Field.UINT16, 'Value'),
  ]),
  # 4001: 2300db9c 240001e2 27000da0 28000000 2b0003e1 2d012701 480002a8
  # 5201: 23000348 2800008d 3c0001a0 2b000007
  # 6001: no response
  # 8001: 23000001 24000000 28000872 2700052d 3c000000 380034b9 3900002a 2b000063

  # are these counters?
  # these tags are related to the tags in 0310
  # seems to be the same as 0315
  '000311': ('UnknownThreeByteBookend', [
    (0, Field.REPEATING, 'ThreeByte'),
    (1, Field.UINT8, 'Tag'),
    (1, Field.UINT8, "Unknown"),
    (1, Field.UINT16, 'Value'),
  ]),
  # 4001: 25002524 26000068 290002d6 2a000000 2e00693a 2c01952f 49000134
  # 5201: 25000c05 2a000384 3d00001c 2c002580
  # 6001: no response
  # 8001: 25000000 26000000 2a00006d 29000001 3d000000 3a001447 3b0042d5 2c019462

  # 0312
  # 4001: 000000000000000000000000000000000000000000000000000000000000000000000000000000000000
  # 5201: NAK 0a
  # 6001: 0710 1323 060a 1410 0b34 0402 1410 0411 100c 1318 080f 0e03 1318 0931 1902 1310 0931 1902 1310 0323 1008 11
  # 8001: 0710 1222 060a 1410 1326 1806 142e ffff ffff ff2e 0612 1002 0d2e 052c 1002 0d2e 0409 1002 0d2e 0227 1002 0d

  # 0313
  # 4001: f0
  # 5201, 8001: c9
  # 6001: no response

  # 0314 seems to be the same as 0310 (except for 6001)
  # 4001: 2300db9c 240001e2 27000da0 28000000 2b0003cc 2d012701 480002a8
  # 5201: 23000348 2800008d 3c0001a0 2b000007
  # 6001: 38001d6c 39003802 2b0007b5
  # 8001: 23000001 24000000 28000872 2700052d 3c000000 380034b9 3900002a 2b000063

  # 0315 seems to be the same as 0311
  # 4001: 25002524 26000068 290002d6 2a000000 2e00693a 2c01952f 49000134
  # 5201: 25000c05 2a000384 3d00001c 2c002580
  # 6001: no response
  # 8001: 25000000 26000000 2a00006d 29000001 3d000000 3a001447 3b0042d5 2c019462

  # Infinitive: read-only air handler 4001, 4101, 4201
  # 4001: all fields zero with unparsed 0000 0078 0100 020d
  # 5201: NAK 0a
  # 6001: no response
  # 8001: all fields zero with unparsed 0000 0000 0100 0000 00
  '000316': ('AirHandler16', [
    (1, Field.UINT8, 'State'),  # State & 0x03 != 0 when electric heat is on
    (3, Field.UNKNOWN),
    (1, Field.UINT16, 'AirflowCFM')
  ]),

  # 0317
  # 4001: 07210b37080515210f0c010515210e0f16041521131e150415210f22040215210c00000000000000000000
  # 5201: 07440e161c071504ec052a030d2bef7704db040992012a0000000000000000cb0304a062110114031502b3028c0306541977060b0905fa0258000000000000000017015e7163110114031502b3028c0306541977060b0905fa0258000000000000000017015e716210151b0a1403ce0392030a5b1b7605d108054002580000000000000000f601a78d4411010f0a1404cc050b030a29ef7404a8030990027c0000000000000000c0030d964412170d08140560054e03054bef77050804098801360000000000000000f702e6a3440a221707140406042c030724ef76030e020971000000000000000000005603ab8b
  # 6001: 07101323060a14100b34040214100411100c13180931190213100931190213100323100811100913040b0b
  # 8000: 07101222060a141013261806142effffffffff2e061210020d2e052c10020d2e040910020d2e022710020d

  # 0318
  # 4001: no response
  # 5201, 6001, 8001: 49

  # DamperState is read-only damper control 0x6001 (by thermostat 0x2001).
  # DamperControl(0308) is the corresponding writable control.
  # Zones 1-4 or zones 5-8 will be reported as 0xff for zones not connected
  # to this device according to DIP switch settings.
  # 4001 has this register but it is shorter [0000] and means something else *****
  # 5201 has this register but it is shorter [0011] and means something else *****
  # 8001: NACK 0a
  '000319': ('DamperState', [
    (REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')  # 0xff for zone not present
  ]),

  # 031a
  # 4001 5201: NACK 0a
  # 6001, 8001: no response

  # 031b
  # 4001, 8001: NACK 0a
  # 5201: 03
  # 6001: no response

  # LastStatus is read-only air handler 4001, heat pump 5201 (unread)
  # 2001, 6001, 8001: NACK 0a
  # 9201: no response
  '00031c': ('LastStatus', [
    (1, Field.UINT8, 'StatusCode'),  # "fault code" for faults
    # 1 = event, 2 = fault, 3 = system malfunction
    (1, Field.UINT8, 'Severity'),
    (38, Field.UTF8, 'Message')
  ]),

  # 031d
  # 4001, 5201, 6001, 8001: NACK 0a

  # 031e
  # 4001, 5201, 8001: NACK 0a
  # 6001: no response

  # 031f
  # 4001, 6001, 8001: NACK 0a
  # 5201: 208 zero bytes

  # 0320
  # 4001, 6001, 8001: NACK 0a
  # 5201: 208 zero bytes

  # 0321
  # 4001, 6001, 8001: NACK 0a
  # 5201: 208 zero bytes

  # 0322
  # 4001: NACK 0a
  # 6001, 8001: no response

  # 0323
  # 4001, 6001, 8001: NACK 0a

  # 0324
  # 4001, 6001, 8001: NACK 0a

  # 0325
  # 4001: NACK 0a
  # 6001, 8001: no response

  # 0326
  # 4001, 8001: NACK 0a
  # 6001: no response

  # RLCSMAIN has documented all registers in RegInfo02 for device 5201

  #######################################################
  # table 04 SSSBCAST for thermostat 2001

  # 0401 RegInfo04
  # 0420 0000000000000000000000000000000000000000

  # SSSBCAST has documented all registers in RegInfo04

  #######################################################
  # table 04 SAM INTF for SAM 9201

  # 0401 RegInfo04
  # 040e 5033303336363331000000000000000021
  # 0420 000073ffff57ff5700ffff031854186a54540000

  # SAM INTF has documented all registers in RegInfo04

  #######################################################
  # table 04 VARSPEED for air handler 4001

  # 5201 NACKs all registers including RegInfo04
  # 6001 no response to any register except to 0402 and 0409: NACK 04
  # 8001 NACKs most registers inluding RegInfo04, no response to the others

  # RegInfo04 is read-only, unread
  '000401': ('RegInfo04', _REGINFO),

  # 0402 5a7896b4781d 358ec4741d 34978da41d b4eaad511d 324813a602 3004ba02c6 (sys 1)
  # 0402 5a7896b4781d 34b0fee01d 36054aa81d b5e462881d 34a265e902 3005a002cb (sys 2)

  # read-write unsegmented air handler 0x4001 (from themostat 0x2001)
  '000403': ('UntitledAirHandler03', [
    (4, Field.UNKNOWN)  # 00 01 01 00 when operating or not, COOL mode
  ]),

  # 0404 1078 1006 0207 0000 0000 00000000 000a 0000 (sys 1)
  # 0404 1078 1206 0a37 0518 04d1 00000000 000a 0605 (sys 2)

  # 0405 0100 0000 0000 0000 020000 0000 0000 0000 0100000000 (sys 1)
  # 0405 0110 0000 7800 0500 000000 000f 0019 0000 0100000000 (sys 2)

  # 0406 0000 0000 0000 0000 0000 0078 01 (sys 1)
  # 0406 0000 0200 051d 0000 0000 0078 01 (sys 2)

  # 0407 0000 (sys 1)
  # 0407 0519 (sys 2)

  # 0408 00 0000 0000

  # read/write, non-segmented air handler 0x4001
  # (from thermostat 0x2001).
  '000409': ('UntitledAirHandler', [
    (4, Field.UNKNOWN),  # most bytes zero, second byte sometimes 1
  ]),

  # 040a-040b NACK 0a

  # read-only (?) 4001 (from thermostat 2001).
  # NACKed by 58MVC
  # '00041b'

  # VARSPEED has documented all registers in RegInfo04

  #######################################################
  # table 05

  # 0501: NACK 04 by 2001, 4001, 5201, 6001, 8001, 9201

  #######################################################
  # table 06 LINESET for thermostat 2001

  # RegInfo06 is read-only, unread
  # NACK 04 by 8001, 9201
  '000601': ('RegInfo06', _REGINFO),

  #######################################################
  # table 06 VAR COMP for heat pump 5201

  # read-write unsegmented heat pump 0x5201 (from themostat 0x2001)
  '00060d': ('UntitledHeatPump0d', [
    (1, Field.UINT8, 'Unknown')
  ]),

  # read-write unsegmented heat pump 0x5201 (from themostat 0x2001)
  '000610': ('UntitledHeatPump10', [
    (4, Field.UNKNOWN)
  ]),

  # read-write unsegmented heat pump 0x5201 (from themostat 0x2001)
  '00061a': ('UntitledHeatPump1a', [
    (1, Field.UINT8, 'Unknown')
  ]),

  #######################################################
  # table 30 EECONFIG

  '003001': ('RegInfo30', _REGINFO),

  # read-only (?) thermostat 0x2001 (from SAM 0x9201)
  # appears to be NACKed by Touch thermostat firmware 3.60
  # '003005'

  #######################################################
  # table 34 [NIM or damper control module] 4 ZONE

  '003401': ('RegInfo34', _REGINFO),

  # HVRState is read/write, non-segmented damper control 0x6001
  # (from thermostat 0x2001).
  # TODO: is this also sent to the NIM in system 1?
  '003404': ('HRVState', [
    (1, Field.UINT8, 'Speed')  # 0 off, 1 low, 2 med, 3 high
  ]),

  #######################################################
  # table 3b [thermostat] AI PARMS / NVMINIT

  '003b01': ('RegInfo3b', _REGINFO),

  # Infinitive: read/write segmented; thermostat 0x2001
  '003b02': ('TStatCurrentParams', [
    # first field is not in Infinitive -- may be unique to Touch thermostats
    # may be the set of zones that are configured/active
    (1, Field.UINT8, 'ZonesUnknown'),
    # this field is also not in Infinitive and may be unique to Touch
    # seems to always be 0
    (2, Field.UNKNOWN),  # not in Infinitive
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentTemp'),
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentHumidity'),
    (1, Field.UNKNOWN),  # typically 0
    (1, Field.INT8, 'OutdoorAirTemp'),  # -1 if sensor not present
    (1, Field.UINT8, 'ZonesUnoccupied'),  # LSB is zone 1, MSB is zone 8
    # high order nybble of Mode is the stage number
    # low order nybble is defined by HvacMode enum
    (1, Field.UINT8, 'Mode'),  # segment 0x10
    (5, Field.UNKNOWN),  # typically 255, 0, 0, 4, 89
    (1, Field.UINT8, 'DisplayedZone')
  ]),

  # Infinitive: read/write segmented; thermostat 0x2001
  '003b03': ('TStatZoneParams', [
    # first field is not in Infinitive -- may be unique to Touch thermostats
    # may be the set of zones that are configured/active
    (1, Field.UINT8, 'ZonesUnknown'),
    # this field is also not in Infinitive and may be unique to Touch
    (2, Field.UNKNOWN),  # not in Infinitive; typically 0
    (REPEATED_8_ZONES, Field.UINT8, 'FanMode'),  # segment 1
    (1, Field.UINT8, 'ZonesHolding'),  # segment 2; LSB is zone 1, MSB is zone 8
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentHeatSetpoint'),  # segment 4
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentCoolSetpoint'),  # segment 8
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentHumidityTarget'),
    # FanAutoConfig is probably what the SAM refers to as "programmable fan."
    # If so, it cannot be turned off for Touch thermostats.
    (1, Field.UINT8, 'FanAutoConfig'),  # 1 if fan speed controlled by system
    # This unknown field is probably a bitmap of zones where the
    # "hold until" override timer is in use. TODO: verify this
    (1, Field.UNKNOWN),
    # HoldDuration is probably what the SAM refers to as the
    # "hold until" override timer, which is 0 if not in use. TODO: verify this
    (REPEATED_8_ZONES, Field.UINT16, 'HoldDuration'),
    (REPEATED_8_ZONES, Field.NAME, 'Name')
  ]),

  # Infinitive: read/write segmented; thermostat 0x2001.
  # We have not seen this frame live with Infinity Touch thermostats, but
  # the SAM documentation says it should work with Touch.
  '003b04': ('TStatVacationParams', [
    (1, Field.UINT8, 'Active'),  # segment 1: 1 if vacation is active, 0 otherwise
    (1, Field.UINT16, 'Hours'),  # segment 2
    (1, Field.UINT8, 'MinTemp'),  # segment 4
    (1, Field.UINT8, 'MaxTemp'),  # segment 8
    (1, Field.UINT8, 'MinHumidity'),  # segment 0x10
    (1, Field.UINT8, 'MaxHumidity'),  # segment 0x20
    (1, Field.UINT8, 'FanMode')  # segment 0x40
  ]),

  # read/write segmented; thermostat 0x2001 (by SAM).
  '003b06': ('TStatUntitled', [
    (1, Field.UINT8, 'ValidZones'),  # some zone bitmap, could be this
    (11, Field.UNKNOWN), # typically 0, 0, 1, 1, 2, 2, ff, ff, 1, 0, 0
    (20, Field.UTF8, 'DealerName'), # not writable for Touch thermostats
    (20, Field.UTF8, 'DealerPhone'), # not writable for Touch thermostats
  ]),

  # read-write SAM 0x9201 (by thermostat 0x2001).
  # thermostat writes 01 after setpoint update
  '003b0e': ('SAMUntitled', [
    (1, Field.UINT8, 'Unknown')
  ]),

  # thermostat/SAM info still to determine:
  #   get humidifier state
  #   get/set percentage used: filter, UV lamp, humidifier pad; ventilator pad
  #      (note: can only set 0 percent used)
  #   enable/disable reminders: filter; UV lamp; humidifier pad; ventilator pad
  #   enable/disable high intensity backlight
  #   get/set thermostat units
  #   get AUTO mode enable (always on)
  #   get system type (cool/heat/heatcool)
  #   get deadband
  #   get cycles per hour
  #   get programming state (always on)
  #
  # fields not supported by Touch:
  #   set current day of week
  #   enable/disable AUTO mode
  #   set deadband
  #   set cycles per hour
  #   enable/disable programmable fan
  #   set number of periods for programming
  #   set programming state
  #   set program for WAKE/DAY/EVE/SLEEP period
  #      for each period, for each day: heat setpt, cool setpt, fanmode
  #   reset factory defaults

  # heat pump info still to determine (from 25VNA8/24VNA9 Service Manual):
  # status:
  #   Suction Thermistor (on suction tube)
  #   inverter/VSD output frequency and amplitude (?)
  #   outdoor fan motor speed (?) -- between 400 and 1050 RPM
  #   suction pressure transducer used to perform low-pressure cutout, etc.
  #   utility curtailment relay wired between UTIL connections on the control board
  #     - reports "curtailment YES" in the thermostat UI when relay closed
  #   fault code reported in thermostat UI
  #   touch UI service mode: press and HOLD service icon for 10 seconds
  #   charging mode in Touch UI service mode: service valve subcooling target temp,
  #     stabilization time, mode/stage(out of 5)/speed (up to 3200 rpm),
  #     EXV position 0-100%, and indoor airflow.

  # possible status or control of Pressure Equalizer Valve (used at startup)

  # control:
  #   service UI manual closing/opening of Electronic Expansion Valve (EXV)
  #   service UI has heat source lockout settings
  #   service UI selectable defrost intervals of 30, 60, 90, or AUTO minutes
  #   service UI has "full installation" button to be used when address changes
  #   service UI has "test mode" to test heating/cooling at full capacity

  #######################################################
  # table 3e DCLEGACY

  # Infinitive says this is read-only from heat pump 0x5001 or 0x5101.
  # 25VNA8 responds NACK 04
  '003e01': ('LegacyHeatPumpTemperatures', [
    (1, Field.UINT16, 'OutsideTempTimes16'),
    (1, Field.UINT16, 'CoilTempTimes16')
  ]),

  # Infinitive says this is read-only from heat pump 0x5001 or 0x5101.
  # 25VNA8 responds NACK 04
  '003e02': ('LegacyHeatPumpStage', [
    # Shift right by one bit to get the stage number.
    # Higher stage numbers correspond to auxilliary heat on.
    (1, Field.UINT8, 'StageShift1')
  ]),
}
