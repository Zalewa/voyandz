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


Current State
=============

Very early development. Doesn't work and doesn't do anything yet.


Development
===========

Requirements:

- Python 3
- virtualenv
- make

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
