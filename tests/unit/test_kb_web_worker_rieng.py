"""Worker chính không được nhặt job kb/web; worker riêng chỉ nhặt đúng loại đó."""

import subprocess
import sys

_MAIN = """
from portal.worker.__main__ import load_handlers
load_handlers()
from portal.core import jobs
raise SystemExit(1 if "kbweb_project" in jobs._HANDLERS or not jobs._HANDLERS else 0)
"""

_WEB = """
import portal.cli.kb_web_worker  # noqa: F401
from portal.core import jobs
raise SystemExit(0 if set(jobs._HANDLERS) == {"kbweb_project", "kbweb_run", "kbweb_probe", "kbweb_purge"} else 1)
"""


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_worker_chinh_khong_dang_ky_job_web():
    r = _run(_MAIN)
    assert r.returncode == 0, r.stderr


def test_worker_rieng_chi_dang_ky_job_web():
    r = _run(_WEB)
    assert r.returncode == 0, r.stderr
