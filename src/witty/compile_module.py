from __future__ import annotations

import distutils
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from distutils.ccompiler import new_compiler
from distutils.command.build_ext import build_ext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

import Cython
import nanobind
from Cython.Build.Dependencies import cythonize
from setuptools import Distribution, Extension
from typing_extensions import deprecated

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import ModuleType


def get_witty_cache_dir() -> Path:
    """Return the base directory containing Witty's caches.

    - os.environ["WITTY_CACHE_DIR"] if set
    - Windows: `%LOCALAPPDATA%/witty/cache`
    - macOS: `~/Library/Caches/witty`
    - Linux: os.environ['XDG_CACHE_HOME']/witty or `~/.cache/witty`

    This function does not ensure that the directory exists.
    """
    if "WITTY_CACHE_DIR" in os.environ:
        cache_dir = Path(os.environ["WITTY_CACHE_DIR"])
    elif sys.platform == "win32":
        if local_app := os.getenv("LOCALAPPDATA"):
            cache_dir = Path(local_app) / "witty" / "cache"
        else:
            cache_dir = Path.home() / ".witty" / "cache"
    elif sys.platform == "darwin":
        cache_dir = Path.home() / "Library" / "Caches" / "witty"
    else:
        if xdg_cache := os.getenv("XDG_CACHE_HOME"):
            cache_dir = Path(xdg_cache) / "witty"
        else:
            cache_dir = Path.home() / ".cache" / "witty"
    return cache_dir.expanduser().absolute()


def compile_nanobind(
    source: str,
    *,
    source_files: Sequence[Path | str] = (),
    include_dirs: Sequence[Path | str] = (".",),
    library_dirs: Sequence[Path | str] = (),
    language: Literal["c", "c++"] | None = "c++",
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    force_rebuild: bool | None = None,
    quiet: bool = False,
    output_dir: Path | None = None,
    **extension_kwargs: Any,
) -> ModuleType:
    """Compile a nanobind C/C++ module given as a string.

    The module will be stored in witty's cache directory. Called with the same
    `source`, the cached module will be returned.

    Parameters
    ----------
    source: str
        The C/C++ source code.
    source_files : list of Path, optional
        Additional source files the C/C++ code depends on. Changes to these
        files will trigger re-compilation of the module.
    include_dirs : list of Path, optional
        List of directories to search for C/C++ header files (in Unix
        form for portability).
    library_dirs : list of Path, optional
        List of directories to search for C/C++ libraries at link time.
    language : str, optional
        Extension language (i.e., "c", "c++", "objc"). Defaults to "c++".
    extra_compile_args : list of str, optional
        Extra platform- and compiler-specific information to use when
        compiling the source files in 'sources'. This is typically a
        list of command-line arguments for platforms and compilers where
        "command line" makes sense.
    extra_link_args : list of str, optional
        Extra platform- and compiler-specific information to use when
        linking object files to create the extension (or a new static
        Python interpreter). Has a similar interpretation as for 'extra_compile_args'.
    force_rebuild : bool, optional
        Force a rebuild even if a module with the same name/hash already exists. By
        default False.  May be set via environment variable `WITTY_FORCE_REBUILD=1`.
    quiet : bool, optional
        Suppress output except for errors and warnings.
    output_dir : Path, optional
        Directory to store the compiled module. If not provided, the module will be
        stored in the output of `witty.get_witty_cache_dir()`:
        - os.environ["WITTY_CACHE_DIR"] if set
        - Windows: `%LOCALAPPDATA%/witty/cache`
        - macOS: `~/Library/Caches/witty`
        - Linux: os.environ['XDG_CACHE_HOME']/witty or `~/.cache/witty`
    extension_kwargs : dict, optional
        Additional keyword arguments passed to the distutils `Extension` constructor.

    Returns
    -------
    ModuleType
        The compiled module.
    """
    # operator delete(void*, std::align_val_t) first became part of the
    # system C++ runtime in macOS 10.13
    os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "10.13")

    def build_extra_objects(build_dir: Path) -> list[str]:
        nanobind_base_dir = Path(nanobind.include_dir()) / ".."
        source_dir = Path(nanobind.source_dir())
        target = build_dir / str(source_dir).lstrip("/") / "nb_combined.o"

        if target.exists():
            return [str(target)]

        compiler = new_compiler()

        compiler.add_include_dir(nanobind.include_dir())
        compiler.add_include_dir(
            str(nanobind_base_dir / "ext" / "robin_map" / "include")
        )
        compiler.add_include_dir(distutils.sysconfig.get_python_inc())

        if sys.platform == "win32":
            cxx_flags = [
                "/std:c++17",
                "/DNDEBUG",
                "/DNB_COMPACT_ASSERTIONS",
                "/O2",
                "/EHsc",
            ]
        else:
            cxx_flags = [
                "-std=c++17",
                "-fvisibility=hidden",
                "-DNDEBUG",
                "-DNB_COMPACT_ASSERTIONS",
                "-fPIC",
                "-fno-strict-aliasing",
                "-ffunction-sections",
                "-fdata-sections",
                "-O3",
            ]
        nanobind_objects = compiler.compile(
            sources=[source_dir / "nb_combined.cpp"],
            output_dir=str(build_dir),
            extra_preargs=cxx_flags,
        )

        return nanobind_objects  # type: ignore[no-any-return]

    if include_dirs is None:
        include_dirs = []
    else:
        include_dirs = list(include_dirs)
    include_dirs.append(nanobind.include_dir())

    if extra_compile_args is None:
        extra_compile_args = []
    # Use MSVC style flag on Windows, GCC/Clang flags otherwise
    if sys.platform == "win32":
        extra_compile_args += [
            "/std:c++17",
            "/DNDEBUG",
            "/DNB_COMPACT_ASSERTIONS",
            "/O2",
            "/EHsc",
        ]
    else:
        extra_compile_args += [
            "-std=c++17",
            "-fvisibility=hidden",
            "-DNDEBUG",
            "-DNB_COMPACT_ASSERTIONS",
            "-fPIC",
            "-O3",
        ]

    return _compile_module(
        source,
        source_type="nanobind",
        source_files=source_files,
        include_dirs=include_dirs,
        library_dirs=library_dirs,
        language=language,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
        build_extra_objects=build_extra_objects,
        force_rebuild=force_rebuild,
        quiet=quiet,
        output_dir=output_dir,
        **extension_kwargs,
    )


