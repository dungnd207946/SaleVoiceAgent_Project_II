"""Merge hotword nền (file) với hotword phiên (frame config) trong stt_server."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

STT_SERVER = Path(__file__).resolve().parents[1] / "stt" / "stt_server.py"


@pytest.fixture
def stt(monkeypatch):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", types.ModuleType("sherpa_onnx"))
    spec = importlib.util.spec_from_file_location("stt_server_merge_undertest", STT_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phien_khong_ghi_score_thi_giu_score_cua_nen(stt):
    """Agent gửi "KPI" trần (bảng không có cột score) không được hạ "KPI :3.0" của nền về mặc định."""
    merged = stt._merge_hotwords({"KPI": 3.0}, "kpi/Alluvia")
    assert merged == {"KPI": 3.0, "ALLUVIA": None}


def test_phien_ghi_score_thi_de_score_cua_nen(stt):
    merged = stt._merge_hotwords({"NOBLEX": 2.0}, "noblex :1.2")
    assert merged == {"NOBLEX": 1.2}


def test_khong_sua_danh_sach_nen(stt):
    base = {"KPI": 3.0}
    stt._merge_hotwords(base, "kpi :1.0/moi")
    assert base == {"KPI": 3.0}
