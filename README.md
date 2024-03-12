# witty

[![tests](https://github.com/funkelab/witty/actions/workflows/tests.yaml/badge.svg)](https://github.com/funkelab/witty/actions/workflows/tests.yaml)

Use `cython` to compile `pyx` modules at runtime.

```python
from witty import compile_module


fancy_module_pyx = """
def add(int a, int b):
    return a + b
"""

# equivalent to "import fancy_module"
fancy_module = compile_module(fancy_module_pyx)

result = fancy_module.add(3, 2)
print("fancy_module.add(3, 2) =", result)
```

## Why?

Compilation at runtime is very handy to modify C/C++/PYX sources based on type information or configurations that are not known during build time. This allows combining the optimizations of C++ template libraries with Python's flexible typing system.

This module will no longer be needed if/when https://github.com/cython/cython/pull/555 gets merged into Cython.

## How?

`witty` invokes `cython` to compile the module given as a PYX string (just like it would compile it during build time). The compiled module ends up in the Cython cache directory, with a hash build from the content of the PYX string. Repeated calls to `compile_module` will only invoke the compiler if the exact PYX string has not been compiled before (or if `force_rebuild==True`). Compilation is protected by a file lock, i.e., concurrent calls to `compile_module` are safe.
