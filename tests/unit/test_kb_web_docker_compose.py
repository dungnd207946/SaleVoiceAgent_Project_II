"""`crawl-worker` cần key DashScope — không được nằm trong profile `app` mà dev nào cũng bật."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["docker-compose.local.yml", "docker-compose.dev.yml"])
def test_crawl_worker_chi_o_profile_crawl_va_cho_redis_qdrant(name):
    services = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]
    worker = services["crawl-worker"]
    assert worker["profiles"] == ["crawl"]
    for dep in ("redis", "qdrant"):
        assert worker["depends_on"][dep]["condition"] == "service_started"
    assert not [n for n, s in services.items() if n.startswith("crawl") and "app" in (s.get("profiles") or [])]
