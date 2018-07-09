Voyoffnik Andzej - SPECIFICATION DOCUMENT
=========================================

Voyoffnik Andzej (voyandz) is a real-time AV streaming server akin to
the discontinued `ffserver`. Its primary purpose is to enable network
streaming of audio, video or audio & video in form of continuous,
non-seekable streams. The source feed can be any feed that can be
provided in a streamable form through a preinstalled program such as
`ffmpeg`. The output stream can be any stream that can be produced by
a preinstalled program such as `ffmpeg`. Voyoffnik Andzej itself
doesn't delve into codec details, but merely deals with piping.

Voyoffnik Andzej is implemented in Python 3 using Flask microframework.


Goals - Main Imperative
=======================

Minimum latency between source feed and target stream.


Goals - Primary
===============

1. Don't limit the nature of the source feed as long
   as it remains streamable.
2. Multiple, independent streams per single feed with configurable
   encoding parameters and container format.
3. Multiple, independent feeds.
4. Reliance on `ffmpeg` while allowing the user to freely choose
   which `ffmpeg`-like binary will be used per each feed and
   output stream.
5. Feeds activated and deactivated on-demand to save resources.
6. Feeds running continuously to support sources that don't handle
   disconnections well.
7. Plain-text configuration file.
8. Built-in screenshot capture feature.


Goals - Secondary
=================

1. Architecture independence (including arm).
2. Platform independence, however the main target platform is Linux.
3. Optional: in-place implementation of MPJPEG to allow direct streaming
   to browser's `img` tag. `ffmpeg` can already do that reliably.


Name
====

V stands for Video, A stands for Audio, ff implies purpose.
The rest is gibberish. Short name is `voyandz`, all lower-case.


Repository Structure
====================

Project file structure should adhere to the best practices
recommended for Python and Flask projects.

Deployment must rely on setuptools.

Makefile may be provided to provide convenient aliases for
otherwisely "arcane" commands.

Source material:

1. http://docs.python-guide.org/en/latest/writing/structure/
2. https://github.com/kennethreitz/samplemod
3. http://flask.pocoo.org/docs/0.12/patterns/distribute/#

Implementation
==============


Protocol
--------

Main communication protocol is HTTP over TCP. Voyandz assumes
that clients will be able to connect to it directly through URLs.
Once client connects to a stream, voyandz will continue to stream
to it until the client closes the connection.

Port on which voyandz will listen must be configurable.

IP address on which voyandz will listen must be configurable.


Logging
-------

All logs are written through Flask's app.logger.

All lines in the log must start with a timestamp in
`YYYY-mm-dd hh:mm:ss.sss` format followed by a single space.

Each start of the program must print the name of the program
and its version in the first line of the log.

Incoming connections should be logged.


Errors
------

All exceptions that cannot be handled gracefully must have
their stack trace logged.

Feeds, streams and connections that raise exceptions
cannot take the whole server down. It's allowed to break
the connection or kill the feed or stream and restart it
if appropriate.

Connections that try to access non existing resources
should end with error 404.


Feeds
-----

Feeds are input pipes where the source material will come *in*.

Feeds can be defined as:

* A path to a file (including a named pipe).
* A command that outputs the feed to stdout.

Feeds should be configurable as:

* Continuous - in this mode the feed will be always active, draining
  resources even if there's no one using it.

* On-demand - in this mode the feed will only be activated when
  at least one connection to a stream configured to use this feed
  is opened. When all related connections are closed, the feed
  must also be closed. This is the default mode.

* Timeout - in this mode the feed will remain alive for a limited
  amount of time even if no one is using it. This mode can minimize
  delays in cases where screenshots are captured rapidly. Timeout
  mode doesn't need to be specified explicitly as a "timeout" keyword,
  but as a number of seconds.

When more than one stream needs a single feed, this single feed must be
used for all streams. The new stream cannot open a duplicate feed.

If feed dies while being used in the "on-demand" mode, or at any time in
the "continuous" mode, it must be resurrected immediately, unless
it's explicitly configured with 'no-resurrect' flag. This also applies
when the input comes from a file or a named pipe. There should be
no limit to resurrection attempts, however repeated failures should
have limited error logging.

