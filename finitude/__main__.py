"""__main__.py for finitude

There are many different subcommands, but none of them exit. We always
loop forever.

If our first command line argument is not RAW, we run the finitude
server and never exit. The second argument is optionally a
configuraton file to use. Environment variables override any
configuration file values.

If our first command line argument is RAW, the second argument must be
the URI of the RS-485 bus adapter.

    If there are no other arguments, we listen on the bus and print each
    parsed frame as it arrives and never exit.

    If there are other arguments they must be four hex characters of source address,
    four hex characters of destination address, the function name, and
    0-3 arguments of hexadecimal text. The frame specified by the arguments
    is written to the bus. We then listen on the bus and print each parsed frame
    as it arrives and never exit.

Examples:

    python -m finitude finitude.yml          run the metrics server forever
    python -m finitude RAW /dev/ttyUSB0      print every frame on the bus forever
    python -m finitude RAW telnet://localhost:2626 2001 3001 READ 3b02
            send a READ frame requesting the value of register 3b02 from
            the thermostat, then print every frame on the bus forever

"""

from finitude import finitude
from finitude import transactions


if __name__ == '__main__':
    import sys, os
    if len(sys.argv) >= 3 and sys.argv[1] == 'RAW':
        sys.exit(transactions.main([sys.argv[0]] + sys.argv[2:]))
    else:
        sys.exit(finitude.main(sys.argv, os.environ))
