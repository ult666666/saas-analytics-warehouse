from __future__ import annotations

import pytest

from saasgen.config import GeneratorConfig
from saasgen.generator import Dataset, generate


@pytest.fixture(scope="session")
def default_dataset() -> Dataset:
    """The dataset ``make data`` produces (generated once per test session)."""
    return generate(GeneratorConfig())


@pytest.fixture(scope="session")
def small_config() -> GeneratorConfig:
    return GeneratorConfig(seed=7, months=6, scale=0.2)
