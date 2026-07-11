"""Package import smoke tests."""

import echoes


def test_package_imports() -> None:
    assert echoes.__version__ == "0.1.0"