def compile_cython(
    source_pyx: str,
    *,
    source_files: Sequence[Path | str] = (),
    include_dirs: Sequence[Path | str] = (".",),
    library_dirs: Sequence[Path | str] = (),
    language: Literal["c", "c++"] | None = None,
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    name: str = "_witty_module",
    force_rebuild: bool | None = None,
    quiet: bool = False,
    output_dir: Path | None = None,
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
        Force a rebuild even if a module with the same name/hash already exists. By
        default False.  May be set via environment variable `WITTY_FORCE_REBUILD=1`.
    quiet : bool, optional
        Suppress output except for errors and warnings.
    output_dir : Path, optional
        Directory to store the compiled module. If not provided, the module will be
        stored in the output of `witty.get_witty_cache_dir()`:
        - os.environ["WITTY_CACHE_DIR"] if set
        - Windows: `%LOCALAPPDATA%/witty/cache`
        - macOS: `~/Library/Caches/witty`
        - Linux: os.environ['XDG_CACHE_HOME']/witty or `~/.cache/witty`
    extension_kwargs : dict, optional
        Additional keyword arguments passed to the distutils `Extension` constructor.

    Returns
    -------
    ModuleType
        The compiled module.
    """

    return _compile_module(
        source_pyx,
        source_type="pyx",
        source_files=source_files,
        include_dirs=include_dirs,
        library_dirs=library_dirs,
        language=language,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
        name=name,
        force_rebuild=force_rebuild,
        quiet=quiet,
        output_dir=output_dir,
        **extension_kwargs,
    )


@deprecated(
    "Use compile_cython for PYX and compile_nanobind for nanobind C/C++. "
    "compile_module will be removed in future releases."
)
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
    force_rebuild: bool | None = None,
    quiet: bool = False,
    output_dir: Path | None = None,
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
        Force a rebuild even if a module with the same name/hash already exists. By
        default False.  May be set via environment variable `WITTY_FORCE_REBUILD=1`.
    quiet : bool, optional
        Suppress output except for errors and warnings.
    output_dir : Path, optional
        Directory to store the compiled module. If not provided, the module will be
        stored in the output of `witty.get_witty_cache_dir()`:
        - os.environ["WITTY_CACHE_DIR"] if set
        - Windows: `%LOCALAPPDATA%/witty/cache`
        - macOS: `~/Library/Caches/witty`
        - Linux: os.environ['XDG_CACHE_HOME']/witty or `~/.cache/witty`
    extension_kwargs : dict, optional
        Additional keyword arguments passed to the distutils `Extension` constructor.

    Returns
    -------
    ModuleType
        The compiled module.
    """

    return _compile_module(
        source_pyx,
        source_type="pyx",
        source_files=source_files,
        include_dirs=include_dirs,
        library_dirs=library_dirs,
        language=language,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
        name=name,
        force_rebuild=force_rebuild,
        quiet=quiet,
        output_dir=output_dir,
        **extension_kwargs,
    )


def _compile_module(
    source: str,
    source_type: Literal["pyx", "nanobind"],
    *,
    source_files: Sequence[Path | str] = (),
    include_dirs: Sequence[Path | str] = (".",),
    library_dirs: Sequence[Path | str] = (),
    language: Literal["c", "c++"] | None = None,
    extra_compile_args: list[str] | None = None,
    extra_link_args: list[str] | None = None,
    build_extra_objects: Callable[[Path], list[str]] | None = None,
    name: str | None = None,
    force_rebuild: bool | None = None,
    quiet: bool = False,
    output_dir: Path | None = None,
    **extension_kwargs: Any,
) -> ModuleType:
    if output_dir is None:
        output_dir = get_witty_cache_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

    if force_rebuild is None:
        force_rebuild = os.getenv("WITTY_FORCE_REBUILD", "0").lower() in ("1", "true")

    module_hash = _generate_hash(
        source, source_files, extra_compile_args, extra_link_args, extension_kwargs
    )

    if source_type == "nanobind":
        assert name is None, (
            "For non-PYX builds, the module name should not be given but be part "
            "of the source file."
        )
        names = re.findall(r"NB_MODULE\s*\(\s*(.*),", source)
        if len(names) != 1:
            raise ValueError(
                "For nanobind modules, the source must contain a single NB_MODULE "
                f"definition with the module name.  Found {len(names)}"
            )
        name = names[0]
    module_name = (name or "") + "_" + module_hash

    # already loaded?
    if module_name in sys.modules and not force_rebuild:
        return sys.modules[module_name]

    build_extension = _get_build_extension()
    module_ext = build_extension.get_ext_filename("")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        source_extension = (
            ".pyx" if source_type == "pyx" else (".cpp" if language == "c++" else ".c")
        )
        module_source = Path(temp_dir, module_name).with_suffix(source_extension)
        module_lib = (output_dir / module_name).with_suffix(module_ext)
        if not quiet:
            print(f"Compiling {module_name} into {module_lib}...")

        # make sure the same module is not build concurrently
        with _module_locked(module_source):
            # already compiled?
            if module_lib.is_file() and not force_rebuild:
                if not quiet:
                    print(f"Reusing already compiled module from {module_lib}")
                return _load_dynamic(module_name, module_lib)

            if source_type == "nanobind":
                # adjust module name in nanobind definition to include hash
                source = re.sub(
                    r"NB_MODULE\s*\(\s*(.*),\s*(.*)\s*\)",
                    "NB_MODULE(\\1_" + module_hash + ", \\2)",
                    source,
                )

            # create source file
            module_source.write_text(source)

            if build_extra_objects:
                if not quiet:
                    print("Building extra objects...")
                extra_objects = build_extra_objects(get_witty_cache_dir())
                if not quiet:
                    print(f"Built {extra_objects}...")
            else:
                extra_objects = []

            if extra_link_args is None:
                extra_link_args = []

            extension = Extension(
                module_name,
                sources=[str(module_source)],
                include_dirs=[str(x) for x in include_dirs],
                library_dirs=[str(x) for x in library_dirs],
                language=language,
                extra_compile_args=extra_compile_args,
                extra_link_args=extra_objects + extra_link_args,
                **(extension_kwargs or {}),
            )

            if source_type == "pyx":
                extensions = cythonize(  # type: ignore [no-untyped-call]
                    [extension],
                    compiler_directives={"language_level": "3"},
                    quiet=quiet,
                )
            else:
                extensions = [extension]

            build_extension.extensions = extensions
            build_extension.build_temp = temp_dir
            build_extension.build_lib = str(output_dir)
            build_extension.run()

            if not quiet:
                print(f"Build module {module_name} in {module_lib}")

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
    source: str, source_files: Sequence[Path | str] = (), *args: dict | list | None
) -> str:
    """Generate a hash key for a `source` along with other source file paths."""
    sources = [source] + [Path(source).read_text() for source in source_files]
    src_hashes = [hashlib.md5(source.encode("utf-8")).hexdigest() for source in sources]
    arg_hash = _hash_args(args)
    source_key = (
        src_hashes,
        arg_hash,
        sys.version_info,
        sys.executable,
        Cython.__version__,  # type: ignore [attr-defined]
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
