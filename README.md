# witty

[![License](https://img.shields.io/pypi/l/witty.svg?color=green)](https://github.com/funkelab/witty/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/witty.svg?color=green)](https://pypi.org/project/witty)
[![Python Version](https://img.shields.io/pypi/pyversions/witty.svg?color=green)](https://python.org)
[![CI](https://github.com/funkelab/witty/actions/workflows/ci.yaml/badge.svg)](https://github.com/funkelab/witty/actions/workflows/ci.yaml)

A "well-in-time" compiler using [`cython`](https://cython.org) or
[`nanobind`](https://nanobind.readthedocs.io/en/latest/) to compile `pyx` or
C/C++ modules (respectively) at runtime.

## Installation

You can install `witty` via pip:

```sh
# for Cython support
pip install witty[cython]
# for Nanobind support
pip install witty[nanobind]
```

## Cython

> [!NOTE]
> Cython is currently included by default with witty, but this will change in the future.
> Please install with `pip install witty[cython]` if you wish to compile Cython modules.

```python
from witty import compile_cython


fancy_module_pyx = """
def add(int a, int b):
    return a + b
"""

# equivalent to "import fancy_module"
fancy_module = compile_cython(fancy_module_pyx)

result = fancy_module.add(3, 2)
print("fancy_module.add(3, 2) =", result)
```

## Nanobind

> [!NOTE]
> Cython is currently included by default with witty, but this will change in the future.
> Please install with `pip install witty[nanobind]` if you wish to compile nanobind modules.

```python
from witty import compile_nanobind


fancy_module_cpp = """
#include <nanobind/nanobind.h>

int add(int a, int b) {
 return a + b;
}

NB_MODULE(fancy_module, m) {
 m.def("add", &add);
}
"""

# equivalent to "import fancy_module"
fancy_module = compile_nanobind(fancy_module_cpp)

result = fancy_module.add(3, 2)
print("fancy_module.add(3, 2) =", result)
```

This module will no longer be needed if/when
<https://github.com/cython/cython/pull/555> gets merged into Cython.

## Why?

Compilation at runtime is very handy to modify C/C++/PYX sources based on type information or configurations that are not known during build time. This allows combining the optimizations of C++ template libraries with Python's runtime flexibility, like so:

```python
import witty


source_pxy_template = """
cdef extern from '<vector>' namespace 'std':

    cdef cppclass vector[T]:
        vector()
        void push_back(T& item)
        size_t size()

def to_vector(values):
    vec = vector[{type}]()
    for x in values:
        vec.push_back(x)
    return vec
"""

fancy_module = witty.compile_cython(
    source_pxy_template.format(type="float"), language="c++"
)

# create a C++ vector of floats from a list
vec_float = fancy_module.to_vector([0.1, 0.2, 0.3, 1e10])

print(vec_float)
```

## How?

`witty` invokes `cython` or `nanobind` to compile the module given as a
PYX/C/C++ source string (just like it would compile it during build time). The
compiled module ends up in a cache directory, with a hash build from the
content of the source string. Repeated calls to `compile_[cython,nanobind]`
will only invoke the compiler if the exact source string has not been compiled
before (or if `force_rebuild==True`). Compilation is protected by a file lock,
i.e., concurrent calls to `compile_[cython,nanobind]` are safe.

## For developers

To push a new release, make sure you've pulled main and are definitely on
the commit you want to release, then tag a commit and push to github:

```sh
git tag -a vX.Y.Z -m vX.Y.Z
git push upstream --follow-tags
```

The deploy is handled by [`workflows/ci.yaml`](.github/workflows/ci.yaml#L44)
