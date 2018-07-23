/* Public Domain
   Program displays time intervals for stdin reads
*/
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#define CLOCK_ CLOCK_MONOTONIC

int64_t timespec_diff_msecs(struct timespec *ta, struct timespec *tb)
{
	return (ta->tv_sec * 1000 + ta->tv_nsec / 1000000)
		- (tb->tv_sec * 1000 + tb->tv_nsec / 1000000);
}

int main(int argc, char **argv)
{
	struct timespec start_time;
	size_t bufsize = 1024;
	unsigned char *buf;

	if (argc > 1) {
		bufsize = atoi(argv[1]);
		fprintf(stderr, "bufsize = %zu\n", bufsize);
	}

	if (clock_gettime(CLOCK_, &start_time)) {
		fprintf(stderr, "cannot get clock\n");
		return 1;
	}

	buf = malloc(bufsize);
	struct timespec prev_time;
	struct timespec read_time;
	for (;;) {
		int64_t prev_diff;
		int got = read(STDIN_FILENO, (void *)buf, bufsize);
		if (got == 0)
			break;
		prev_time = read_time;
		clock_gettime(CLOCK_, &read_time);

		prev_diff = timespec_diff_msecs(&read_time, &prev_time);
		if (prev_diff > 0) {
			printf("start: %" PRId64 "ms, prev: %" PRId64 "ms\n", timespec_diff_msecs(&read_time, &start_time), prev_diff);
		}
	}
	free(buf);
	printf("total: %" PRId64 "ms\n", timespec_diff_msecs(&read_time, &start_time));
	return 0;
}
