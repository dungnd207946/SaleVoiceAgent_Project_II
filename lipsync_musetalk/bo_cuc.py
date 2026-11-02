"""Tự đo bố cục tư thế (`BoCuc`) cho nhân vật khách tự tạo — logic THUẦN, test được không GPU.

Clip người dẫn gốc được đo TAY (vùng chờ 1–15, dải nói 22–100…). Video khách upload
hay sinh bằng AI thì không ai đo tay được, nên đo từ tín hiệu từng frame:

  • `chuyen_dong[k]` — độ đổi hình frame k so với k−1 trong vùng người (0 = đứng yên).
  • `mieng[k]`       — độ mở miệng (khoảng môi trong / chiều cao mặt), None nếu không đo được.
  • `tay_g[k]`       — độ cao cổ tay so với lúc đầu đoạn G (dương = đã nhấc), None nếu không có G.
  • `lech_vong`      — frame cuối F lệch frame đầu bao nhiêu (cùng thang `chuyen_dong`).

Chuẩn video (README §Chuẩn video nhân vật) yêu cầu MỞ ĐẦU bằng 1–2s đứng yên, miệng khép —
nên vùng chờ là cửa sổ «yên + khép miệng» nhất trong 3 giây đầu.
"""

from __future__ import annotations

import json
import os

import numpy as np
from tu_the import FPS, BoCuc

F_TOI_THIEU = 3 * FPS          # đoạn nói phải ≥ 3s (vùng chờ + dải nói + lề)
G_TOI_THIEU = 2 * FPS          # đoạn đưa tay ngắn hơn 2s ⇒ bỏ (không đủ một cử chỉ)
TIM_CHO_TRONG = 4 * FPS        # vùng chờ tìm trong 4s đầu (video AI chỉnh dáng mất ~1,5s đầu)
NGUONG_VONG = 1.5              # lech_vong ≤ NGUONG_VONG × trung vị chuyển động ⇒ coi như liền vòng
TIM_SAU_VAO_DANG = int(1.5 * FPS)  # tìm vùng chờ trong 1,5s sau điểm vào dáng
NGUONG_ON_DINH = 0.015          # cổ tay lệch ≤ 1,5% chiều cao khung so với dáng cuối ⇒ đã vào dáng
TI_LE_KHEP = 0.9               # ≥ 90% frame của vùng chờ phải «khép»
MIENG_KHEP_TUYET_DOI = 0.035     # độ mở ≤ mức này luôn là khép (đo Wan: khép ~0,015–0,03, nói 0,05–0,1)
NGUONG_KHEP = 0.6              # miệng «khép» = độ mở ≤ 60% trung vị độ mở cả clip (clip chủ yếu là nói)
NGUONG_NHAC_TAY = 0.04         # cổ tay lên ≥ 4% chiều cao khung ⇒ đã nhấc tay
# Khung chờ của lần dựng KHÔNG có đoạn đưa tay — portal lấy ảnh này sinh clip đưa tay (khung đầu =
# khung cuối = nó), rồi dựng lại có G: F phải bắt đầu ĐÚNG ở frame này thì mối nối F↔G mới liền.
# Nằm ở gốc thư mục nhân vật, GIỮ qua lần dựng lại; video nói đổi thì xoá (chỉ số vô nghĩa).
KHUNG_CHO_JPG = "khung_cho.jpg"
KHUNG_CHO_JSON = "khung_cho.json"


class LoiDung(Exception):
    """Lỗi dựng nhân vật có MÃ — portal đổi mã thành câu hướng dẫn cho khách."""

    def __init__(self, ma: str, chi_tiet: str = ""):
        super().__init__(f"{ma}: {chi_tiet}")
        self.ma, self.chi_tiet = ma, chi_tiet


def _chuan(x):
    """Đưa tín hiệu về thang ~1 = mức điển hình (chia trung vị), chống chia 0."""
    x = np.asarray(x, np.float64)
    m = float(np.median(x)) if len(x) else 0.0
    return x / (m if m > 1e-9 else (float(x.max()) or 1.0))


def _tb_cua_so(x, dai):
    cs = np.concatenate([[0.0], np.cumsum(x)])
    return (cs[dai:] - cs[:-dai]) / dai               # trung bình mỗi cửa sổ dài `dai`


