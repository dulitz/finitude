"""
sniffersql.py -- 

Reads all packets on the ABCD bus. 
Stores the parsed frames in a SQL table using an ODBC connection
using pyodbc
Here is a sample table definition:
CREATE TABLE [dbo].[messages]
(
    [time] [smalldatetime],
    [origin] [tinyint],
    [destination] [tinyint],
    [function] [tinyint],
    [len] [tinyint],
    [register] [smallint] NULL,
    [data] [varbinary](128) NULL
) ON [PRIMARY] 
Please note that in order to make the database more space efficient the network ID (always 1) has been stripped of the origin and destination of the messages
Therefore origin, destination function and data length(len) are 1 byte columns
register is a 2 byte column since the first byte of the register is always 0
data is variable byte array (128 byte max) and excludes the bytes denoting the register
"""
import pyodbc

from finitude import frames

import socket
import sys
import time
import operator

from datetime import date, datetime



get_printable_address = frames.ParsedFrame.get_printable_address

class Sniffer:
    def __init__(self, stream, db):
        self.stream = stream
        self.bus = frames.Bus(stream) #, report_crc_error=lambda: print('.', end='', file=sys.stderr))
        self.waiting_frames = []
        self.frames = []
        self.current_time = None
        self.current_date = None
        self.current_date_time = None
        self.db = db
        # find the index of the latest message and use it to add new frames
        self.cursor = db.cursor()
        self.cursor.execute("EXEC Sp_spaceused 'messages'")
        row = self.cursor.fetchone()
        self.nframes = int(row[1]) + 1
        self.cursor.fast_executemany = True
    @property
    def date_time_available(self):
        return self.current_time and self.current_date
    def get_current_date_time(self):
        return self.current_date_time
    def read_one_frame(self):
        return frames.ParsedFrame(self.bus.read())

    def empty_waiting_frames(self):
        for f in self.waiting_frames:
            self.record_frame(f)
        self.waiting_frames.clear()

    def flush_to_db(self):
        if len(self.frames) > 0:
            self.cursor.setinputsizes([(pyodbc.SQL_WCHAR, 32, 0), (pyodbc.SQL_TINYINT), (pyodbc.SQL_TINYINT), 
                (pyodbc.SQL_TINYINT), (pyodbc.SQL_TINYINT), (pyodbc.SQL_SMALLINT), (pyodbc.SQL_VARBINARY, 128, 0)])
            self.cursor.executemany("INSERT INTO messages ([time], [origin], [destination], [function], [len], [register], data) values(?,?,?,?,?,?,?)", self.frames)
            self.db.commit()
            self.frames = []
    
    def record_frame(self, frame):
        reg = register_of_frame(frame)
        if reg:
            record = (str(self.current_date_time), frame.source[0], frame.dest[0], frame.func, frame.length,
                        register_as_int(reg), frame.data[3:])
            self.frames.append(record)
            self.nframes += 1
            if len(self.frames) >= 5000:
                self.flush_to_db()


    def process_frame(self, frame):
        reg = register_of_frame(frame)
        if reg and reg[1] == 2 and reg[0] == 0:
            #this is a time or date register 
            reg_name = frame.get_register()
            if reg[2]== 2:
                self.current_time = frame.data[3:5]
                assert(reg_name == 'SysTime')
            elif reg[2] == 3:
                self.current_date = frame.data[3:6]
                assert(reg_name == 'SysDate')
            if self.date_time_available:
                self.current_date_time = datetime(
                    self.current_date[2] + 2000, self.current_date[1], self.current_date[0], self.current_time[0], self.current_time[1])
        if not self.date_time_available:
            self.waiting_frames.append(frame)
        else:
            if len(self.waiting_frames) > 0:
                self.empty_waiting_frames()
            self.record_frame(frame)


#These frame helpers could be methods on the ParsedFrame class 
#but they are only used in this file. 
def register_of_frame(frame):
    if (frame.func == frames.Function.READ or
        frame.func == frames.Function.WRITE or
        frame.func == frames.Function.ACK06) and frame.length >= 3:
        return frame.data[0:3]
    else:
        return None

def register_as_int(reg_data):
    if reg_data is None:
        return None
    else:
        return reg_data[0]*(1 << 16) + reg_data[1]*(1 << 8) + reg_data[2]
#end of helpers

def main(args, outputfile):
    Server = args[2]
    db = pyodbc.connect(Server, autocommit=False)
    try:
        sniffer = Sniffer(frames.StreamFactory(args[1]), db)
        frame = sniffer.read_one_frame()
        print(f'synchronized at: {frame}', file=outputfile)
        while True:
            sniffer.process_frame(frame)
            frame = sniffer.read_one_frame()
    except socket.timeout as ex:
        print(f'caught exception {ex}', file=sys.stderr)
    except KeyboardInterrupt as ex:
        print(f'caught KeyboardInterrupt', file=sys.stderr)
    except frames.CarrierError as ex:
        print(ex, file=sys.stderr)

    sniffer.flush_to_db()
    db.close()
    db = None

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv, sys.stderr))

"""
Usage: python3 sniffer-sql.py /dev/ttyUSB0 <connection_string>
Usage: python3 sniffer-sql.py telnet://192.168.0.7:26 <connection_string>
Usage: python3 sniffer-sql.py localfile://logs/foo.raw <connection_string>
example connection_string: "DRIVER={ODBC Driver 17 for SQL Server};Server=HOSTNAME\SQLEXPRESS;Database=ics-test;Trusted_Connection=yes"
"""
