from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("omnia-cli")
except PackageNotFoundError:
    __version__ = "unknown"
