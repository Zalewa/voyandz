import sys

FULLNAME = "Voyandz"
NAME = "voyandz"
VERSION = "V.O.Y"
YEARSPAN = "2018, 2020 - 2021, 2023"

_metadata_fallback = sys.version_info < (3, 8, 1)
if _metadata_fallback:
    from importlib_metadata import version, PackageNotFoundError
else:
    from importlib.metadata import version, PackageNotFoundError

try:
    VERSION = version(NAME)
except PackageNotFoundError:
    pass
