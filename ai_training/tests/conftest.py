"""Load explicitly isolated TEST_ONLY software fixtures."""

import importlib.util
import sys
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("training_toy_fixture", Path(__file__).parent / "fixtures/toy.py")
toy_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toy_module
spec.loader.exec_module(toy_module)


@pytest.fixture
def toy():
    return toy_module


@pytest.fixture
def case(toy):
    return toy.make_case()
