Voyoffnik Andzej
================

Voyoffnik Andzej (voyandz) is a real-time AV streaming server akin to
the discontinued `ffserver`. Its primary purpose is to enable network
streaming of audio, video or audio & video in form of continuous,
non-seekable streams. The source feed can be any feed that can be
provided in a streamable form through a preinstalled program such as
`ffmpeg`. The output stream can be any stream that can be produced by
a preinstalled program such as `ffmpeg`. Voyoffnik Andzej itself
doesn't delve into codec details, but merely deals with piping.

`ffmpeg` not attached.

Home page: https://github.com/Zalewa/voyandz/

Installation
============

```
  pip3 install voyandz
```

Then run:

```
  voyandz -h
```

Current State
=============

At current stage voyandz is already usable. It is possible to prepare
configuration file that will create a usable pipeline. HTTP clients,
such as browsers or command line downloaders, can be used to connect
to stream endpoints and download the data produced by voyandz.
voyandz will work with as many input feeds and HTTP clients as possible
until it hits soft limits such as CPU power or throughput.

It is currently untested how voyandz will behave during long-time
operation or under heavy usage.


What works
----------

- Home page, stats page - HTML, config dump - dumps config in JSON format.
- Reading and parsing a config-file with defined streams and feeds.
- Piping feeds to streams and then to HTTP clients; creating pipelines.
- YAML configuration files allowing to define transcoding commands, mimetypes,
  client exclusive or shared streams, listen port, listen host.
- A "screenshot" stream that produces one picture and closes connection.
- Logging stderr of commands to a configured logdir.


Unstable
--------

- Config format.
- API.


TODO
----

- Config documentation.
- Config command templating; command args; allow to declare
  multiple similar feeds and streams without having to copy
  and paste the same text all over the config file.
- Code documentation (docstrings).
- Limit stderr logfiles to a set size, even
  though it should be logrotate's job.
- Daemon mode (in the systemd era, should I even be concerned?)
- Dead feed resurrection.


Development
===========

Requirements:

- Python 3
- virtualenv
- make (optional)

Create virtual env, install dependencies, link the application:

```
  python3 -m venv venv
  . venv/bin/activate
  make init
  make dev
```

To start in development mode:

```
  FLASK_ENV=development voyandz -f config/minimal
```

Cleaning:

```
  make clean
  rm -rf venv
```

Repository Structure
====================

Project file structure should adhere to the practices
recommended for Python and Flask projects.

```
  .
  |- config - example configuration files
  |- sandbox - development scraps, experiments
  \- voyandz - application code
```

Name
====

V stands for Video, A stands for Audio, ff implies purpose.
The rest is gibberish. Short name is `voyandz`, all lower-case.

Troubleshooting
===============

**Problem:** Running on Linux and getting
"cannot modify pipe size: [Errno 1] Operation not permitted"
error upon heavy load.

**Solution:**

voyandz makes extensive use of pipes. To improve piping performance,
the size of those pipes is increased using `F_SETPIPE_SZ` `fcntl` calls.
However, Linux kernel imposes a limit on non-root users on how much
memory can be consumed by the pipes by each user. This limit is
controlled through a kernel parameter

```
  fs.pipe-user-pages-soft
```

The value of this parameter is expressed in *pages*, which means the total
allowed size is at least 4kB times this value. You can read more at:
https://patchwork.kernel.org/patch/8055531/

voyandz will continue to operate even if the limit is breached, but all
pipes that try to go above the limit will actually be limited to the
size of one page. Once usage drops and old pipes are closed, new pipes
recover the capability to increase their sizes.

To allow more pipes to be opened with increased size do one of those:

* `sudo sysctl fs.pipe-user-pages-soft=65536` to increase the limit;
  Choose a value right for you if you think 65536 is still not enough.

* `sudo sysctl fs.pipe-user-pages-soft=0` to disable the limit completely

To persist this value between reboots add it to `/etc/sysctl.conf` or
`/etc/sysctl.d/`.

More info: http://man7.org/linux/man-pages/man7/pipe.7.html

Keywords: pipe-user-pages-soft, PermissionError, Operation not permitted
