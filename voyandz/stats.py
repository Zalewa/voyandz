class FeedStats:
    '''FeedStats object is temporary. It only marks
    the statistics of a given feed in a given instant.
    To get fresh statistics, discard current FeedStats
    object and create a new one, adding the feeds to
    it all over again.

    FeedStats refers both to internal feeds and client-facing
    streams as internally there's little difference between them.
    '''
    def __init__(self, name):
        self.name = name
        self.total_transfer = 0
        self.num_readers = 0
        self.is_running = False

    def add_from_feed(self, feed):
        self.total_transfer += feed.total_transfer
        self.num_readers += feed.num_readers
        self.is_running |= feed.is_alive()

    @property
    def total_transfer_human(self):
        return lenbytes_to_human(self.total_transfer)


class Totals:
    def __init__(self, stream_stats, feed_stats):
        self.client_transfer = 0
        self.clients = 0
        self.internal_transfer = 0
        for stream in stream_stats:
            self.client_transfer += stream.total_transfer
            self.clients += stream.num_readers
        for feed in feed_stats:
            self.internal_transfer += feed.total_transfer

    @property
    def client_transfer_human(self):
        return lenbytes_to_human(self.client_transfer)

    @property
    def internal_transfer_human(self):
        return lenbytes_to_human(self.internal_transfer)


def lenbytes_to_human(lenbytes):
    KB = 1024
    MB = 1024 * KB
    if lenbytes > MB:
        lenamount = lenbytes / MB
        lenunit = "MB"
    elif lenbytes > KB:
        lenamount = lenbytes / KB
        lenunit = "KB"
    else:
        lenamount = lenbytes
        lenunit = "B"
    return "{:.2f} {}".format(lenamount, lenunit)