def tim_vung_cho(chuyen_dong, mieng=None, dai=None, tu=0, bo_qua_mieng=False):
    """(a, b) — vùng chờ trong `TIM_CHO_TRONG` frame đầu: MIỆNG KHÉP trước, rồi YÊN nhất.

    Miệng là điều kiện CỨNG chứ không cộng điểm ngang hàng chuyển động: video AI hay nói
    liên tục mà lại rất ít cử động thân (đo 2026-10-07, Wan: đoạn ít chuyển động nhất rơi
    đúng lúc đang nói, miệng mở ~0,06–0,09 so với ~0,02 lúc khép) — cộng điểm thì đoạn đang
    nói thắng và người dẫn mấp máy môi khi đứng chờ. Cửa sổ «khép» = ≥ `TI_LE_KHEP` frame có độ mở
    ≤ `NGUONG_KHEP` × trung vị độ mở cả clip; không cửa sổ nào đạt thì rơi về cộng điểm.
    """
    n = len(chuyen_dong)
    dai = int(dai) if dai else int(np.clip(n // 8, 8, 16))
    tu = int(max(0, min(tu, n - 30 - dai)))      # tìm từ điểm đã vào dáng, vẫn chừa dải nói
    # Đã biết điểm vào dáng ⇒ chỉ tìm trong `TIM_SAU_VAO_DANG` sau nó: phần trước vùng chờ bị cắt,
    # tìm xa (4s) thì chọn đoạn yên nhất ở tận giây 4 và cắt mất nửa chất liệu nói (đã gặp).
    tam = TIM_SAU_VAO_DANG if tu > 0 else TIM_CHO_TRONG
    het = max(tu + dai, min(n - 30, tu + tam))
    cd = np.asarray(chuyen_dong[:het], np.float64).copy()
    if len(cd) > 1:
        cd[0] = cd[1]                            # frame 0 không có «so với frame trước»
    tb_cd = _tb_cua_so(_chuan(cd), dai)
    tb_cd[:tu] = np.inf                          # cửa sổ bắt đầu trước khi vào dáng: loại
    if mieng is not None and len(mieng) >= het and not bo_qua_mieng:
        m = np.asarray(mieng, np.float64)
        # ≥ 90% frame trong cửa sổ phải khép — KHÔNG lấy trung bình độ mở (cửa sổ nửa khép nửa
        # nói lọt qua) và KHÔNG đòi 100% (số đo DWPose có nhiễu: trên video Wan thật, đòi 100%
        # đẩy vùng chờ vào GIỮA đoạn chuyển dáng; 90% ra đúng đoạn đã đứng yên ở dáng chuẩn).
        # Sàn tuyệt đối: clip KHÔNG NÓI (prompt hiện tại — môi khép cả video) có trung vị độ mở
        # rất nhỏ ⇒ ngưỡng tương đối rơi xuống mức nhiễu và frame khép bị coi là «mở».
        nguong = max(NGUONG_KHEP * float(np.median(m)), MIENG_KHEP_TUYET_DOI)
        frame_khep = (m[:het] <= nguong).astype(np.float64)
        khep = (_tb_cua_so(frame_khep, dai) >= TI_LE_KHEP - 1e-9) & np.isfinite(tb_cd)
        if khep.any():
            a = int(np.argmin(np.where(khep, tb_cd, np.inf)))
            return a, a + dai - 1
        if tu == 0:
            # Đã biết điểm vào dáng mà không có đoạn khép ⇒ chọn đoạn YÊN nhất, KHÔNG cộng điểm
            # miệng: cộng điểm kéo vùng chờ về đoạn ít nói nhưng còn rung (vùng chờ lúc đó đằng
            # nào cũng là frame MuseTalk — `mieng_khep` trả False).
            tb_cd = tb_cd + _tb_cua_so(_chuan(m[:het]), dai)
    a = int(np.argmin(tb_cd))
    return a, a + dai - 1


def mieng_khep(mieng, a, b):
    """Vùng chờ [a, b] có miệng KHÉP THẬT trong video gốc không ⇒ đứng chờ dùng frame GỐC
    (`BoCuc.cho_goc`), giữ nguyên môi khép + nụ cười mỉm của video. False ⇒ frame MuseTalk trên
    âm im lặng — MuseTalk học từ người đang nói, im lặng ra môi hơi hé và không cười được.

    Ngưỡng TUYỆT ĐỐI (không tương đối như `tim_vung_cho`): clip nói nhẹ có trung vị độ mở thấp,
    60% trung vị có thể lọt môi đang hé ~0,05 — hiện frame gốc như thế là đứng chờ mấp máy môi."""
    if mieng is None or b < a or len(mieng) <= b:
        return False
    m = np.asarray(mieng[a:b + 1], np.float64)
    return float(np.mean(m <= MIENG_KHEP_TUYET_DOI)) >= TI_LE_KHEP - 1e-9


def noi_tu_sau_khep(mieng, b, noi_tu, noi_den):
    """Đẩy đầu dải nói qua đoạn MIỆNG KHÉP liền sau vùng chờ [.., b]: MuseTalk lấy chính frame
    gốc làm tham chiếu khuôn miệng — nói trên frame mím môi ra khẩu hình mở hẹp. Không đẩy nếu
    dải nói còn lại < 8 frame."""
    m = np.asarray(mieng, np.float64)
    j = b + 1
    while j < len(m) and m[j] <= MIENG_KHEP_TUYET_DOI:
        j += 1
    return j if noi_tu < j <= noi_den - 8 else noi_tu


def tim_nhac_tay(tay_g):
    """Frame (trong G) cổ tay bắt đầu nhấc — trước nó lùi về G0 được mà không thấy tay."""
    if tay_g is None or len(tay_g) == 0:
        return 0
    tay = np.asarray(tay_g, np.float64)
    vuot = np.nonzero(tay >= NGUONG_NHAC_TAY)[0]
    return int(vuot[0]) if len(vuot) else len(tay) // 3


def diem_on_dinh(co_tay, nguong=NGUONG_ON_DINH, toi_da=TIM_CHO_TRONG):
    """Frame đầu tiên mà từ đó (trong `toi_da` frame đầu) hai cổ tay nằm ổn định ở vị trí của
    NỬA SAU clip — tức người đã vào dáng. `co_tay` = vị trí TB hai cổ tay theo chiều cao khung."""
    x = np.asarray(co_tay, np.float64)
    if len(x) < 4:
        return 0
    dich = float(np.median(x[len(x) // 2:]))
    lech = np.abs(x[: min(len(x), toi_da)] - dich) > nguong
    sai = np.nonzero(lech)[0]
    return int(sai[-1] + 1) if len(sai) else 0


def luu_khung_cho(avatar_dir, frame, jpg: bytes):
    """Ghi khung chờ (JPEG frame GỐC có nền) + chỉ số của nó trong clip nói CHƯA cắt."""
    with open(os.path.join(avatar_dir, KHUNG_CHO_JPG), "wb") as f:
        f.write(jpg)
    with open(os.path.join(avatar_dir, KHUNG_CHO_JSON), "w") as f:
        json.dump({"frame": int(frame)}, f)


def doc_khung_cho(avatar_dir):
    """Chỉ số khung chờ đã lưu, None nếu chưa có / hỏng."""
    try:
        with open(os.path.join(avatar_dir, KHUNG_CHO_JSON)) as f:
            return int(json.load(f)["frame"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def xoa_khung_cho(avatar_dir):
    for ten in (KHUNG_CHO_JPG, KHUNG_CHO_JSON):
        p = os.path.join(avatar_dir, ten)
        if os.path.exists(p):
            os.remove(p)


def vung_cho_da_luu(frame, dai, n_f):
    """Vùng chờ bắt đầu đúng ở khung chờ đã lưu — None nếu không có hoặc không còn nằm gọn
    trong clip (video nói đã đổi) ⇒ bên gọi đo lại."""
    if frame is None or frame < 0 or frame + dai > n_f - 30:
        return None
    return int(frame), int(frame + dai - 1)


def do_bo_cuc(
    chuyen_dong, mieng=None, n_g=0, tay_g=None, lech_vong=None, vung_cho=None, dai_cho=None, toc_cho=0.45,
    tu_cho=0, bo_qua_mieng=False,
) -> BoCuc:
    n_f = len(chuyen_dong)
    if n_f < F_TOI_THIEU:
        raise LoiDung("VIDEO_NGAN", f"đoạn nói chỉ có {n_f / FPS:.1f}s — cần ít nhất {F_TOI_THIEU // FPS}s")
    if n_g and n_g < G_TOI_THIEU:
        n_g = 0
    a, b = (
        vung_cho if vung_cho is not None
        else tim_vung_cho(chuyen_dong, mieng, dai_cho, tu=tu_cho, bo_qua_mieng=bo_qua_mieng)
    )
    f_cuoi = n_f - 1
    trung_vi = float(np.median(chuyen_dong[1:])) if n_f > 1 else 0.0
    vong = lech_vong is not None and lech_vong <= NGUONG_VONG * max(trung_vi, 1e-6)
    # Dải nói: sau vùng chờ một quãng (đi ra), chừa lề cuối (clip vòng: chỗ quay về F1;
    # không vòng: tránh dừng ở frame cuối — thường là lúc người trong video kết thúc câu).
    noi_tu = min(b + 6, f_cuoi - 10)
    le = max(4, n_f // 6)
    noi_den = max(noi_tu + 8, f_cuoi - le)
    noi_den = min(noi_den, f_cuoi)
    return BoCuc(
        f_cuoi=f_cuoi,
        g_dai=int(n_g),
        noi_tu=int(noi_tu),
        noi_den=int(noi_den),
        nhac_tay=tim_nhac_tay(tay_g[:n_g] if (n_g and tay_g is not None) else None) if n_g else 0,
        idle_from=int(a),
        idle_to=int(b),
        idle_speed=float(toc_cho),
        vong=bool(vong),
    )
