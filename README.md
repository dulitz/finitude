# finitude

Finitude decodes the ABCD bus (RS-485) used by Carrier Infinity and Bryant Evolution
HVAC systems.

## Why?

An HVAC system consumes a lot of energy. You might want to know how hard it's working,
how often it's running, whether it's running when your windows are open...

Carrier's apps are crappy and they no longer even have a functioning website. Plus it's nice
to be able to monitor your equipment without relying on connectivity to Carrier's servers.

## Based On

* [https://github.com/3tones/brybus](brybus) -- This is unmaintained since 2014, but
it's simple so that's where I started.

* [https://github.com/nebulous/infinitude](infinitude) -- This doesn't focus on RS-485;
instead it proxies the thermostat's network traffic to/from Carrier's servers and
intercepts/modifies the data stream. It also has an RS-485 parser as a sidelight.
If it weren't written in Perl I might have started there. Props to nebulous for
continuing to support this.

* [https://hithub.com/acd/infinitive](infinitive) -- This is unmaintained since 2018,
but the Go code is clear and there is still an active user community. It does focus
on RS-485. There is some question that maybe it isn't compatible with the newer
Infinity Touch thermostats but I never investigated this.
