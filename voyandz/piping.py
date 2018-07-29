# coding: utf-8
from .logging import logopen
from .stats import FeedStats

import atexit
import errno
import os
import threading
import time
import select
import shlex
import subprocess


_PIPE_CHUNK_SIZE = select.PIPE_BUF
_CLIENT_WPIPE_TIMEOUT = 10.0


class Error(Exception):
    pass


class FeedReuseError(Error):
    def __init__(self, details, feed_id, *args):
        super(FeedReuseError, self).__init__(
            "tried to incorrectly reuse feed{}, feed_id: {}".format(
                " {}".format(details) if details else "",
                feed_id),
            feed_id,
            *args)


class NoSuchFeedError(Error):
    pass


class NoSuchStreamError(Error):
    pass


def stream(cfg, stream_name):
    try:
        stream_cfg = cfg['streams'][stream_name]
    except KeyError:
        raise NoSuchStreamError(stream_name)
    try:
        mimetype = stream_cfg["mimetype"]
    except KeyError:
        raise Error("stream '{}' is of unknown mimetype".format(mimetype))
    feeds_cfg = cfg.get('feeds', {})
    stream_type = stream_cfg.get("type")
    try:
        if stream_type == "stream":
            output = _stream(stream_name, stream_cfg, feeds_cfg, cfg.get('logdir'))
        elif stream_type == "shot":
            output = _shot(stream_cfg, feeds_cfg)
        else:
            raise Error("stream '{}' is of unknown type".format(stream_name))
    except Exception as e:
        if isinstance(e, Error):
            raise
        else:
            raise Error(str(e)) from e
    return stream_type, mimetype, output


def stream_stats(name):
    return _stats(name, _mk_stream_id(name))


def feed_stats(name):
    return _stats(name, _mk_feed_id(name))


def _stats(name, feed_id):
    stats = FeedStats(name)
    feeds = _global_ctx.find_all_feeds(feed_id)
    for feed in feeds:
        stats.add_from_feed(feed)
    return stats


def _stream(stream_name, stream_cfg, feeds_cfg, logdir):
    cmd = stream_cfg['command']
    stream_id = _mk_stream_id(stream_name)
    exclusive = (stream_cfg.get("client") == "exclusive")

    def generate():
        feed = _feed_for_stream(stream_cfg.get('feed'), feeds_cfg, logdir=logdir)
        with _global_ctx.feed(stream_id, cmd, feed,
                              logdir=logdir, exclusive=exclusive) as stream:
            stream_rpipe = stream.new_reader()
            try:
                while stream.is_alive():
                    chunk = os.read(stream_rpipe, _PIPE_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
            finally:
                os.close(stream_rpipe)
    return generate()


def _shot(stream_cfg, feeds_cfg):
    cmd = shlex.split(stream_cfg['command'])
    with _feed_for_stream(stream_cfg.get('feed'), feeds_cfg, logdir=stream_cfg.get('logdir')) as feed:
        stdin = None
        if feed:
            stdin = feed.new_reader()
        try:
            p = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, close_fds=True)
        finally:
            if stdin is not None:
                os.close(stdin)
        stdout, stderr = p.communicate()
        ec = p.wait()
        if ec == 0:
            return stdout
        else:
            raise Error(stderr.decode('utf-8', 'replace'))


def _feed_for_stream(feed_name, feeds_cfg, logdir):
    if not feed_name:
        return _null_feed
    try:
        feed_cfg = feeds_cfg[feed_name]
    except KeyError:
        raise NoSuchFeedError("feed '{}' cannot be found".format(feed_name))
    parent_feed = _feed_for_stream(feed_cfg.get('feed'), feeds_cfg, logdir)
    return _feed(feed_name, feed_cfg, logdir=logdir, input_feed=parent_feed)


def _feed(feed_name, feed_cfg, logdir, input_feed=None):
    input_feed = input_feed or _null_feed
    command = feed_cfg['command']
    mode = feed_cfg.get('mode', 'on-demand')
    if isinstance(mode, str):
        mode = mode.lower()
    return _global_ctx.feed(_mk_feed_id(feed_name),
                            command, input_feed=input_feed,
                            mode=mode, logdir=logdir)


@atexit.register
def _teardown(*args):
    _global_ctx.close()


