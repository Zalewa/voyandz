'''The dreaded 'util' module where all garbage is thrown.'''
from enum import Enum
import time


class NameEnum(Enum):
    def _generate_next_value_(name, start, count, last_values):
        return name.lower()

    @classmethod
    def of(cls, name):
        for member in cls.__members__.values():
            if member.value == name:
                return member
        return None

    @classmethod
    def names(cls):
        return [member.value for member in cls.__members__.values()]


def monotonic():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
