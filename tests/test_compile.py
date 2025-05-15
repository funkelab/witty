from pathlib import Path

import witty


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

    module_int = witty.compile_module(
        source_pxy_template.format(type="int"),
        language="c++",
        force_rebuild=True,
        output_dir=tmp_path,
    )
    result = module_int.add(3, 4)

    assert result == 7
    assert type(result) is int

    module_float = witty.compile_module(
        source_pxy_template.format(type="float"), language="c++", output_dir=tmp_path
    )
    result = module_float.add(3, 4)

    assert result == 7
    assert type(result) is float

    assert module_float.__file__
    assert Path(module_float.__file__).parent == tmp_path