class _GlobalContext:
    def __init__(self):
        self._plumbing = _Plumbing()
        self._plumbing.start()
        self._shared_feeds = {}
        self._feeds = []
        self._feed_lock = threading.Lock()

    def feed(self, feed_id, cmd, input_feed=None, mode="on-demand",
             logdir=None, exclusive=False):
        with self._feed_lock:
            feed = self._find_free_feed(feed_id, exclusive)
            if feed is None:
                # Spawn a new one.
                feed = _Feed(feed_id, cmd, input_feed, mode=mode,
                             logdir=logdir)
                if exclusive:
                    self._feeds.append(feed)
                else:
                    self._shared_feeds[feed_id] = feed
            if input_feed is not feed.input_feed:
                raise FeedReuseError("with a different input feed", feed_id)
            if mode != feed.mode:
                raise FeedReuseError("with a different mode", feed_id)
            return feed

    def close(self):
        with self._feed_lock:
            for feed in self._shared_feeds.values():
                feed._close()
            self._shared_feeds = {}
            for feed in self._feeds:
                feed._close()
            self._feeds = []
        self._plumbing.stop()

    def add_pipeline(self, pipeline):
        self._plumbing.add_pipeline(pipeline)

    def has_pipeline(self, pipeline):
        return self._plumbing.has_pipeline(pipeline)

    def close_pipeline(self, pipeline):
        if self.has_pipeline(pipeline):
            # If plumbing already has the pipeline, we cannot close it
            # in the current thread but need to inform plumbing to do it.
            self._plumbing.close_pipeline(pipeline)
        else:
            pipeline.close()

    def find_all_feeds(self, feed_id):
        feeds = []
        if feed_id in self._shared_feeds:
            feeds.append(self._shared_feeds[feed_id])
        feeds += [feed for feed in self._feeds if feed.feed_id == feed_id]
        return feeds

    def _find_free_feed(self, feed_id, exclusive):
        if exclusive:
            # Try to reuse an unused exclusive feed
            for unused_feed in self._feeds:
                if unused_feed.feed_id == feed_id and not unused_feed.is_alive():
                    return unused_feed
        else:
            return self._shared_feeds.get(feed_id)
        return None


