"""Shared test fixtures."""

import os
import sys

import pytest

# Add src/ to path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(autouse=True)
def _isolate_os_environ():
    """Snapshot os.environ before each test and restore it after.

    Some code paths load the developer's real .env into the process
    environment (e.g. __main__.main() → _load_dotenv()). Without isolation
    that leaks .env values into every subsequent test, breaking "code
    default" assertions that build UnifiedSettings(_env_file=None) — they
    read os.environ, so a leaked STT_SERVICE_URL etc. overrides the default.
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
