"""Labeller v2 server — đọc/ghi thẳng JSONL case + golden trong repo (spec §8).

stdlib-only. Mặc định bind 0.0.0.0 để share link cho người khác cùng review
(mọi thao tác lưu vẫn ghi vào repo TRÊN MÁY NÀY); cần riêng tư thì --host
127.0.0.1. Ghi qua write_file: validate TỪNG dòng bằng chính
parse_case/parse_golden rồi mới atomic-write (tmp + os.replace) — labeller không
bao giờ lưu được file sai schema. Golden dùng parse_golden trực tiếp (KHÔNG
load_golden): labeller phải sửa được draft, còn runner vẫn từ chối draft.
Tree liệt kê ĐỆ QUY mọi *.jsonl dưới root, kèm cả folder rỗng (để folder vừa
tạo hiện ra ngay); POST /api/dir tạo folder mới trong root.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import typing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from evals.quality.cases import parse_case
from evals.rag.golden import parse_golden

_EVALS = Path(__file__).resolve().parent.parent
ROOTS: dict[str, Path] = {
    "cases": _EVALS / "quality" / "data" / "cases",
    "golden": _EVALS / "rag" / "data" / "golden",
}
_STATIC = Path(__file__).resolve().parent / "static"


def resolve_path(kind: str, rel: str) -> Path:
    root = ROOTS.get(kind)
    if root is None:
        raise ValueError(f"unknown kind {kind!r}; allowed: {sorted(ROOTS)}")
    if not rel.endswith(".jsonl"):
        raise ValueError("path must end with .jsonl")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes root: {rel!r}")
    return path


def resolve_dir(kind: str, rel: str) -> Path:
    """Đường dẫn folder an toàn trong root — cho POST /api/dir."""
    root = ROOTS.get(kind)
    if root is None:
        raise ValueError(f"unknown kind {kind!r}; allowed: {sorted(ROOTS)}")
    # Chỉ strip đuôi: strip cả đầu sẽ biến path tuyệt đối "/tmp/x" thành tương đối
    # và lách qua check is_relative_to bên dưới.
    rel = (rel or "").strip().rstrip("/")
    if not rel:
        raise ValueError("dir path must be non-empty")
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"dir escapes root: {rel!r}")
    return path


def make_dir(kind: str, rel: str) -> None:
    path = resolve_dir(kind, rel)
    if path.exists():
        raise ValueError(f"dir exists: {rel!r}")
    path.mkdir(parents=True)


def _validate(kind: str, lineno: int, data: dict) -> None:
    src = f"line {lineno}"
    if kind == "cases":
        parse_case(data, source=src)
    else:
        parse_golden(data, source=src)


def list_tree() -> dict:
    out: dict = {"dirs": {}}
    for kind, root in ROOTS.items():
        rows = []
        for path in sorted(root.rglob("*.jsonl")):  # đệ quy: mọi file dưới root, sâu bao nhiêu cũng liệt kê
            rel = path.relative_to(root)
            n = n_ok = 0
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                n += 1
                try:
                    data = json.loads(line)
                    _validate(kind, lineno, data)
                    flag = data.get("reviewed") if kind == "cases" else (data.get("status") == "approved")
                    n_ok += 1 if flag else 0
                except (ValueError, TypeError):
                    pass
            rows.append({"tenant": rel.parent.as_posix(), "file": path.name,
                         "path": rel.as_posix(), "n": n, "n_ok": n_ok})
        out[kind] = rows
        # Cả folder RỖNG cũng liệt kê — folder vừa tạo phải hiện ra để chọn làm đích "+ File mới".
        out["dirs"][kind] = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir())
    return out


def read_file(kind: str, rel: str) -> dict:
    path = resolve_path(kind, rel)
    lines = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError as e:
            lines.append({"n": lineno, "data": None, "error": f"line {lineno}: not JSON — {e}"})
            continue
        try:
            _validate(kind, lineno, data)
            lines.append({"n": lineno, "data": data, "error": ""})
        except ValueError as e:
            lines.append({"n": lineno, "data": data, "error": str(e)})
    return {"lines": lines}


def write_file(kind: str, rel: str, lines: list[dict]) -> None:
    path = resolve_path(kind, rel)
    for i, data in enumerate(lines, start=1):
        _validate(kind, i, data)  # raise trước khi chạm file
    payload = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# Placeholder jinja trong description của schema (chưa render vì chưa có tenant).
# Labeller chỉ hiển thị nên thay bằng chữ trung tính cho dễ đọc.
_PLACEHOLDERS = {
    "brand.company": "bên mình",
    "brand.app_name": "app",
    "identity.honorific_self": "em",
    "identity.honorific_customer": "anh/chị",
    "identity.agent_name": "trợ lý",
    "scope.handoff_department": "CSKH",
}


def _plain(text: str) -> str:
    import re

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", lambda m: _PLACEHOLDERS.get(m.group(1), ""), text or "").strip()


def tool_catalog() -> dict:
    """Catalog `tool → args` cho dropdown của labeller.

    Nguồn sự thật là `agent/tools/schemas.py` — KHÔNG hardcode lại danh sách ở
    front-end, nếu không nó sẽ trôi khỏi schema thật và labeller sẽ chọn ra arg
    không tồn tại. Import nhẹ: schemas.py + agent_config.py chỉ dùng stdlib.
    Lỗi import → trả {} và UI tự rơi về ô nhập tay như trước.
    """
    try:
        from noble_agent.agent.agent_config import CORE_TOOLS, OPTIONAL_TOOLS
        from noble_agent.agent.tools.schemas import SCHEMAS
    except Exception:  # noqa: BLE001 — labeller phải chạy được cả khi agent không import nổi
        return {}

    order = list(CORE_TOOLS) + list(OPTIONAL_TOOLS)
    names = [n for n in order if n in SCHEMAS] + sorted(n for n in SCHEMAS if n not in order)
    out: dict = {}
    for name in names:
        fn = SCHEMAS[name].get("function") or {}
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        required = set(params.get("required") or [])
        out[name] = {
            "description": _plain(fn.get("description", "")),
            "core": name in CORE_TOOLS,
            "args": {
                arg: {
                    "type": spec.get("type", "string"),
                    "enum": spec.get("enum") or None,
                    "required": arg in required,
                    "description": _plain(spec.get("description", "")),
                }
                for arg, spec in props.items()
            },
        }
    return out


def customer_catalog() -> dict:
    """Field của `Customer` cho dropdown `expect.customer_field` của labeller.

    Nguồn sự thật là `storage/models.py::Customer` — hardcode lại ở front-end thì
    khi model đổi labeller sẽ chọn ra field không tồn tại, mà assertion trên field
    không tồn tại KHÔNG lỗi: nó chỉ đọc ra None rồi fail mãi mãi. Lỗi import → {}
    và UI rơi về ô nhập tay.
    """
    try:
        from noble_agent.storage.models import Customer
    except Exception:  # noqa: BLE001 — labeller phải chạy được cả khi agent không import nổi
        return {}

    out: dict = {}
    for name, field in Customer.model_fields.items():
        inner = [a for a in typing.get_args(field.annotation) if a is not type(None)]
        ann = inner[0] if len(inner) == 1 else field.annotation
        if typing.get_origin(ann) is typing.Literal:
            out[name] = {"type": "string", "enum": [str(v) for v in typing.get_args(ann)]}
        elif ann is bool:
            out[name] = {"type": "boolean", "enum": None}
        else:
            out[name] = {"type": "string", "enum": None}
    return out


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, (_STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/tree":
                self._json(200, list_tree())
            elif url.path == "/api/tools":
                self._json(200, tool_catalog())
            elif url.path == "/api/customer-fields":
                self._json(200, customer_catalog())
            elif url.path == "/api/file":
                q = parse_qs(url.query)
                self._json(200, read_file(q["kind"][0], q["path"][0]))
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, KeyError, FileNotFoundError) as e:
            self._json(422, {"error": str(e)})

    def do_PUT(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            if url.path != "/api/file":
                self._json(404, {"error": "not found"})
                return
            q = parse_qs(url.query)
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            lines = json.loads(body)["lines"]
            write_file(q["kind"][0], q["path"][0], lines)
            self._json(200, {"ok": True})
        except (ValueError, KeyError) as e:
            self._json(422, {"error": str(e)})

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        try:
            q = parse_qs(url.query)
            if url.path == "/api/file":
                path = resolve_path(q["kind"][0], q["path"][0])
                if path.exists():
                    raise ValueError(f"file exists: {q['path'][0]}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                self._json(200, {"ok": True})
            elif url.path == "/api/dir":
                make_dir(q["kind"][0], q["path"][0])
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            self._json(422, {"error": str(e)})

    def log_message(self, fmt: str, *args) -> None:  # im lặng access log
        pass


def _lan_ip() -> str:
    """IP LAN best-effort để in link share — không gửi gói tin nào thật."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(port: int = 8765, host: str = "0.0.0.0") -> None:
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"Labeller: http://127.0.0.1:{port}  (Ctrl-C để dừng)")
    if host == "0.0.0.0":
        print(f"Share link cho người review khác: http://{_lan_ip()}:{port}  (kết quả lưu trên máy này)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
