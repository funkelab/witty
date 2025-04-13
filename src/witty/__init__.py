from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("witty")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

from .compile_module import WITTY_CACHE, compile_module

__all__ = ["compile_module", "WITTY_CACHE"]
