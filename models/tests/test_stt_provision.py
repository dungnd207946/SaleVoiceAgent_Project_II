"""stt kéo Zipformer theo revision HF mỗi lần boot — spec 2026-09-24.

`sherpa_onnx` không nằm trong extras `dev` (chỉ có trong image stt), nên module
được nạp với một stub. `huggingface_hub` cũng stub: ghi lại lời gọi, giả sha của
branch và tạo file như thật.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

STT_SERVER = Path(__file__).resolve().parents[1] / "stt" / "stt_server.py"
FILES = [
    "encoder-epoch.onnx",
    "decoder-epoch.onnx",
    "joiner-epoch.onnx",
    "encoder-epoch.int8.onnx",
    "decoder-epoch.int8.onnx",
    "joiner-epoch.int8.onnx",
    "tokens.txt",
]
SHA_A = "a" * 40
SHA_B = "b" * 40


class FakeHub:
    def __init__(self):
        self.sha = SHA_A
        self.info_error: Exception | None = None
        self.broken_download = False
        self.info_calls: list[dict] = []
        self.download_calls: list[dict] = []

    def repo_info(self, repo_id, revision=None, token=None, **kw):
        self.info_calls.append({"repo_id": repo_id, "revision": revision, "token": token})
        if self.info_error:
            raise self.info_error
        return types.SimpleNamespace(sha=self.sha)

    def snapshot_download(self, repo_id, local_dir, revision=None, token=None, **kw):
        self.download_calls.append({"repo_id": repo_id, "local_dir": local_dir, "revision": revision})
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        names = ["tokens.txt"] if self.broken_download else FILES
        for name in names:
            (Path(local_dir) / name).write_text(revision or "")
        return local_dir


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    mod = types.ModuleType("huggingface_hub")

    class HfApi:
        def __init__(self, token=None):
            pass

        def repo_info(self, *a, **kw):
            return fake.repo_info(*a, **kw)

    mod.HfApi = HfApi
    mod.snapshot_download = fake.snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    return fake


@pytest.fixture
def stt(monkeypatch, hub):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", types.ModuleType("sherpa_onnx"))
    spec = importlib.util.spec_from_file_location("stt_server_undertest", STT_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HF_REPO", "NobleX-AI/santa-stt")
    monkeypatch.setattr(module, "HF_REVISION", "prod")
    return module


def _seed(model_dir: Path, sha: str | None, content: str = "old") -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        (model_dir / name).write_text(content)
    if sha is not None:
        (model_dir / ".revision").write_text(sha)


def test_dung_sha_thi_khong_tai(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)

    stt._ensure_model_present(str(d), quantize=False)

    assert hub.info_calls[0]["revision"] == "prod"
    assert hub.download_calls == []
    assert (d / "encoder-epoch.onnx").read_text() == "old"


def test_khac_sha_thi_tai_va_doi_cho(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)
    hub.sha = SHA_B

    stt._ensure_model_present(str(d), quantize=False)

    assert len(hub.download_calls) == 1
    assert hub.download_calls[0]["revision"] == SHA_B, "phải ghim đúng sha vừa so, không phải tên branch"
    assert hub.download_calls[0]["local_dir"] == str(d) + ".new"
    assert (d / ".revision").read_text() == SHA_B
    assert (d / "encoder-epoch.onnx").read_text() == SHA_B
    assert (tmp_path / "odyssey-stt.prev" / "encoder-epoch.onnx").read_text() == "old"
    assert not (tmp_path / "odyssey-stt.new").exists()
    assert stt._discover_stem(str(d), False) == "epoch"
    assert stt._discover_stem(str(d), True) == "epoch.int8"


def test_thieu_revision_nhung_co_file_thi_tai(stt, hub, tmp_path):
    """Server đang chạy hôm nay: có model, chưa có .revision → lần boot đầu tự tải một lần."""
    d = tmp_path / "odyssey-stt"
    _seed(d, None)

    stt._ensure_model_present(str(d), quantize=False)

    assert len(hub.download_calls) == 1
    assert (d / ".revision").read_text() == SHA_A


def test_thu_muc_trong_thi_tai(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"

    stt._ensure_model_present(str(d), quantize=False)

    assert len(hub.download_calls) == 1
    assert (d / ".revision").read_text() == SHA_A
    assert not (tmp_path / "odyssey-stt.prev").exists()


def test_hf_chet_co_local_thi_chay_tiep(stt, hub, tmp_path, caplog):
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)
    hub.info_error = ConnectionError("no route")

    stt._ensure_model_present(str(d), quantize=False)

    assert hub.download_calls == []
    assert "no route" in caplog.text


def test_hf_chet_khong_local_thi_nem(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"
    hub.info_error = ConnectionError("no route")

    with pytest.raises(ConnectionError):
        stt._ensure_model_present(str(d), quantize=False)


def test_ban_tai_thieu_file_thi_giu_ban_cu(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)
    hub.sha = SHA_B
    hub.broken_download = True

    with pytest.raises(FileNotFoundError):
        stt._ensure_model_present(str(d), quantize=False)

    assert (d / "encoder-epoch.onnx").read_text() == "old"
    assert (d / ".revision").read_text() == SHA_A
    assert not (tmp_path / "odyssey-stt.new").exists()
    assert not (tmp_path / "odyssey-stt.prev").exists()


def test_repo_rong_thi_khong_dung_hf(stt, hub, tmp_path, monkeypatch):
    d = tmp_path / "odyssey-stt"
    _seed(d, None)
    monkeypatch.setattr(stt, "HF_REPO", "")

    stt._ensure_model_present(str(d), quantize=False)

    assert hub.info_calls == []
    assert hub.download_calls == []


def test_repo_rong_thu_muc_trong_thi_nem(stt, hub, tmp_path, monkeypatch):
    monkeypatch.setattr(stt, "HF_REPO", "")

    with pytest.raises(FileNotFoundError):
        stt._ensure_model_present(str(tmp_path / "odyssey-stt"), quantize=False)


def test_cap_nhat_lan_hai_thay_prev_cu(stt, hub, tmp_path):
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)
    hub.sha = SHA_B
    stt._ensure_model_present(str(d), quantize=False)
    hub.sha = "c" * 40
    stt._ensure_model_present(str(d), quantize=False)

    assert (d / ".revision").read_text() == "c" * 40
    assert (tmp_path / "odyssey-stt.prev" / ".revision").read_text() == SHA_B


def test_thu_muc_nhap_nhang_khong_co_ban_moi_thi_nem(stt, hub, tmp_path):
    """Hai stem fp32 + đúng sha → ValueError của _discover_stem phải nổi lên, không tải đè."""
    d = tmp_path / "odyssey-stt"
    _seed(d, SHA_A)
    (d / "encoder-other.onnx").touch()

    with pytest.raises(ValueError):
        stt._ensure_model_present(str(d), quantize=False)

    assert hub.download_calls == []
