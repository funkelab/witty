import Cython
import fcntl
import hashlib
import importlib.util
import sys
from Cython.Build import cythonize
from Cython.Build.Inline import to_unicode, _get_build_extension
from Cython.Utils import get_cython_cache_dir
from distutils.core import Extension
from pathlib import Path


def load_dynamic(module_name, module_lib):
    spec = importlib.util.spec_from_file_location(module_name, module_lib)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return sys.modules[module_name]


def compile_module(
    source_pyx,
    source_files=None,
    include_dirs=None,
    library_dirs=None,
    language="c",
    extra_compile_args=None,
    extra_link_args=None,
    name=None,
    force_rebuild=False,
):
    if source_files is None:
        source_files = []
    if include_dirs is None:
        include_dirs = ["."]
    if library_dirs is None:
        library_dirs = []
    if name is None:
        name = "_wit_module"

    source_pyx = to_unicode(source_pyx)
    sources = [source_pyx]

    for source_file in source_files:
        sources.append(open(source_file, "r").read())

    source_hashes = [
        hashlib.md5(source.encode("utf-8")).hexdigest() for source in sources
    ]
    source_key = (source_hashes, sys.version_info, sys.executable, Cython.__version__)
    module_hash = hashlib.md5(str(source_key).encode("utf-8")).hexdigest()
    module_name = name + "_" + module_hash

    # already loaded?
    if module_name in sys.modules and not force_rebuild:
        return sys.modules[module_name]

    build_extension = _get_build_extension()
    module_ext = build_extension.get_ext_filename("")
    module_dir = Path(get_cython_cache_dir()) / "witty"
    module_pyx = (module_dir / module_name).with_suffix(".pyx")
    module_lib = (module_dir / module_name).with_suffix(module_ext)
    module_lock = (module_dir / module_name).with_suffix(".lock")

    print(f"Compiling {module_name} into {module_lib}...")

    module_dir.mkdir(parents=True, exist_ok=True)

    # make sure the same module is not build concurrently
    with open(module_lock, "w") as lock_file:
        fcntl.lockf(lock_file, fcntl.LOCK_EX)

        # already compiled?
        if module_lib.is_file() and not force_rebuild:
            print(f"Reusing already compiled module from {module_lib}")
            return load_dynamic(module_name, module_lib)

        # create pyx file
        with open(module_pyx, "w") as f:
            f.write(source_pyx)

        extension = Extension(
            module_name,
            sources=[str(module_pyx)],
            include_dirs=include_dirs,
            library_dirs=library_dirs,
            language=language,
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
        )

        build_extension.extensions = cythonize(
            [extension], compiler_directives={"language_level": "3"}
        )
        build_extension.build_temp = str(module_dir)
        build_extension.build_lib = str(module_dir)
        build_extension.run()

    return load_dynamic(module_name, module_lib)
