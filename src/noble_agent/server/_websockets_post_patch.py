"""Monkey-patch `websockets.http11.Request.parse` to support POST/OPTIONS.

The `websockets` library (16.0) hardcodes GET-only at parse() level:

    if method != b"GET":
        raise ValueError(f"unsupported HTTP method; expected GET; got {d(method)}")

This breaks every POST endpoint we serve via `process_request` (handoff,
mark_followed_up, mark_contacted, /api/call-me, outbound/instructions,
outbound/call). Curl sees "Empty reply from server"; nginx upstream sees
the dropped connection and surfaces 502 Bad Gateway.

The patch:
  1. Allows GET, POST, OPTIONS, PUT, DELETE, PATCH, HEAD.
  2. Stores the method string on `request.method`.
  3. When `Content-Length` is present, reads the body via the bound
     reader's `read_exact()` and stashes bytes on `request.body`.

Imported eagerly from `noble_agent/server/http.py` so the patch is applied
before any WebSocket server starts. Idempotent: re-import is safe.
"""

from __future__ import annotations

import logging

from websockets import http11 as _ws_http11
from websockets.http11 import parse_headers, parse_line

logger = logging.getLogger("server.websockets_post_patch")

_ALLOWED_METHODS = frozenset(
    {
        b"GET",
        b"POST",
        b"OPTIONS",
        b"PUT",
        b"DELETE",
        b"PATCH",
        b"HEAD",
    }
)

# Hard cap on POST body size (matches existing handler limits).
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

_PATCH_FLAG = "_noble_post_patch_applied"


@classmethod  # type: ignore[misc]
def _patched_parse(cls, read_line):
    """Replacement for `Request.parse` — accepts non-GET + reads body."""
    request_line = yield from parse_line(read_line)
    try:
        method, raw_path, protocol = request_line.split(b" ", 2)
    except ValueError:
        raise ValueError(f"invalid HTTP request line: {request_line!r}") from None
    # parse_line returns bytearray slices — convert to bytes so they're hashable
    # for set membership and stable for `==` against b"HTTP/1.1".
    method = bytes(method)
    raw_path = bytes(raw_path)
    protocol = bytes(protocol)

    if protocol != b"HTTP/1.1":
        raise ValueError(f"unsupported protocol; expected HTTP/1.1: {protocol!r}")

    if method not in _ALLOWED_METHODS:
        raise ValueError(f"unsupported HTTP method: {method!r}")

    path = raw_path.decode("ascii", "surrogateescape")
    headers = yield from parse_headers(read_line)

    if "Transfer-Encoding" in headers:
        # Same upstream behavior — chunked encoding not supported.
        raise NotImplementedError("transfer codings aren't supported")

    request = cls(path, headers)
    request.method = method.decode("ascii")  # type: ignore[attr-defined]
    request.body = b""  # type: ignore[attr-defined]

    # Read body when Content-Length present (POST/PUT/PATCH).
    cl_raw = headers.get("Content-Length", "")
    if cl_raw:
        try:
            content_length = int(cl_raw)
        except ValueError as exc:
            raise ValueError(f"invalid Content-Length: {cl_raw!r}") from exc
        if content_length < 0:
            raise ValueError(f"negative Content-Length: {content_length}")
        if content_length > _MAX_BODY_BYTES:
            raise ValueError(
                f"Content-Length too large: {content_length} > {_MAX_BODY_BYTES}",
            )
        if content_length > 0:
            # `read_line` is a bound method on the StreamReader instance —
            # pull the reader out and use its `read_exact` to grab raw bytes.
            reader = getattr(read_line, "__self__", None)
            if reader is None or not hasattr(reader, "read_exact"):
                raise RuntimeError(
                    "websockets read_line callable lost reader binding — cannot read POST body",
                )
            body = yield from reader.read_exact(content_length)
            request.body = bytes(body)  # type: ignore[attr-defined]

    return request


def apply() -> None:
    """Apply the patch (idempotent)."""
    if getattr(_ws_http11.Request, _PATCH_FLAG, False):
        return
    _ws_http11.Request.parse = _patched_parse  # type: ignore[method-assign]
    setattr(_ws_http11.Request, _PATCH_FLAG, True)
    logger.info(
        "[ws-post-patch] websockets.http11.Request.parse patched — POST/OPTIONS/PUT/DELETE/PATCH/HEAD now accepted",
    )


# Auto-apply at import time so any downstream `import http.py` triggers it.
apply()
