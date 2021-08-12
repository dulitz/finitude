# syntax=docker/dockerfile:1

# by default, we build for Raspberry Pi (arm32v7)
# FROM python:3.8-slim-buster
FROM arm32v7/python:3.8-slim-buster

MAINTAINER dulitz@gmail.com

WORKDIR /app

RUN apt-get update
RUN apt-get install -y git

RUN mkdir /var/lib/finitude

# the next line causes the Docker cache to be invalidated when req.txt changes
ADD https://raw.githubusercontent.com/dulitz/finitude/master/req.txt /var/lib/finitude/req.txt

RUN pip3 install -r /var/lib/finitude/req.txt

# the next line causes the Docker cache to be invalidated when git changes
ADD https://api.github.com/repos/dulitz/finitude/git/refs/heads/master version.json

RUN cd /home && git clone https://github.com/dulitz/finitude

WORKDIR /home/finitude

RUN cp finitude.yml /var/lib/finitude/

CMD [ "python3", "finitude.py", "/var/lib/finitude/finitude.yml" ]
