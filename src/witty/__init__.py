from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("witty")
except PackageNotFoundError:
    # package is not installed
    __version__ = "unknown"

from .compile_module import compile_module, get_witty_cache_dir

__all__ = ["compile_module", "get_witty_cache_dir", "__version__"]
