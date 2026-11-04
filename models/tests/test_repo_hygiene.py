import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("embed", "lipsync_musetalk")


@pytest.mark.parametrize("pkg", PACKAGES)
def test_moi_file_py_deu_nam_trong_git(pkg: str):
    """`.gitignore` nuốt nhầm source thì deploy vỡ chứ test không đỏ: image build từ
    `git reset --hard` nên thiếu file, còn máy dev vẫn có nó trên đĩa. Đã xảy ra với
    `embed/models/` (pattern `models/` khớp mọi cấp)."""
    tracked = subprocess.run(
        ["git", "ls-files", pkg], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    on_disk = {
        str(p.relative_to(ROOT))
        for p in (ROOT / pkg).rglob("*.py")
        if "__pycache__" not in p.parts
    }
    assert on_disk - set(tracked) == set()
