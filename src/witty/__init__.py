from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("witty")
except PackageNotFoundError:  # pragma: no cover
    # package is not installed
    __version__ = "unknown"

from .compile_module import (
    compile_cython,
    compile_module,
    compile_nanobind,
    get_witty_cache_dir,
)

__all__ = [
    "compile_cython",
    "compile_module",
    "compile_nanobind",
    "get_witty_cache_dir",
    "__version__",
]