class _Feed:
    def __init__(self, feed_id, cmd, input_feed, mode="on-demand",
                 logdir=None):
        if not self._is_mode_valid(mode):
            raise Error("invalid mode '{}'".format(mode))
        self.input_feed = input_feed
        self.mode = mode
        self._feed_id = feed_id
        self._logdir = logdir
        self._acquired = 0
        self._lock = threading.Lock()
        self._process = None
        self._pipeline = None
        self._cmd = cmd
        self._closed = True
        self._total_transfer_so_far = 0

    @property
    def feed_id(self):
        return self._feed_id

    @property
    def num_readers(self):
        pipeline = self._pipeline
        return self._pipeline.num_readers if pipeline else 0

    @property
    def total_transfer(self):
        pipeline = self._pipeline
        total_transfer = self._total_transfer_so_far
        if pipeline:
            total_transfer += pipeline.total_transfer
        return total_transfer

    def new_reader(self):
        return self._pipeline.new_reader()

    def is_alive(self):
        proc = self._process
        pipeline = self._pipeline
        return ((proc is not None and proc.poll() is None) and
                (pipeline is not None and pipeline.is_alive()))

    def open(self):
        with self._lock:
            if self._acquired == 0 and self._closed:
                self._open()
            self._acquired += 1

    def close(self):
        with self._lock:
            self._acquired -= 1
            if self._acquired <= 0:
                if self.mode == "on-demand":
                    self._close()
                elif isinstance(self.mode, (int, float)):
                    t = threading.Thread(target=self._delayed_close, args=(self.mode,))
                    t.daemon = True
                    t.start()

    def _delayed_close(self, delay):
        time.sleep(delay)
        with self._lock:
            if self._acquired <= 0:
                self._close()

    def _open(self):
        self.input_feed.open()
        cmd = shlex.split(self._cmd)
        logfile = subprocess.DEVNULL
        feed_rpipe = subprocess.DEVNULL
        rpipe = None
        wpipe = None
        buffer_ = None
        try:
            rpipe, wpipe = os.pipe()
            buffer_ = _MultiClientBuffer()
            # Ownership of pipes is transferred to the Pipeline.
            self._pipeline = _Pipeline(rpipe, buffer_, lifecheck=self.is_alive)
            if self.input_feed:
                feed_rpipe = self.input_feed.new_reader()
            if self._logdir:
                logfile = logopen(self._logdir, "{}.log".format(self._feed_id))
            self._process = subprocess.Popen(
                cmd, stdin=feed_rpipe, stdout=wpipe,
                stderr=logfile, close_fds=True)
            self._closed = False
            _global_ctx.add_pipeline(self._pipeline)
        except BaseException:
            if self._pipeline is None:
                # We didn't get the chance to create the pipeline yet,
                # so its elements need to be closed here.
                if rpipe:
                    os.close(rpipe)
                if buffer_:
                    buffer_.close()
            elif not _global_ctx.has_pipeline(self._pipeline):
                self._pipeline.close()
                self._pipeline = None
            self._close()
            raise
        finally:
            if feed_rpipe is not subprocess.DEVNULL:
                os.close(feed_rpipe)
            if logfile is not subprocess.DEVNULL:
                logfile.close()
            if wpipe is not None:
                os.close(wpipe)

    def _close(self):
        self._closed = True
        # Close pipeline
        pipeline = self._pipeline
        if pipeline:
            self._total_transfer_so_far = pipeline.total_transfer
            _global_ctx.close_pipeline(pipeline)
        self._pipeline = None
        # Stop process.
        p = self._process
        self._process = None
        if p:
            p.terminate()
            try:
                p.wait(1.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        self.input_feed.close()

    def _is_mode_valid(self, mode):
        return mode in ["continuous", "on-demand"] or isinstance(mode, (float, int))

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


class _Plumbing:
    def __init__(self):
        self._pipelines = {}
        self._lock = threading.Condition()
        self._thread = None
        self._running = False

    def add_pipeline(self, pipeline):
        with self._lock:
            self._pipelines[pipeline.feed_pipe] = pipeline
            self._notify_by_wpipe()
            self._lock.notify_all()

    def has_pipeline(self, pipeline):
        with self._lock:
            return pipeline.feed_pipe in self._pipelines

    def close_pipeline(self, pipeline):
        with self._lock:
            pipeline.mark_for_close()
            self._notify_by_wpipe()
            self._lock.notify_all()

    def start(self):
        self._pipeline_notify_rpipe, self._pipeline_notify_wpipe = None, None
        try:
            self._running = True
            self._pipeline_notify_rpipe, self._pipeline_notify_wpipe = os.pipe()
            t = threading.Thread(target=self._run)
            t.daemon = True
            t.start()
        except BaseException:
            self._running = False
            rpipe, wpipe = self._pipeline_notify_rpipe, self._pipeline_notify_wpipe
            if rpipe:
                os.close(rpipe)
            if wpipe:
                os.close(wpipe)
            self._pipeline_notify_rpipe, self._pipeline_notify_wpipe = None, None
            raise
        self._thread = t

    def stop(self):
        with self._lock:
            self._running = False
            self._notify_by_wpipe()
            self._lock.notify_all()
            os.close(self._pipeline_notify_wpipe)
        t = self._thread
        if t:
            t.join()
        os.close(self._pipeline_notify_rpipe)
        self._thread = None

    def _run(self):
        while self._running:
            with self._lock:
                while self._running and not self._pipelines:
                    self._lock.wait()
                if not self._running:
                    break
            self._run_step()

    def _run_step(self):
        with self._lock:
            pipelines = dict(self._pipelines)
        if not pipelines:
            return
        dead_feed_pipes = set()
        # Prepare pending selections.
        feed_pipes = [feed_pipe for feed_pipe in pipelines]
        feed_pipes.append(self._pipeline_notify_rpipe)
        all_pending_pipelines = []
        all_pending_wpipes = []
        for pipeline in pipelines.values():
            if not pipeline.lifecheck() or pipeline.to_close:
                dead_feed_pipes.add(pipeline.feed_pipe)
                continue
            pending_wpipes = pipeline.pending_wpipes()
            if pending_wpipes:
                all_pending_pipelines.append(pipeline)
                all_pending_wpipes += pending_wpipes
        ready_feed_pipes, ready_pending_wpipes, _ = select.select(feed_pipes, all_pending_wpipes, [], _CLIENT_WPIPE_TIMEOUT)
        # Deal with new data.
        for feed_pipe in ready_feed_pipes:
            chunk = os.read(feed_pipe, _PIPE_CHUNK_SIZE)
            if not chunk:
                dead_feed_pipes.add(feed_pipe)
                continue
            if feed_pipe != self._pipeline_notify_rpipe:
                pipelines[feed_pipe].write(chunk)
        # Deal with data that was already waiting to be piped out.
        if ready_pending_wpipes:
            for pipeline in all_pending_pipelines:
                pending_wpipes_for_this_buf = [wpipe for wpipe in ready_pending_wpipes
                                               if wpipe in pipeline.pending_wpipes()]
                if pending_wpipes_for_this_buf:
                    pipeline.flush(pending_wpipes_for_this_buf, _PIPE_CHUNK_SIZE)
        # Close timed out or slow pipelines; also close pipelines that are
        # meant to be closed.
        # Slow clients must get discarded, otherwise there's risk of
        # out-of-memory errors as buffers grow indefinitely to ensure
        # that clients don't lose any data.
        for pipeline in pipelines.values():
            pipeline.close_timedout()
        # Reap graveyard.
        if dead_feed_pipes:
            dead_pipelines = []
            with self._lock:
                for feed_pipe in dead_feed_pipes:
                    dead_pipelines.append(self._pipelines[feed_pipe])
                    del self._pipelines[feed_pipe]
            for pipeline in dead_pipelines:
                pipeline.close()

    def _notify_by_wpipe(self):
        os.write(self._pipeline_notify_wpipe, b'x')


class _Pipeline:
    def __init__(self, feed_pipe, outbuffer, lifecheck):
        self.feed_pipe = feed_pipe
        self.outbuffer = outbuffer
        self.lifecheck = lifecheck or (lambda: False)
        self.dead = False
        self.to_close = False
        self.total_transfer = 0

    def close(self):
        self.dead = True
        self.outbuffer.close()

    def close_timedout(self):
        self.outbuffer.close_timedout()

    def flush(self, wpipes, amount):
        self.outbuffer.flush(wpipes, _PIPE_CHUNK_SIZE)

    def is_alive(self):
        return not self.dead  # duh

    def mark_for_close(self):
        self.to_close = True

    def new_reader(self):
        return self.outbuffer.new_reader()

    @property
    def num_readers(self):
        return self.outbuffer.num_readers

    def pending_wpipes(self):
        return self.outbuffer.pending_wpipes()

    def write(self, chunk):
        self.total_transfer += len(chunk)
        self.outbuffer.write(chunk)


class _MultiClientBuffer:
    def __init__(self):
        self._pipes = {}
        self._pipes_lock = threading.Lock()
        self._closed = False

    @property
    def num_readers(self):
        return len(self._pipes)

    def new_reader(self):
        with self._pipes_lock:
            if self._closed:
                raise IOError(errno.EIO, "already closed")
            rpipe, wpipe = os.pipe()
            self._pipes[wpipe] = _PipeBuffer(wpipe)
            return rpipe

    def write(self, chunk):
        if self._closed:
            return
        for pipe in self._copy_pipes().values():
            pipe.write(chunk)

    def flush(self, wpipes, amount):
        pipes = self._copy_pipes()
        bad_wpipes = []
        for wpipe in wpipes:
            try:
                pipe = pipes[wpipe]
                pipe.flush(amount)
            except OSError:
                bad_wpipes.append(wpipe)
        if bad_wpipes:
            with self._pipes_lock:
                self._close_wpipes(bad_wpipes)

    def pending_wpipes(self):
        return [wpipe for (wpipe, pipe) in self._copy_pipes().items() if pipe.pending]

    def close_timedout(self):
        with self._pipes_lock:
            timedout_wpipes = [wpipe for wpipe in self._pipes
                               if self._pipes[wpipe].timedout]
            self._close_wpipes(timedout_wpipes)

    def close(self):
        with self._pipes_lock:
            self._closed = True
            for wpipe in self._pipes:
                os.close(wpipe)
            self._pipes = {}

    def _copy_pipes(self):
        with self._pipes_lock:
            return dict(self._pipes)

    def _close_wpipes(self, wpipes):
        for wpipe in wpipes:
            try:
                os.close(wpipe)
            except OSError:
                pass
            if wpipe in self._pipes:
                del self._pipes[wpipe]


class _PipeBuffer:
    def __init__(self, pipe):
        self._pipe = pipe
        self._buffer = b''
        self._last_ready = _monotonic()

    @property
    def timedout(self):
        return (_monotonic() - self._last_ready) > _CLIENT_WPIPE_TIMEOUT

    @property
    def pending(self):
        return self._buffer

    def write(self, chunk):
        self._buffer += chunk

    def flush(self, amount):
        payload = self._buffer
        try:
            if payload:
                written_len = os.write(self._pipe, payload[:amount])
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EWOULDBLOCK]:
                raise
        else:
            self._last_ready = _monotonic()
            self._buffer = payload[written_len:]

    def fileno(self):
        return self._pipe


class _NullFeed:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def open(self):
        pass

    def close(self):
        pass

    def __bool__(self):
        return False


def _mk_feed_id(name):
    return "feed_{}".format(name)


def _mk_stream_id(name):
    return "stream_{}".format(name)


def _monotonic():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


_null_feed = _NullFeed()
_global_ctx = _GlobalContext()
