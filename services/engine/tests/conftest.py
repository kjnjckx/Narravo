from collections.abc import Iterator
from pathlib import Path

import pytest

from narravo_engine.domain import Domain
from narravo_engine.storage import Storage


@pytest.fixture
def domain(tmp_path: Path) -> Iterator[Domain]:
    storage = Storage(tmp_path)
    yield Domain(storage)
    storage.close()
