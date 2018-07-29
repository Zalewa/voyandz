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


Versioning
==========

Versioning follows semantic versioning:

https://semver.org/

Voyandz's 'piping' functionality could be used as a library, therefore
having a clear versioning scheme is important, as is sticking to the
compatibility recommendations for this versioning scheme.


Development Branches
--------------------

All development that doesn't break existing functionality should
be conducted on the `master` branch.

All development should not break existing functionality, unless
maintaining current functionality would be inconvenient.

Development that breaks existing functionality can be moved to
a 'feature' branch. A completed 'feature' branch should be merged
into `master` branch with explicit merge commit, even if fast-forward
would also do.

Bugfixing (PATCH versions) should be branched off the master
branch to a "x.y_bugfix" branch. However, if there are no
new features present on the `master` branch and the bugfix
release is expected to be done quickly then it's allowed
to make a "bugfix" release off the `master` branch.

Bugfixing commits that already exist on `master` branch can be
cherry-picked from there to the 'bugfix' branch.


Version Tagging
---------------

"Feature" releases must be tagged on the `master` branch.

"Bugfix" releases may be tagged on the 'bugfix' branch.

Tags must be named `voyandz_vx.y.z`, for example: `voyandz_v0.1.0`,
`voyandz_v1.11.4`, etc.

Tags must be annotated with 'voyandz vx.y.z' message, ie. the same
as tag name but use spaces instead of underscores.

  git tag -am 'voyandz v1.11.4' voyandz_v1.11.4

Version bumping commits must follow this commit message pattern:

  Version: voyandz vx.y.z

The `z` part in `x.y.z` musn't be ommitted, even if it's `0`.

To differ release builds from builds made from development commits,
development version bump commit should be created as soon as release
commit is tagged, and immediately follow this release commit.

Development versions should end with 'dev' suffix, ie. `x.y.zdev`.

Development version bump commit should not be tagged.


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

Feeds are uniquely identified by their names. There can't be
more than one feed with the same name.

Feeds can be defined as a command that outputs the feed to stdout.

Feeds should be configurable as:

* Continuous - in this mode the feed will be always active, draining
  resources even if there's no one using it. This mode is useful
  when the input source doesn't handle disconnections or subsequent
  reconnections very well. Feed in 'continous' mode doesn't start
  until it's needed for the first time.

* Autostart - like the 'continuous' mode, but doesn't wait on first
  use. Starts with voyandz.

* On-demand - in this mode the feed will only be activated when
  at least one connection to a stream configured to use this feed
  is opened. When all related connections are closed, the feed
  must also be closed. This is the default mode.

* Timeout - in this mode the feed will remain alive for a limited
  amount of time even if no one is using it. This mode can minimize
  delays in cases where screenshots are captured rapidly. Timeout
  mode doesn't need to be specified explicitly as a "timeout" keyword,
  but as a number of seconds (int).

When more than one stream needs a single feed, this single feed must be
used for all streams. The new stream cannot open a duplicate feed.

It should be possible for a feed to have its own feed, thus allowing
to chain commands together like piping with '|' in shell.

If feed dies while being used in the "on-demand" mode, or at any time in
the "continuous" mode, it must be resurrected immediately, unless
it's explicitly configured with 'no-resurrect' flag. There should be
no limit to resurrection attempts, however repeated failures should
have limited error logging.

Please, no stupid "buffer size" configuration parameters that are
meaningless to the user, to the program and generally create additional
bugs.


Streams
-------

Streams are output pipes where target material will come *out*, possibly
going through a re-encoding process before.

Streams are uniquely identified by their names. There can't be
more than one stream with the same name.

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
By default, the URLs should begin with '/stream/' and continue
with the stream name.

Many independent connections can use a single stream. In such
case the data created for that stream should only be created
once and sent to each connection. This means that some connections
can receive partial data and clients need to be prepared for that.

Unfortunately, it may be necessary to stream formats that only contain
the content meta-data at the beginning of the stream and this meta-data
is never repeated afterwards. In such case, it should be allowed to
define the stream as 'client: exclusive'. In this mode, each new
client connection will create a new stream with the same name and
command and only this one client will receive data produced by this
stream. When container of the stream is suitable for clients joining
in the middle, the default setting of 'client: shared' should be used.
In 'shared' mode, clients should be able to connect at any time,
potentially receiving gibberish at the beginning.


Screenshots
-----------

Video streams should provide a capability of grabbing
current feed frame as a screenshot. Screenshot must be
sent to the client directly through its connection,
and then the connection must be closed.

Screenshots are essentially "Streams" with 'type: shot'
and mimetype appropriate for the produced picture.

Server configuration determines the "mimetype" of the picture.

"command" parameter of the screenshot stream must be expected
to produce a singular picture already in the chosen "mimetype".
This command must then end gracefully with `exitcode` `0`.
If `exitcode != 0` then `stderr` of the command is returned
to the client alongside error 500.


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
should be seeked in `/etc/voyandz`.

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

Configuration dump endpoint should be enableable through a configuration
parameter. This parameter should be disabled by default. Configuration
should be dumped in JSON format at /config endpoint. Using JSON format
here is counter-intuitive, as the input configs are YAML. JSON format
was chosen regardless because it displays well in browsers, programming
languages have (built-in) libraries to parse it and it has a standardized
MIME type.

Authorization
-------------

This is a FFA situation. Authorization is currently not in the goals.

If needed, basic HTTP authorization can be implemented.
