from pathlib import Path

import witty


def test_hash_injection(tmp_path: Path) -> None:
    """Test that __witty_hash__ is injected when add_hash_to_name=True (default)."""
    cython_code = """
def hello(name):
    return f"Hello, {name}!"
"""

    module = witty.compile_module(
        cython_code,
        name="test_hash_module",
        output_dir=tmp_path,
        quiet=True,
        force_rebuild=True,
        add_hash_to_name=False,
    )

    # Test that the module works
    assert module.hello("World") == "Hello, World!"

    # Test that the hash is available as an attribute
    assert hasattr(module, "__witty_hash__")
    assert isinstance(module.__witty_hash__, str)
