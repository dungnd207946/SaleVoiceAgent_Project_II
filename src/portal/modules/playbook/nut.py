"""Bộ nút kịch bản — bản CHÉP từ odyssey-agent `src/noble_agent/playbook/playbook.json`
(sinh bằng `scripts/export_playbook.py` bên agent). Sửa nút ở agent, không sửa ở đây."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path

_FILE = Path(__file__).parent / "data" / "playbook.json"
KHUON = (
    "id",
    "ten",
    "nhom",
    "bat",
    "kenh",
    "dau_hieu",
    "lam",
    "tool",
    "cam",
    "khi_thieu",
    "cau_ket",
    "lan_2",
    "chi_lan_2",
    "nguon",
    "buoc",
)
"""Khuôn nút lưu ở `tenant_data.kich_ban.nut` (spec 2026-10-06 đợt 2 §3)."""


@cache
def doc() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        if (
            not isinstance(d.get("nodes"), list)
            or not isinstance(d.get("promptVersion"), str)
            or not d["promptVersion"]
            or not isinstance(d.get("version"), str)
            or not isinstance(d.get("templateVersion"), str)
            or not isinstance(d.get("gioiHan"), dict)
            or not all(
                isinstance(n, dict)
                and isinstance(n.get("id"), str)
                and isinstance(n.get("hash"), str)
                and n.get("lop") in ("sale", "he_thong")
                for n in d["nodes"]
            )
        ):
            raise ValueError("thiếu nodes / promptVersion / version / templateVersion / gioiHan / id-hash-lop nút")
        return d
    except (OSError, ValueError, AttributeError) as exc:
        raise RuntimeError(f"playbook.json hỏng: {exc}") from exc


def gioi_han() -> dict:
    return doc()["gioiHan"]


def template_sale() -> list[dict]:
    return [n for n in doc()["nodes"] if n["lop"] == "sale"]


def he_thong() -> list[dict]:
    return [n for n in doc()["nodes"] if n["lop"] == "he_thong"]


def chuan_hoa(j: dict) -> dict:
    """Nút JSON (kèm trường tương thích FE) → khuôn lưu."""
    d = {k: j[k] for k in KHUON}
    d["buoc"] = [{"id": b["id"], "lam": b["lam"]} for b in j["buoc"]]
    return d


def bam_nut(d: dict) -> str:
    """Hash định nghĩa nút — y hệt agent `loader.node_hash` (trừ `nguon`). Đổi ở đây là đổi cả bên kia."""
    x = {k: d[k] for k in KHUON if k != "nguon"}
    x["buoc"] = [{"id": b["id"], "lam": b["lam"]} for b in d["buoc"]]
    raw = json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def tuong_thich(d: dict) -> dict:
    """Nút sale lưu ở DB → hình dạng nút trong playbook.json (màn /kich-ban đọc) — y hệt agent `export._node`.
    Tool agent đã gỡ (không còn trong `gioiHan`) bị bỏ trước khi băm — như agent `loader._bo_tool_la`."""
    d = {**d, "tool": [t for t in d["tool"] if t in gioi_han()["tool"]]}
    return {
        **d,
        "lop": "sale",
        "buoc": [{"id": b["id"], "lam": b["lam"], "tool": []} for b in d["buoc"]],
        "khoaXoa": d["id"] in gioi_han()["khoaXoa"],
        "trang_thai": "dung" if d["bat"] else "nhap",
        "loai": "luong" if d["buoc"] else "phan_xa",
        "dieu_kien": {"lan": 2} if d["chi_lan_2"] else {},
        "tiep": {"lan_2": d["lan_2"]} if d["lan_2"] else {},
        "can_du_lieu": [],
        "hash": bam_nut(d),
    }
