"""API QUẢN LÝ NHÂN VẬT (HTTP :8021) + luồng dựng nền — client là portal BACKEND, không phải trình duyệt.

WebSocket :8020 chỉ nói được GET (bắt tay) nên upload video / lệnh dựng đi cổng HTTP riêng.
Mọi route (trừ /health) đòi `Authorization: Bearer $ODYSSEY_MODELS_TOKEN` (rỗng = tắt, dev).

  GET    /health
  GET    /avatars/<id>                  trạng thái: chua_dung | cho | dang_dung | san_sang | loi
                                        {"trang_thai","buoc","tien_do","loi":{"ma","chi_tiet"},"w","h","bo_cuc"}
  PUT    /avatars/<id>/video/<loai>     body = bytes video (loai: chinh | tay) — ≤ LIPSYNC_VIDEO_MAX_MB
  POST   /avatars/<id>/dung             xếp hàng dựng (202). Dựng lại = gọi lại (xoá cache cũ, giữ nguồn)
                                        thân tuỳ chọn {"cat_dau_s": giây} — sàn cắt đầu (nhân vật từ ảnh)
  GET    /avatars/<id>/poster.png       ảnh chờ RGBA (sau khi san_sang)
  GET    /avatars/<id>/khung_cho.jpg    khung chờ GỐC có nền (sau lần dựng không có clip tay) —
                                        portal sinh clip đưa tay từ đây rồi dựng lại có G
  POST   /avatars/<id>/xem-truoc        {"text","nen"?,"voice"?} → video/mp4 nhân vật nói câu đó (đồng bộ)
  DELETE /avatars/<id>                  xoá nhân vật (409 khi đang dựng)

Dựng chạy TUẦN TỰ trong một luồng nền (GPU ~1–3 phút/nhân vật). Nó tranh GPU với phiên
đang gọi: phần MuseTalk xin `gpu_lock` theo từng lô, phần dò mặt / tách nền thì không —
phiên tự chuyển sang render thưa (12,5 fps) khi bị tranh, như lúc TTS chạy song song.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("lipsync-quanly")

LOAI_VIDEO = ("chinh", "tay")
VIDEO_MAX = int(os.environ.get("LIPSYNC_VIDEO_MAX_MB", "200")) * 1024 * 1024
TEXT_MAX = 400
DUOI = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}
_ROUTE = re.compile(r"^/avatars/(?P<id>[^/]+)(?P<con>/.*)?$")


class QuanLy:
    def __init__(self, eng, kho, avatar_cls, args, token):
        # avatar_cls truyền vào (không `from lipsync_server import Avatar`): server chạy như
        # __main__, import lại tên module là nạp BẢN THỨ HAI của nó — thiếu các global
        # musetalk mà Engine.__init__ gán ⇒ NameError lúc ghép mặt.
        self.eng, self.kho, self.avatar_cls, self.args, self.token = eng, kho, avatar_cls, args, token
        self.hang: queue.Queue[str] = queue.Queue()
        self.dang_dung: str | None = None
        self.cho: set[str] = set()
        self.khoa = threading.Lock()
        self.khoa_xem = threading.Lock()          # xem trước tuần tự — mỗi lượt vài giây GPU

    # ── trạng thái ──
    def trang_thai(self, avatar_id):
        import dung_avatar as da
        from avatar import doc_info, thu_muc

        if avatar_id == self.args.avatar_id:
            a = self.kho.lay(avatar_id)
            return {"trang_thai": "san_sang", "mac_dinh": True, "w": a.w, "h": a.h, "bo_cuc": a.bo_cuc.dict()}
        d = thu_muc(avatar_id)
        if not os.path.isdir(d):
            return None
        info = doc_info(avatar_id)
        with self.khoa:
            if avatar_id == self.dang_dung or avatar_id in self.cho:
                info = None                         # đang dựng lại ⇒ info cũ đã/ sắp bị xoá
        tt = da.doc_trang_thai(d) or {}
        if info is not None:
            return {"trang_thai": "san_sang", "tien_do": 1.0, "w": info["w"], "h": info["h"],
                    "bo_cuc": info["bo_cuc"], "so_frame": info["so_frame"]}
        if tt.get("trang_thai") in ("cho", "dang_dung", "loi"):
            return {k: tt.get(k) for k in ("trang_thai", "buoc", "tien_do", "loi")}
        return {"trang_thai": "chua_dung", "co_video": sorted(os.path.splitext(t)[0]
                                                           for t in os.listdir(os.path.join(d, "nguon")))
                if os.path.isdir(os.path.join(d, "nguon")) else []}

    # ── dựng ──
    def xep_dung(self, avatar_id):
        import dung_avatar as da
        from avatar import thu_muc

        with self.khoa:
            if avatar_id == self.dang_dung or avatar_id in self.cho:
                return False
            self.cho.add(avatar_id)
        da.ghi_trang_thai(thu_muc(avatar_id), trang_thai="cho", buoc="cho", tien_do=0.0)
        self.hang.put(avatar_id)
        return True

    def vong_dung(self):
        while True:
            avatar_id = self.hang.get()
            with self.khoa:
                self.cho.discard(avatar_id)
                self.dang_dung = avatar_id
            try:
                self._dung(avatar_id)
            finally:
                with self.khoa:
                    self.dang_dung = None

    def _dung(self, avatar_id):
        import avatar as av
        import dung_avatar as da
        from avatar import PHIEN_BAN_KHACH, thu_muc
        from bo_cuc import LoiDung
        from tu_the import BoCuc

        d = thu_muc(avatar_id)
        if not os.path.isdir(d):                    # bị xoá trong lúc chờ
            return

        def bao(buoc, tien_do):
            da.ghi_trang_thai(d, trang_thai="dang_dung", buoc=buoc, tien_do=round(tien_do, 3))

        self.kho.bo(avatar_id)
        log.info("🏗️  dựng nhân vật %s …", avatar_id)
        try:
            bao("bat_dau", 0.0)
            # TOÀN BỘ việc dựng nằm trong giu_cudnn(): import `musetalk.utils.preprocessing`
            # (DWPose + S3FD, lần đầu ở `diem_than`) khởi tạo FaceAlignment và BẬT
            # `cudnn.benchmark` toàn cục. Để kẹt ở True thì MỌI phiên gọi sau đó dò lại thuật
            # toán cuDNN ở lô đầu (4,1s thay vì 0,27s) ⇒ cả câu chào trễ hạn, nhân vật không
            # nhép môi lượt đầu (đo 2026-10-07: phiên đầu sau khi dựng có `tre` 148 frame).
            with av.giu_cudnn():
                a_ = self.args
                meta = da.dung(d, self.eng.vae, self.eng.fp, a_.extra_margin, a_.parsing_mode, bao)
                bao("mieng_khep", 0.7)
                a = self.avatar_cls(self.eng, d, BoCuc.tu_dict(meta["bo_cuc"]))  # render miệng khép + poster
            with open(os.path.join(d, "info.json"), "w") as f:            # CUỐI CÙNG — dấu «dùng được»
                json.dump({"phien_ban": PHIEN_BAN_KHACH, **meta}, f)
            da.ghi_trang_thai(d, trang_thai="san_sang", buoc="xong", tien_do=1.0)
            del a
            log.info("✅ nhân vật %s dựng xong (%d frame, %s)", avatar_id, meta["so_frame"], meta["bo_cuc"])
        except LoiDung as e:
            log.warning("❌ nhân vật %s: %s", avatar_id, e)
            da.ghi_trang_thai(d, trang_thai="loi", buoc="loi", tien_do=0.0,
                              loi={"ma": e.ma, "chi_tiet": e.chi_tiet})
        except Exception as e:  # noqa: BLE001 — một video hỏng không được giết luồng dựng
            log.error("❌ nhân vật %s lỗi hệ thống:\n%s", avatar_id, traceback.format_exc())
            if os.path.isdir(d):
                da.ghi_trang_thai(d, trang_thai="loi", buoc="loi", tien_do=0.0,
                                  loi={"ma": "LOI_HE_THONG", "chi_tiet": f"{type(e).__name__}: {e}"[:500]})

    def xep_lai_khi_khoi_dong(self):
        """Container bị restart giữa lúc dựng ⇒ nhân vật kẹt `cho/dang_dung` — dựng lại."""
        import dung_avatar as da

        if not os.path.isdir("avatars"):
            return
        for ten in sorted(os.listdir("avatars")):
            tt = da.doc_trang_thai(os.path.join("avatars", ten)) or {}
            if tt.get("trang_thai") in ("cho", "dang_dung"):
                log.info("↻ nhân vật %s dở dang từ lần chạy trước — xếp dựng lại", ten)
                self.xep_dung(ten)

    # ── xem trước ──
    def xem_truoc(self, avatar_id, text, nen, voice):
        import xem_truoc as xt

        a = self.kho.lay(avatar_id)
        # Token TTS riêng được (dev: lipsync tắt auth nhưng TTS bật); mặc định = token chung.
        tts_token = os.environ.get("LIPSYNC_TTS_TOKEN", "").strip() or self.token
        pcm, sr = xt.tts(self.args.tts_url, tts_token, text, voice)
        with self.khoa_xem:
            return xt.render(self.eng, a, pcm, sr, nen)

    def xoa(self, avatar_id):
        from avatar import thu_muc

        with self.khoa:
            if avatar_id == self.dang_dung:
                return False
            self.cho.discard(avatar_id)
        self.kho.bo(avatar_id)
        shutil.rmtree(thu_muc(avatar_id), ignore_errors=True)
        return True


def _handler(ql: QuanLy):
    from avatar import MA_HOP_LE, thu_muc

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):  # noqa: D401 — log qua logging, không stderr
            log.debug("%s " + fmt, self.address_string(), *a)

        def _tra(self, status, body=b"", loai="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", loai)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _loi(self, status, ma, chi_tiet=""):
            self._tra(status, {"error": {"code": ma, "message": chi_tiet}})

        def _xac_thuc(self):
            if not ql.token:
                return True
            if self.headers.get("Authorization", "").removeprefix("Bearer ").strip() == ql.token:
                return True
            self._loi(HTTPStatus.UNAUTHORIZED, "unauthorized")
            return False

        def _route(self):
            m = _ROUTE.match(self.path.split("?", 1)[0])
            if not m:
                return None, None
            avatar_id = m["id"]
            if not MA_HOP_LE.match(avatar_id):
                self._loi(HTTPStatus.BAD_REQUEST, "bad_id", "id: [a-z0-9_-], 3–64 ký tự")
                return False, None
            return avatar_id, m["con"] or ""

        def _doc_body(self, toi_da):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                self._loi(HTTPStatus.LENGTH_REQUIRED, "empty_body")
                return None
            if n > toi_da:
                self._loi(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too_large", f"tối đa {toi_da >> 20} MB")
                return None
            return n

        def do_GET(self):  # noqa: N802
            if self.path.split("?", 1)[0] == "/health":
                return self._tra(HTTPStatus.OK, "ok", "text/plain")
            if not self._xac_thuc():
                return None
            avatar_id, con = self._route()
            if avatar_id is False:
                return None
            if avatar_id is None:
                return self._loi(HTTPStatus.NOT_FOUND, "not_found")
            if con == "":
                tt = ql.trang_thai(avatar_id)
                if not tt:
                    return self._loi(HTTPStatus.NOT_FOUND, "avatar_not_found")
                return self._tra(HTTPStatus.OK, tt)
            if con == "/poster.png":
                p = os.path.join(thu_muc(avatar_id), "poster.png")
                if not os.path.exists(p):
                    return self._loi(HTTPStatus.NOT_FOUND, "not_ready")
                with open(p, "rb") as f:
                    return self._tra(HTTPStatus.OK, f.read(), "image/png")
            if con == "/khung_cho.jpg":
                from bo_cuc import KHUNG_CHO_JPG

                p = os.path.join(thu_muc(avatar_id), KHUNG_CHO_JPG)
                if not os.path.exists(p):
                    return self._loi(HTTPStatus.NOT_FOUND, "not_ready")
                with open(p, "rb") as f:
                    return self._tra(HTTPStatus.OK, f.read(), "image/jpeg")
            return self._loi(HTTPStatus.NOT_FOUND, "not_found")

        def do_PUT(self):  # noqa: N802
            if not self._xac_thuc():
                return None
            avatar_id, con = self._route()
            if avatar_id is False:
                return None
            m = re.fullmatch(r"/video/(chinh|tay)", con or "")
            if avatar_id is None or not m or avatar_id == ql.args.avatar_id:
                return self._loi(HTTPStatus.NOT_FOUND, "not_found")
            n = self._doc_body(VIDEO_MAX)
            if n is None:
                return None
            nguon = os.path.join(thu_muc(avatar_id), "nguon")
            os.makedirs(nguon, exist_ok=True)
            loai = m[1]
            if loai == "chinh":                             # video nói đổi ⇒ khung chờ cũ vô nghĩa
                from bo_cuc import xoa_khung_cho

                xoa_khung_cho(thu_muc(avatar_id))
            for t in os.listdir(nguon):                     # thay video cùng loại (khác đuôi)
                if os.path.splitext(t)[0] == loai:
                    os.remove(os.path.join(nguon, t))
            duoi = DUOI.get(self.headers.get("Content-Type", "").split(";")[0].strip(), ".mp4")
            dich = os.path.join(nguon, loai + duoi)
            con_lai = n
            with open(dich + ".tmp", "wb") as f:
                while con_lai > 0:
                    khoi = self.rfile.read(min(1 << 20, con_lai))
                    if not khoi:
                        break
                    f.write(khoi)
                    con_lai -= len(khoi)
            if con_lai:
                os.remove(dich + ".tmp")
                return self._loi(HTTPStatus.BAD_REQUEST, "truncated")
            os.replace(dich + ".tmp", dich)
            log.info("📥 nhân vật %s: nhận video %s (%.1f MB)", avatar_id, loai, n / 1e6)
            return self._tra(HTTPStatus.OK, {"ok": True, "loai": loai, "bytes": n})

        def do_POST(self):  # noqa: N802
            if not self._xac_thuc():
                return None
            avatar_id, con = self._route()
            if avatar_id is False:
                return None
            if avatar_id is None:
                return self._loi(HTTPStatus.NOT_FOUND, "not_found")
            if con == "/dung":
                if avatar_id == ql.args.avatar_id:
                    return self._loi(HTTPStatus.CONFLICT, "default_avatar")
                if not os.path.isdir(os.path.join(thu_muc(avatar_id), "nguon")):
                    return self._loi(HTTPStatus.CONFLICT, "no_video", "chưa upload video chính")
                # Thân TUỲ CHỌN `{"cat_dau_s": 1.2}` (xem `dung_avatar.CAU_DUNG_JSON`). Không thân
                # ⇒ giữ cấu hình đã lưu (bên gọi cũ chưa gửi trường này).
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= 4096:
                    import dung_avatar as da
                    try:
                        yc = json.loads(self.rfile.read(n))
                        if "cat_dau_s" in yc:
                            da.ghi_cau_dung(thu_muc(avatar_id), float(yc["cat_dau_s"]))
                    except (ValueError, TypeError, AttributeError):
                        return self._loi(HTTPStatus.BAD_REQUEST, "bad_json")
                ql.xep_dung(avatar_id)
                return self._tra(HTTPStatus.ACCEPTED, ql.trang_thai(avatar_id))
            if con == "/xem-truoc":
                n = self._doc_body(64 * 1024)
                if n is None:
                    return None
                try:
                    yc = json.loads(self.rfile.read(n))
                except ValueError:
                    return self._loi(HTTPStatus.BAD_REQUEST, "bad_json")
                text = str(yc.get("text") or "").strip()[:TEXT_MAX]
                if not text:
                    return self._loi(HTTPStatus.BAD_REQUEST, "empty_text")
                try:
                    mp4 = ql.xem_truoc(avatar_id, text, yc.get("nen"), yc.get("voice"))
                except KeyError:
                    return self._loi(HTTPStatus.NOT_FOUND, "avatar_not_ready")
                except Exception as e:  # noqa: BLE001
                    log.exception("xem trước %s lỗi", avatar_id)
                    loi = f"{type(e).__name__}: {e}"[:300]
                    return self._loi(HTTPStatus.BAD_GATEWAY, "preview_failed", loi)
                return self._tra(HTTPStatus.OK, mp4, "video/mp4")
            return self._loi(HTTPStatus.NOT_FOUND, "not_found")

        def do_DELETE(self):  # noqa: N802
            if not self._xac_thuc():
                return None
            avatar_id, con = self._route()
            if avatar_id is False:
                return None
            if avatar_id is None or con:
                return self._loi(HTTPStatus.NOT_FOUND, "not_found")
            if avatar_id == ql.args.avatar_id:
                return self._loi(HTTPStatus.CONFLICT, "default_avatar")
            if not ql.xoa(avatar_id):
                return self._loi(HTTPStatus.CONFLICT, "building", "đang dựng — xoá sau khi xong")
            return self._tra(HTTPStatus.OK, {"ok": True})

    return H


def chay_nen(eng, kho, avatar_cls, args, token):
    """Mở API quản lý + luồng dựng (daemon) — gọi từ main() của lipsync_server."""
    ql = QuanLy(eng, kho, avatar_cls, args, token)
    threading.Thread(target=ql.vong_dung, name="dung-avatar", daemon=True).start()
    ql.xep_lai_khi_khoi_dong()
    srv = ThreadingHTTPServer(("0.0.0.0", args.http_port), _handler(ql))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="api-quan-ly", daemon=True).start()
    log.info("🛠️  API quản lý nhân vật trên 0.0.0.0:%d (auth=%s)", args.http_port, "on" if token else "off")
    return ql