Please, no stupid "buffer size" configuration parameters that are
meaningless to the user, to the program and generally create additional
bugs.


Streams
-------

Streams are output pipes where target material will come *out*, possibly
going through a re-encoding process before.

Streams can be audio only, video only or audio and video muxed together.

Re-encoding method should be configurable per stream as
a stdin/stdout pipe command that will take feed to stdin
and output re-encoded data to stdout.

All potential encoding parameters, such as, but not limited to GOP, FPS,
size, bitrate, quality, colorspace, pixel format should be configurable.
However, this responsibility can be delegated to the encoding program, and
these settings don't need to be explicitly stated in voyandz configuration.

It should be possible to specify more than one feed for the stream.
In this case it's expected that one feed will contain video
and the other audio. The feeds will be muxed together.
(How to make this work with a 'stdin' encoder?)

In case if feed produces undesirable or unnecessary overhead,
it should be possible to define a feed-less stream.

Clients connect to streams through HTTP URLs. Voyandz configuration
determines what are the paths for those URLs. URL paths can be
arbitrary, have multiple parts and must be configurable by the user.

Many independent connections can use a single stream. In such
case the data created for that stream should only be created
once and sent to each connection. This means that some connections
can receive partial data and clients need to be prepared for that.

The container of the stream must be suitable for streaming.

Clients should be able to connect at any time, potentially
receiving gibberish at the beginning.

If client is incapable of accepting gibberish, it should
be allowed for this client to specify a parameter in URL
query demanding from voyandz to provide a proper header.

Another URL query parameter should demand to start streaming
from an intra-frame. Audio-only streams can ignore that.


Screenshots
-----------

Video streams should provide a capability of grabbing
current frame as a screenshot. Screenshot must be
sent to the client directly through its connection,
and then the connection must be closed.

URL to grab a screenshot is the URL to the video stream
with extra path parameter called "pic", ie. "/video0.ts/pic".

Screenshots can be taken in PNG or JPG formats.

JPG format should allow to specify quality in percents,
with 85% being the default.

It is undesirable, but allowed, to only provide a screenshot
when the next intra-frame occurs. Client will need to wait.

Audio-only streams must end the connection with error 415.


Status Page
-----------

Voyandz should be able to provide a status page, describing its
general configuration, configured feeds and streams together
with their parameters, current statuses and traffic statistics.

Currently connected clients can be displayed, however this should
be configurable and *off* by default.

The status page should be displayed as a plain HTML page, possibly
with JavaScript AJAX requests to periodically refresh statuses that
can change over time.

The status page should also display current server time.

The status page musn't contain any JavaScript that would be vital
to its functionality. User should be able to use the page with
JavaScript disabled.

There should be clickable links to streams.

The status page should be accessible through an URL that defaults
to '/stat'.

The status page access should be toggleable, but defaulting to enabled.


Status API
----------

Optional.

Provide the information presented on the status page in form
pallatable to other programs. Use JSON format to encode it.

The status API should be accessible through an URL that defaults
to '/stat.json'.

The status API access should be toggleable, but defaulting to enabled.


Configuration
-------------

Voyandz should be configurable through a plain-text YAML file.

It should be possible to specify the path to this file through
a `-f` command-line argument. If unspecified, the default configuration
should be seeked in `/etc/voyandz.ini`.

Configuration should support a templating system, minimizing duplication.
Templates should include:

- Transcoding commands with input/output placeholders.
  Such commands can be very long. Command arguments can
  be defined in an extra configuration field per each stream.

- Sets of streams with interchangeable name piece and command arguments.
  It will be a common case to have many streams from a single capturing
  device. If there is more than one device of the same type in the system,
  it will allow to reduce the size of the config file and minimize duplication.

Template resolution should happen at program load.
Application should receive the configuration in a final format,
as if the user copied & pasted everything around.


Authorization
-------------

This is a FFA situation. Authorization is currently not in the goals.

If needed, basic HTTP authorization can be implemented.
