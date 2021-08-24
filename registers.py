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


REPEATED_8_ZONES = 0

REGISTER_INFO = {
  #######################################################
  # table 01 DEVCONFG

  # DeviceInfo is read-only (read by thermostat and SAM)
  '000104': ('DeviceInfo', [
    (48, Field.UTF8, 'Module'),
    (16, Field.UTF8, 'Firmware'),
    (20, Field.UTF8, 'Model'),
    (36, Field.UTF8, 'Serial')
  ]),

  #######################################################
  # table 02 SYSTIME

  # SysTime and SysDate are read/write, non-segmented.
  # Thermostat broadcasts updated time and date every minute.
  '000202': ('SysTime', [
    (1, Field.UINT8, 'Hour'),
    (1, Field.UINT8, 'Minute')
  ]),
  '000203': ('SysDate', [
    (1, Field.UINT8, 'Day'),
    (1, Field.UINT8, 'Month'),
    (1, Field.UINT8, 'Year')
  ]),

  #######################################################
  # table 03 RLCSMAIN / INGUI

  # Infinitive: read-only air handler device 0x4001, 0x4101, 0x4201
  '000306': ('AirHandler06', [
    (1, Field.UNKNOWN),
    (1, Field.UINT16, 'BlowerRPM')
  ]),

  # DamperControl is write-only, non-segmented, to damper control 0x6001
  # (by thermostat 0x2001). DamperState(0319) is the corresponding read-only
  # state register. Each damper control module will ignore either
  # zones 1-4 or zones 5-8 according to DIP switch settings.
  '000308': ('DamperControl', [
    (REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')  # 0 closed, 0xf full open
  ]),

  # Infinitive: read-only air handler device 0x4001, 0x4101, or 0x4201
  '000316': ('AirHandler16', [
    (1, Field.UINT8, 'State'),  # State & 0x03 != 0 when electric heat is on
    (3, Field.UNKNOWN),
    (1, Field.UINT16, 'AirflowCFM')
  ]),

  # DamperState is read-only damper control 0x6001 (by thermostat 0x2001).
  # DamperControl(0308) is the corresponding write-only control.
  # Zones 1-4 or zones 5-8 will be reported as 0xff for zones not connected
  # to this device according to DIP switch settings.
  '000319': ('DamperState', [
    (REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')  # 0xff for zone not present
  ]),

  #######################################################
  # table 34 [NIM or damper control module] 4 ZONE

  # HVRState is read/write, non-segmented damper control 0x6001
  # (from thermostat 0x2001).
  '003404': ('HRVState', [
    (1, Field.UINT8, 'Speed')  # 0 off, 1 low, 2 med, 3 high
  ]),

  #######################################################
  # table 3b [thermostat] AI PARMS / NVMINIT

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
    (REPEATED_8_ZONES, Field.UINT8, 'CurrentHumiditySetpoint'),
    (1, Field.UINT8, 'FanAutoConfig'),  # 1 if fan speed controlled by system
    (1, Field.UNKNOWN),
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

  # thermostat/SAM info still to determine:
  #   get current day of week
  #   get humidifier state
  #   per-zone "hold until" override timer-in-use
  #   get/set per-zone "hold until" override timer (0 if not in use)
  #   get/set percentage used: filter, UV lamp, humidifier pad; ventilator pad
  #      (note: can only set 0 percent used)
  #   enable/disable reminders: filter; UV lamp; humidifier pad; ventilator pad
  #   enable/disable high intensity backlight
  #   get/set thermostat units
  #   get AUTO mode enable (always on)
  #   get system type (cool/heat/heatcool)
  #   get deadband
  #   get cycles per hour
  #   get programmable fan enable (always on)
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

  #######################################################
  # table 3e DCLEGACY

  # Infinitive: read-only from devices 0x5001 or 0x5101
  '003e01': ('HeatPump01', [
    (1, Field.UINT16, 'OutsideTempTimes16'),
    (1, Field.UINT16, 'CoilTempTimes16')
  ]),

  # Infinitive: read-only from devices 0x5001 or 0x5101
  # shift StageShift1 right by one bit to get the stage number
  # higher stage numbers correspond to auxilliary heat on
  '003e02': ('HeatPump02', [
    (1, Field.UINT8, 'StageShift1')
  ]),
}
