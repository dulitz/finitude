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
    (1, Field.UINT8, 'Minute'),
    (1, Field.UINT8, 'DayOfWeek')  # 0 = Sunday, 6 = Saturday
  ]),
  '000203': ('SysDate', [
    (1, Field.UINT8, 'Day'),
    (1, Field.UINT8, 'Month'),
    (1, Field.UINT8, 'Year')
  ]),

  #######################################################
  # table 03 RLCSMAIN / INGUI

  # read-only air handler, heatpump, damper control devices 0x4001, 0x5201, 0x6001
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

  # read-only (?) heat pump 0x5201 (from thermostat 0x2001)
  '000303': ('UntitledHeatPump', [
    (4, Field.UNKNOWN),  # 01 30 0b f0
  ]),

  # Infinitive: read-only air handler device 0x4001, 0x4101, 0x4201
  '000306': ('AirHandler06', [
    (1, Field.UNKNOWN),
    (1, Field.UINT16, 'BlowerRPM')
  ]),

  # write-only unsegmented air handler 0x4001 (from themostat 0x2001)
  '000307': ('UntitledAirHandler07', [
    (4, Field.UNKNOWN)
  ]),

  # DamperControl is write-only, non-segmented, to damper control 0x6001
  # (by thermostat 0x2001). DamperState(0319) is the corresponding read-only
  # state register. Each damper control module will ignore either
  # zones 1-4 or zones 5-8 according to DIP switch settings.
  '000308': ('DamperControl', [
    (REPEATED_8_ZONES, Field.UINT8, 'DamperPosition')  # 0 closed, 0xf full open
  ]),

  # read-only from all devices including SAM (by thermostat 0x2001)
  # 7 bytes usually all zeroes; heat pump 14 bytes usually all zeroes;
  # SAM 3d 3f 00 0000 0000 alternates with 3f 0000 0000 0000
  # '00030d':

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
  # table 04 DELUXEUI / SSSBCAST

  # write-only unsegmented air handler 0x4001 (from themostat 0x2001)
  '000403': ('UntitledAirHandler03', [
    (4, Field.UNKNOWN)
  ]),

  # read/write, non-segmented air handler 0x4001
  # (from thermostat 0x2001).
  '000409': ('UntitledAirHandler', [
    (4, Field.UNKNOWN),  # most bytes zero, second byte sometimes 1
  ]),

  # read-only (?) air handler 0x4001 (from thermostat 0x2001).
  # NACKed by 58MVC
  # '00041b'

  #######################################################
  # table 06

  # write-only unsegmented heat pump 0x5201 (from themostat 0x2001)
  '00060d': ('UntitledHeatPump0d', [
    (1, Field.UINT8, 'Unknown')
  ]),

  # write-only unsegmented heat pump 0x5201 (from themostat 0x2001)
  '000610': ('UntitledHeatPump10', [
    (4, Field.UNKNOWN)
  ]),

  # write-only unsegmented heat pump 0x5201 (from themostat 0x2001)
  '00061a': ('UntitledHeatPump1a', [
    (1, Field.UINT8, 'Unknown')
  ]),

  #######################################################
  # table 30 EECONFIG

  # read-only (?) thermostat 0x2001 (from SAM 0x9201)
  # appears to be NACKed by Touch thermostat firmware 3.60
  '003005'

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

  # write-only SAM 0x9201 (by thermostat 0x2001).
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
  #   Touch UI service mode manual closing/opening of Electronic Expansion Valve (EXV)
  #   Touch UI selectable defrost intervals of 30, 60, 90, or AUTO minutes

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
