import subprocess
import sys
from pathlib import Path

import witty

CONCURRENT = """
import sys
from pathlib import Path

import witty

module = witty.compile_cython(
    "def add(int x, int y): return x + y", output_dir=Path(sys.argv[1])
)
assert module.add(3, 4) == 7
"""


def test_cache_dir() -> None:
    # smoke test to check if the cache dir is created
    assert isinstance(witty.get_witty_cache_dir(), Path)


def test_compile(tmp_path: Path) -> None:
    source_pxy_template = """
cdef extern from '<vector>' namespace 'std':

    cdef cppclass vector[T]:
        vector()
        void push_back(T& item)
        size_t size()

def add({type} x, {type} y):
    return x + y

def to_vector({type} x):
    v = vector[{type}]()
    v.push_back(x)
    return v
"""

    module_int = witty.compile_cython(
        source_pxy_template.format(type="int"),
        language="c++",
        force_rebuild=True,
        output_dir=tmp_path,
    )
    result = module_int.add(3, 4)

    assert result == 7
    assert type(result) is int

    module_float = witty.compile_cython(
        source_pxy_template.format(type="float"), language="c++", output_dir=tmp_path
    )
    result = module_float.add(3, 4)

    assert result == 7
    assert type(result) is float

    assert module_float.__file__
    assert Path(module_float.__file__).parent == tmp_path


def test_nanobind(tmp_path: Path) -> None:
    fancy_module_cpp = """
#include <nanobind/nanobind.h>

int add(int a, int b) {
	return a + b;
}

NB_MODULE(fancy_module, m) {
	m.def("add", &add);
}
"""

    fancy_module = witty.compile_nanobind(fancy_module_cpp)
    result = fancy_module.add(3, 2)

    assert result == 5
    assert type(result) is int


def test_concurrent_compilation(tmp_path: Path) -> None:
    args = [sys.executable, "-c", CONCURRENT, str(tmp_path)]
    processes = [
        subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(4)
    ]
    outputs = [process.communicate() for process in processes]

    for process, (_, stderr) in zip(processes, outputs):
        assert process.returncode == 0, stderr
    # one of them compiles the module, the others wait for it
    built = [stdout for stdout, _ in outputs if "Build module" in stdout]
    reused = [stdout for stdout, _ in outputs if "Reusing" in stdout]
    assert (len(built), len(reused)) == (1, 3)
