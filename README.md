# finitude

Finitude decodes the ABCD bus (RS-485) used by Carrier Infinity and
Bryant Evolution HVAC systems. It runs two webservers: one serves HVAC
`/metrics` in a format that can be queried by
[Prometheus](https://prometheus.io/), a time series database.
Prometheus is a backend for [Grafana](https://grafana.com/)
visualizations/dashboards.

The other webserver is optional. It stores all the WRITE and ACK06
frames seen on the ABCD bus and dumps them as JSON. The functions in
`analysis.py` can then be used to help find meaning in the frames.

## Why?

An HVAC system consumes a lot of energy. You might want to know how
hard it's working, how often it's running, whether it's running when
your windows are open...

Carrier's apps are crappy and they no longer even have a functioning
webapp. Plus it's nice to be able to monitor your equipment without
relying on connectivity to Carrier's servers.

Carrier's SAM module provides significant information about the modes
of the system. But it does not report the state of the system: when
heating and cooling are actually operating, the current fan speed,
the zones to which the dampers are directing airflow, etc.

## How?

To start with, you'll need an RS-485 adapter that can attach to the
wires of Carrier's ABCD bus. If you have a Raspberry Pi or some other
computer near one of the Carrier devices, you can use a [USB RS-485
adapter](https://www.amazon.com/gp/product/B08SM5MX8K). If you don't
have a nearby computer but you do have Ethernet near one of the
Carrier devices, you can use an [Ethernet RS-485
bridge](https://www.amazon.com/gp/product/B07C1TC165).

You can install finitude from PyPI using pip:
```
pip install finitude
```

Soon you'll be able to install an image from Docker Hub. But not yet.

## Based On

* [https://github.com/3tones/brybus](brybus) -- This is unmaintained
since 2014, but it's simple so that's where I started.

* [https://github.com/nebulous/infinitude](infinitude) -- This doesn't
focus on RS-485; instead it proxies the thermostat's network traffic
to/from Carrier's servers and intercepts/modifies the data stream. It
also has an RS-485 parser as a sidelight.  If it weren't written in
Perl I might have started there. Props to nebulous for continuing to
support this.

* [https://github.com/acd/infinitive](infinitive) -- This is
unmaintained since 2018, but the Go code is clear and there is still
an active user community. It does focus on RS-485. It doesn't support
multi-zone systems and some of its info fields are only populated
by legacy heat pumps.
