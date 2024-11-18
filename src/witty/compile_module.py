from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import Cython
from Cython.Build import cythonize
from Cython.Build.Inline import build_ext
from Cython.Utils import get_cython_cache_dir
from setuptools import Distribution, Extension

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import ModuleType


def compile_module(
    source_pyx: str,
    *,
    source_files: Sequence[Path | str] = (),
    include_dirs: Sequence[Path | str] = (".",),
    library_dirs: Sequence[Path | str] = (),
    language: Literal["c", "c++"] | None = None,
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    name: str = "_witty_module",
    force_rebuild: bool = False,
    quiet: bool = False,
    **extension_kwargs: Any,
) -> ModuleType:
    """Compile a Cython module given as a PYX source string.

    The module will be stored in
    [Cython's cache directory](https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html#cython-cache).
    Called with the same `source_pyx`, the cached module will be returned.

    Parameters
    ----------
    source_pyx : str
        The PYX source code.
    source_files : list of Path, optional
        Additional source files the PYX code depends on. Changes to these
        files will trigger re-compilation of the module.
    include_dirs : list of Path, optional
        List of directories to search for C/C++ header files (in Unix
        form for portability).
    library_dirs : list of Path, optional
        List of directories to search for C/C++ libraries at link time.
    language : str, optional
        Extension language (i.e., "c", "c++", "objc"). Will be detected
        from the source extensions if not provided.
    extra_compile_args : list of str, optional
        Extra platform- and compiler-specific information to use when
        compiling the source files in 'sources'. This is typically a
        list of command-line arguments for platforms and compilers where
        "command line" makes sense.
    extra_link_args : list of str, optional
        Extra platform- and compiler-specific information to use when
        linking object files to create the extension (or a new static
        Python interpreter). Has a similar interpretation as for 'extra_compile_args'.
    name : str, optional
        The base name of the module file. Defaults to "_witty_module".
    force_rebuild : bool, optional
        Force a rebuild even if a module with the same name/hash already exists.
    quiet : bool, optional
        Suppress output except for errors and warnings.
    extension_kwargs : dict, optional
        Additional keyword arguments passed to the distutils `Extension` constructor.

    Returns
    -------
    ModuleType
        The compiled module.
    """
    module_hash = _generate_hash(
        source_pyx, source_files, extra_compile_args, extra_link_args, extension_kwargs
    )
    module_name = name + "_" + module_hash

    # already loaded?
    if module_name in sys.modules and not force_rebuild:
        return sys.modules[module_name]

    build_extension = _get_build_extension()
    module_ext = build_extension.get_ext_filename("")
    module_dir = Path(get_cython_cache_dir()) / "witty"
    module_pyx = (module_dir / module_name).with_suffix(".pyx")
    module_lib = (module_dir / module_name).with_suffix(module_ext)

    if not quiet:
        print(f"Compiling {module_name} into {module_lib}...")

    module_dir.mkdir(parents=True, exist_ok=True)

    # make sure the same module is not build concurrently
    with _module_locked(module_pyx):
        # already compiled?
        if module_lib.is_file() and not force_rebuild:
            if not quiet:
                print(f"Reusing already compiled module from {module_lib}")
            return _load_dynamic(module_name, module_lib)

        # create pyx file
        module_pyx.write_text(source_pyx)

        extension = Extension(
            module_name,
            sources=[str(module_pyx)],
            include_dirs=[str(x) for x in include_dirs],
            library_dirs=[str(x) for x in library_dirs],
            language=language,
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
            **(extension_kwargs or {}),
        )

        build_extension.extensions = cythonize(
            [extension],
            compiler_directives={"language_level": "3"},
            quiet=quiet,
        )
        build_extension.build_temp = str(module_dir)
        build_extension.build_lib = str(module_dir)
        build_extension.run()

    return _load_dynamic(module_name, module_lib)


def _load_dynamic(module_name: str, module_path: Path) -> ModuleType:
    """Dynamically load a module from a path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if not spec or not spec.loader:
        raise ImportError(f"Failed to load module {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return sys.modules[module_name]


def _generate_hash(
    source_pyx: str, source_files: Sequence[Path | str] = (), *args: dict | list | None
) -> str:
    """Generate a hash key for a `source_pyx` along with other source file paths."""
    sources = [source_pyx] + [Path(source).read_text() for source in source_files]
    src_hashes = [hashlib.md5(source.encode("utf-8")).hexdigest() for source in sources]
    arg_hash = _hash_args(args)
    source_key = (
        src_hashes,
        arg_hash,
        sys.version_info,
        sys.executable,
        Cython.__version__,
    )
    return hashlib.md5(str(source_key).encode("utf-8")).hexdigest()


def _hash_args(containers: tuple[dict | list | None, ...]) -> str:
    """Hash a bunch of mutable arg container objects in a reproducible way.

    This is for stuff like extra_compile_args, extra_link_args, and extension_kwargs.
    """
    hash_obj = hashlib.md5()
    for container in containers:
        # sort dict keys for reproducibility
        serialized = json.dumps(container, sort_keys=True)
        # Update the hash object with the serialized container
        hash_obj.update(serialized.encode())
    return hash_obj.hexdigest()


@contextmanager
def _module_locked(module_path: Path) -> Iterator[None]:
    """Temporarily lock a module file to prevent concurrent compilation."""
    module_lock_file = module_path.with_suffix(".lock")
    with open(module_lock_file, "w") as lock_fd:
        _lock_file(lock_fd)
        try:
            yield
        finally:
            _unlock_file(lock_fd)


def _get_build_extension() -> build_ext:
    # same as `cythonize` Build.Inline._get_build_extension
    # vendored to avoid using a private API
    dist = Distribution()
    # Ensure the build respects distutils configuration by parsing
    # the configuration files
    config_files = dist.find_config_files()
    dist.parse_config_files(config_files)
    build_extension = build_ext(dist)
    build_extension.finalize_options()
    return build_extension


if os.name == "nt":
    import msvcrt

    def _lock_file(file: Any) -> None:
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, os.path.getsize(file.name))  # type: ignore

    def _unlock_file(file: Any) -> None:
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, os.path.getsize(file.name))  # type: ignore

else:
    import fcntl

    def _lock_file(file: Any) -> None:
        fcntl.lockf(file, fcntl.LOCK_EX)

    def _unlock_file(file: Any) -> None:
        fcntl.lockf(file, fcntl.LOCK_UN)
