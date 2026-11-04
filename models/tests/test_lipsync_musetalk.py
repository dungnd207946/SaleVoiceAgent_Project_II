"""Test logic thuần của lipsync_musetalk (`tu_the.py`) — không torch, không GPU, không model.

Phần render (MuseTalk) cần GPU + ~4 GB weights nên không test ở đây; nghiệm thu bằng
client giả lập (đo frame đúng hạn) — xem lipsync_musetalk/README.md §Kiểm thử.
"""
from __future__ import annotations

import argparse
import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "lipsync_tu_the", str(Path(__file__).resolve().parent.parent / "lipsync_musetalk" / "tu_the.py")
)
tu_the = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tu_the)

CAU_HINH = argparse.Namespace(idle_from=1, idle_to=15, idle_speed=0.45, noi_tu=22, noi_den=100,
                              f_cuoi=120, nhac_tay=46)
# Mối nối đã đo trên clip người dẫn (lệch ≈ hai frame liền kề) — mọi bước KHÁC phải là frame kề.
MOI_NOI = {(120, 121), (241, 1), (121, 0), (0, 121), (120, 1)}


def _hoi_thoai(giay: int, seed: int) -> list[bool]:
    random.seed(seed)
    tieng: list[bool] = []
    while len(tieng) < 25 * giay:
        tieng += [True] * random.randint(50, 450) + [False] * random.randint(75, 200)
    return tieng[: 25 * giay]


def _chay(tieng, seed, lenh_tay=(), het_luot=()):
    random.seed(seed)
    d = tu_the.DuongTuThe(CAU_HINH)
    out = []
    for n in range(len(tieng)):
        if n in lenh_tay:
            d.yeu_cau_gio_tay(n)
        for het, bao in het_luot:
            if n == bao:
                d.dat_het_luot(het)
        # đúng hàm server dùng (Phien.co_tieng) — giữ ngắn ở cuối lượt khi đã báo het_luot
        out.append(d.toi(n, lambda m: tu_the.dang_noi(lambda k: 0 <= k < len(tieng) and tieng[k], d.het, m)))
    return out


@pytest.mark.parametrize("seed", range(4))
def test_moi_buoc_la_frame_ke_hoac_moi_noi_da_do(seed):
    seq = _chay(_hoi_thoai(180, seed), seed, lenh_tay={2500})
    la = [(n, seq[n - 1], seq[n]) for n in range(1, len(seq))
          if abs(seq[n] - seq[n - 1]) > 1 and (seq[n - 1], seq[n]) not in MOI_NOI]
    assert la == []


def test_im_lau_thi_o_vung_cho():
    tieng = _hoi_thoai(180, 1)
    seq = _chay(tieng, 1)
    im_lau = [seq[n] for n in range(len(seq)) if not any(tieng[max(0, n - 100):n + 1])]
    assert im_lau and all(1 <= x <= 15 for x in im_lau)


def test_lenh_dua_tay_vao_doan_g_trong_vai_giay():
    tieng = [True] * (25 * 20)                      # nói liên tục 20s
    seq = _chay(tieng, 0, lenh_tay={25})            # lệnh ở giây thứ 1
    vao_g = [n for n in range(1, len(seq)) if seq[n] == 121 and seq[n - 1] in (0, 120)]
    assert vao_g and vao_g[0] < 25 * 4


def test_bao_het_luot_ve_cho_som_hon_khong_bao():
    # 2,5s nói (< 3s ⇒ chưa tự đưa tay): hết tiếng lúc người đang ở dải NÓI của đoạn F.
    # (Tay đang giơ lúc hết tiếng thì cả hai cách đều phải làm nốt cử chỉ — không so được.)
    tieng = [True] * (25 * 5 // 2) + [False] * (25 * 6)
    het = 25 * 5 // 2 - 1

    def thua(seq):
        return next(n for n in range(het, len(seq)) if all(1 <= seq[k] <= 15 for k in range(n, n + 25))) - het

    khong = thua(_chay(tieng, 3))
    co = thua(_chay(tieng, 3, het_luot=[(het, het - 12)]))
    assert co < khong


def test_doan_ha_nhip_tang_dan_khop_cach_tinh_day_du():
    rng = np.random.default_rng(0)
    d, tat_ca = tu_the.Doan(0.0), []
    for i in range(2000):
        k = rng.integers(-3000, 3000, size=int(rng.integers(1, 1500)), dtype=np.int16)
        tat_ca.append(k)
        d.them(k)
        if i % 50 == 0:                             # giả lập render tiến lên ⇒ bộ đệm được cắt
            d.xong = max(d.xong, d.tong16 // tu_the.MAU16 - 20)
    ref = np.concatenate(tat_ca)
    n = len(ref) // 3 * 3
    ref16 = ref[:n].reshape(-1, 3).astype(np.float32).mean(1) / 32768
    a = (d.xong - tu_the.NGU_CANH_TRAI) * tu_the.MAU16
    assert d.tong16 == len(ref16)
    assert np.allclose(d.lay16(a, d.tong16), ref16[a:])
    assert d._dai < tu_the.SR16 * 6                 # chỉ giữ vài giây, không giữ cả cuộc gọi


# ── nhân vật KHÁCH tự tạo: bố cục tự đo (bo_cuc.py) + DuongTuThe với BoCuc tuỳ ý ──

def _bo_cuc_mod():
    import sys

    thu_muc = str(Path(__file__).resolve().parent.parent / "lipsync_musetalk")
    if thu_muc not in sys.path:
        sys.path.insert(0, thu_muc)
    import bo_cuc

    return bo_cuc


def _chay_bo_cuc(bc, tieng, seed, lenh_tay=()):
    random.seed(seed)
    d = tu_the.DuongTuThe(bc)
    out = []
    for n in range(len(tieng)):
        if n in lenh_tay:
            d.yeu_cau_gio_tay(n)
        out.append(d.toi(n, lambda m: tu_the.dang_noi(lambda k: 0 <= k < len(tieng) and tieng[k], d.het, m,
                                                      d.giu_noi)))
    return out


def _buoc_hop_le(seq, bc):
    """Nhân vật khách: bước kề, TRỪ lúc đi về chờ (bước dài hơn chỉ được hướng VỀ vùng chờ,
    ≤ VE_NHANH_TOI_DA, không vượt qua vùng chờ)."""
    lo, hi = bc.idle_from, bc.idle_to
    for a, b in zip(seq, seq[1:], strict=False):
        if abs(b - a) <= 1:
            continue
        ve = (a > hi and hi <= b < a) or (a < lo and a < b <= lo)
        if not ve or abs(b - a) > tu_the.VE_NHANH_TOI_DA:
            return False
    return True


def test_bo_cuc_mac_dinh_giu_nguyen_hanh_vi_clip_goc():
    """BoCuc() mặc định = đúng tham số CLI cũ ⇒ cùng seed ra cùng đường tư thế."""
    tieng = _hoi_thoai(120, 5)
    assert _chay_bo_cuc(tu_the.BoCuc(), tieng, 5, {900}) == _chay(tieng, 5, lenh_tay={900})


@pytest.mark.parametrize("seed", range(3))
def test_nhan_vat_khong_vong_khong_tay_chi_di_frame_ke(seed):
    """Video khách: không có G, frame cuối ≠ frame đầu ⇒ KHÔNG mối nối nào, kể cả khi có lệnh đưa tay."""
    bc = tu_the.BoCuc(f_cuoi=199, g_dai=0, noi_tu=30, noi_den=160, nhac_tay=0, idle_from=4, idle_to=19,
                      vong=False)
    seq = _chay_bo_cuc(bc, _hoi_thoai(180, seed), seed, lenh_tay={300, 2000})
    assert max(seq) <= 199
    assert _buoc_hop_le(seq, bc)


def test_nhan_vat_khong_vong_im_lau_ve_vung_cho():
    bc = tu_the.BoCuc(f_cuoi=149, g_dai=0, noi_tu=25, noi_den=120, idle_from=3, idle_to=18, vong=False)
    tieng = ([True] * 300 + [False] * 400) * 3      # người đi xa tận dải nói rồi mới im
    seq = _chay_bo_cuc(bc, tieng, 2)
    im_lau = [seq[n] for n in range(len(seq)) if not any(tieng[max(0, n - 200):n + 1])]
    assert im_lau and all(3 <= x <= 18 for x in im_lau)


def test_nhan_vat_co_g_khong_vong_vao_g_tu_f0():
    """Có clip đưa tay nhưng F không vòng ⇒ chỉ vào G qua F0 (G0 ≈ F0), không qua F_cuối."""
    bc = tu_the.BoCuc(f_cuoi=149, g_dai=100, noi_tu=25, noi_den=120, nhac_tay=30, idle_from=3, idle_to=18,
                      vong=False)
    seq = _chay_bo_cuc(bc, [True] * (25 * 20), 0, lenh_tay={25})
    vao_g = [(seq[n - 1], seq[n]) for n in range(1, len(seq)) if seq[n] == 150 and seq[n - 1] < 150]
    assert vao_g and all(a == 0 for a, _ in vao_g)
    assert max(seq) <= 249


def test_do_bo_cuc_tim_vung_cho_yen_lang_va_khep_mieng():
    bc_mod = _bo_cuc_mod()
    rng = np.random.default_rng(0)
    cd = 0.02 + 0.01 * rng.random(200)
    cd[30:46] = 0.001                                    # yên 16 frame ở giây ~1,2–1,8
    mieng = 0.05 + 0.02 * rng.random(200)
    mieng[30:46] = 0.0
    bc = bc_mod.do_bo_cuc(cd, mieng, lech_vong=0.2)
    assert (bc.idle_from, bc.idle_to) == (30, 45)
    assert bc.idle_to < bc.noi_tu < bc.noi_den <= bc.f_cuoi == 199
    assert bc.g_dai == 0 and bc.vong is False            # lệch vòng 0,2 ≫ chuyển động điển hình


def test_do_bo_cuc_vong_va_nhac_tay():
    bc_mod = _bo_cuc_mod()
    cd = np.full(125, 0.02)
    tay = np.concatenate([np.zeros(40), np.linspace(0, 0.2, 60)])
    bc = bc_mod.do_bo_cuc(cd, None, n_g=100, tay_g=tay, lech_vong=0.01)
    assert bc.vong is True and bc.g_dai == 100
    assert 40 <= bc.nhac_tay <= 55
    assert bc.so_frame == 225


def test_do_bo_cuc_video_ngan_bao_loi_co_ma():
    bc_mod = _bo_cuc_mod()
    with pytest.raises(bc_mod.LoiDung) as e:
        bc_mod.do_bo_cuc(np.full(40, 0.02))
    assert e.value.ma == "VIDEO_NGAN"


def test_do_bo_cuc_clip_tay_qua_ngan_bi_bo():
    bc_mod = _bo_cuc_mod()
    bc = bc_mod.do_bo_cuc(np.full(125, 0.02), n_g=30, tay_g=np.zeros(30))
    assert bc.g_dai == 0 and bc.so_frame == 125


def test_do_bo_cuc_video_ai_chinh_dang_vung_cho_sau_doan_chuyen_dang():
    """Video AI chỉnh dáng: ~1,5s đầu chuyển động mạnh (về dáng chuẩn), rồi đứng yên miệng khép
    ~1s, rồi nói. Vùng chờ phải rơi vào đoạn đứng yên (sau 1,5s) — dung_avatar cắt phần trước nó."""
    bc_mod = _bo_cuc_mod()
    rng = np.random.default_rng(1)
    cd = 0.02 + 0.01 * rng.random(200)
    cd[:38] = 0.08                                   # chuyển dáng: mạnh gấp ~3 lần lúc nói
    cd[38:64] = 0.001
    mieng = 0.05 + 0.02 * rng.random(200)
    mieng[:64] = 0.0                                 # chưa nói ⇒ miệng khép cả lúc chuyển dáng
    bc = bc_mod.do_bo_cuc(cd, mieng)
    assert 38 <= bc.idle_from and bc.idle_to <= 63


def test_san_cat_dau_khong_chon_vung_cho_trong_doan_chinh_dang():
    """Ca nv-71bd (2026-10-09): ảnh gốc tay đã ở gần dáng cuối ⇒ `diem_on_dinh` trả 0, mà vài frame
    đầu (dáng ẢNH, miệng khép) lại yên nhất ⇒ khung chờ rơi vào frame 0. Sàn cắt đầu 1,2s
    (`dung_avatar.doc_cat_dau_s`, truyền vào làm `tu_cho`) phải đẩy vùng chờ ra sau mốc đó."""
    bc_mod = _bo_cuc_mod()
    rng = np.random.default_rng(3)
    cd = 0.02 + 0.01 * rng.random(200)
    cd[1:4] = 0.0005                                 # dáng ảnh: yên nhất cả clip
    cd[4:25] = 0.06                                  # chỉnh dáng đầu/vai (cổ tay gần như đứng yên)
    cd[30:60] = 0.004
    mieng = 0.05 + 0.02 * rng.random(200)
    mieng[:60] = 0.0
    assert bc_mod.do_bo_cuc(cd, mieng, dai_cho=3).idle_from < 4  # không sàn: lấy dáng ẢNH
    san = round(1.2 * 25)
    bc = bc_mod.do_bo_cuc(cd, mieng, dai_cho=3, tu_cho=san)
    assert bc.idle_from >= san


def test_vung_cho_uu_tien_mieng_khep_hon_it_cu_dong():
    """Số đo THẬT của một video Wan (2026-10-07, trung bình mỗi 10 frame): miệng khép ở 0–2s
    (đang chuyển dáng, cử động nhiều), từ 2s nói liên tục mà thân lại RẤT yên. Bản cộng điểm
    chọn đoạn đang nói ⇒ người dẫn mấp máy môi khi đứng chờ. Phải chọn đoạn miệng khép."""
    bc_mod = _bo_cuc_mod()
    cd10 = [2.27, 3.94, 5.05, 3.33, 1.67, 1.14, 1.98, 1.29, 0.92, 1.29, 0.82, 0.69, 0.99, 0.75,
            0.74, 0.71, 0.78, 0.98, 0.95, 0.44]
    m10 = [0.030, 0.018, 0.029, 0.026, 0.021, 0.060, 0.085, 0.093, 0.061, 0.046, 0.062, 0.056,
           0.086, 0.046, 0.069, 0.076, 0.067, 0.084, 0.064, 0.024]
    cd, mieng = np.repeat(cd10, 10), np.repeat(m10, 10)
    a, b = bc_mod.tim_vung_cho(cd, mieng)
    assert float(mieng[a:b + 1].mean()) <= 0.03, (a, b)
    # trong các đoạn khép thì lấy đoạn YÊN nhất: tránh 0,8–1,2s (đang chuyển dáng mạnh nhất)
    assert not (20 <= a <= 30)


def test_do_bo_cuc_giu_vung_cho_truyen_vao():
    bc_mod = _bo_cuc_mod()
    bc = bc_mod.do_bo_cuc(np.full(150, 0.02), np.full(150, 0.05), vung_cho=(0, 15))
    assert (bc.idle_from, bc.idle_to) == (0, 15) and bc.noi_tu == 21


def test_vung_cho_tren_tin_hieu_tung_frame_that_cua_video_wan():
    """Tín hiệu TỪNG FRAME đo trên video Wan thật (100 frame đầu, mỗi 4 frame một mẫu, lặp 4):
    vùng chờ phải là đoạn đã đứng yên ở dáng chuẩn (~frame 36–52), không phải giữa lúc chuyển
    dáng (≤ 32) cũng không phải lúc đang nói (≥ 56)."""
    bc_mod = _bo_cuc_mod()
    cd4 = [0.0076, 0.019, 0.0275, 0.035, 0.0322, 0.0217, 0.0387, 0.0563, 0.028, 0.0181, 0.0163,
           0.0112, 0.0067, 0.0077, 0.0114, 0.0163, 0.016, 0.0144, 0.0113, 0.008, 0.0077, 0.0068,
           0.0101, 0.0095, 0.01] + [0.009] * 25
    m4 = [0.027, 0.035, 0.024, 0.015, 0.019, 0.022, 0.034, 0.034, 0.026, 0.019, 0.026, 0.015,
          0.027, 0.052, 0.084, 0.087, 0.078, 0.099, 0.088, 0.094, 0.062, 0.054, 0.068, 0.048,
          0.033] + [0.07] * 25
    a, _ = bc_mod.tim_vung_cho(np.repeat(cd4, 4), np.repeat(m4, 4))
    assert 33 <= a <= 40, a


def test_vung_cho_ngan_chon_doan_yen_hon_cua_so_dai():
    """Cửa sổ 8 frame (nhân vật khách) né được phần đuôi động tác chỉnh dáng mà cửa sổ 16 ôm vào."""
    bc_mod = _bo_cuc_mod()
    cd = np.full(160, 0.008)
    cd[:37] = 0.03                                   # chỉnh dáng
    cd[37:45] = 0.016                                # đuôi động tác — còn rung
    cd[45:53] = 0.005                                # đứng yên thật
    mieng = np.full(160, 0.07)
    mieng[:53] = 0.02
    a16, _ = bc_mod.tim_vung_cho(cd, mieng)
    a8, b8 = bc_mod.tim_vung_cho(cd, mieng, 8)
    assert a16 <= 40 and (a8, b8) == (45, 52)
    assert bc_mod.do_bo_cuc(cd, mieng, dai_cho=8, toc_cho=0.3).idle_speed == 0.3


def test_clip_khong_noi_mieng_khep_ca_video_van_chon_doan_yen_nhat():
    """Prompt mới: nhân vật KHÔNG nói cả clip (môi khép, độ mở ~0,02 có nhiễu). Ngưỡng tương đối
    (60% trung vị) rơi xuống ~0,012 ⇒ cần sàn tuyệt đối, nếu không vùng chờ chọn theo nhiễu."""
    bc_mod = _bo_cuc_mod()
    rng = np.random.default_rng(3)
    mieng = 0.02 + 0.008 * rng.random(200)
    cd = np.full(200, 0.008)
    cd[:37] = 0.03                                   # chỉnh dáng
    cd[60:68] = 0.003                                # đoạn yên nhất
    a, b = bc_mod.tim_vung_cho(cd, mieng, 8)
    assert (a, b) == (60, 67)


def test_vung_cho_sau_diem_vao_dang_khi_ai_noi_ngay():
    """Số đo THẬT (Wan 2026-10-08, TB mỗi 10 frame): cổ tay 0,99 (dáng ảnh, tay buông) → 0,92
    (khoanh trước bụng) trong 0,4–0,8s; miệng chỉ khép ở 10 frame đầu rồi nói liên tục. Vùng chờ
    phải nằm SAU khi tay đã vào dáng — không phải dáng ảnh ở frame đầu."""
    bc_mod = _bo_cuc_mod()
    tay10 = [0.992, 0.968, 0.924, 0.924, 0.923, 0.925, 0.927, 0.927, 0.929, 0.930, 0.932, 0.932,
             0.933, 0.932, 0.930, 0.929, 0.930, 0.931, 0.929, 0.928]
    cd10 = [0.0060, 0.0265, 0.0177, 0.0135, 0.0074, 0.0046, 0.0079, 0.0054, 0.0067, 0.0077, 0.0058,
            0.0042, 0.0063, 0.0070, 0.0070, 0.0062, 0.0071, 0.0080, 0.0049, 0.0037]
    m10 = [0.016, 0.074, 0.108, 0.103, 0.143, 0.085, 0.076, 0.104, 0.120, 0.081, 0.078, 0.117,
           0.082, 0.081, 0.131, 0.120, 0.125, 0.102, 0.075, 0.037]
    tay, cd, m = np.repeat(tay10, 10), np.repeat(cd10, 10), np.repeat(m10, 10)
    on_dinh = bc_mod.diem_on_dinh(tay)
    assert 10 <= on_dinh <= 20, on_dinh
    bc = bc_mod.do_bo_cuc(cd, m, dai_cho=8, tu_cho=on_dinh)
    assert on_dinh <= bc.idle_from <= on_dinh + 38          # ngay sau khi vào dáng, không tận giây 4
    assert float(np.mean(cd[bc.idle_from + 1:bc.idle_to + 1])) <= 0.0060
    # Đoạn đó đang nói ⇒ đứng chờ KHÔNG được dùng frame gốc.
    assert not bc_mod.mieng_khep(m, bc.idle_from, bc.idle_to)
    # Đối chứng: chọn theo «miệng khép» như cũ thì rơi đúng dáng ảnh ở frame đầu.
    assert bc_mod.tim_vung_cho(cd, m, 8)[0] < 10


def test_doan_mim_cuoi_im_lang_sau_vao_dang_thanh_vung_cho_frame_goc():
    """Prompt mới: vào dáng (~0,5s) → mỉm cười IM LẶNG (~1,5s) → nói. Vùng chờ phải rơi vào đoạn
    im lặng SAU khi vào dáng (không phải dáng ảnh ở frame đầu dù ở đó miệng cũng khép), và đoạn
    đó đủ khép để đứng chờ dùng frame GỐC."""
    bc_mod = _bo_cuc_mod()
    n = 200
    tay = np.full(n, 0.92)
    tay[:12] = np.linspace(0.99, 0.92, 12)           # dáng ảnh → tay khoanh trước bụng
    cd = np.full(n, 0.007)
    cd[:14] = 0.03                                   # chuyển dáng
    cd[20:28] = 0.004                                # đứng yên nhất — nhưng ĐANG NÓI nếu thiếu đoạn im
    m = np.full(n, 0.09)                             # nói
    m[:10] = 0.02                                    # dáng ảnh: môi khép
    m[14:50] = 0.02                                  # mỉm cười im lặng sau khi vào dáng
    m[20:28] = 0.02
    on_dinh = bc_mod.diem_on_dinh(tay)
    bc = bc_mod.do_bo_cuc(cd, m, dai_cho=8, tu_cho=on_dinh)
    assert bc.idle_from >= on_dinh and bc.idle_to < 50, (on_dinh, bc.idle_from, bc.idle_to)
    assert bc_mod.mieng_khep(m, bc.idle_from, bc.idle_to)


def test_vao_dang_khong_co_doan_im_thi_chon_doan_yen_khong_lay_doan_noi_it():
    """Wan không theo mốc thời gian của prompt (nói ngay sau khi vào dáng): giữ hành vi cũ —
    đoạn YÊN nhất sau điểm vào dáng, đứng chờ bằng frame MuseTalk."""
    bc_mod = _bo_cuc_mod()
    n = 200
    cd = np.full(n, 0.008)
    cd[:14] = 0.03
    cd[30:38] = 0.003                                # yên nhất, miệng mở to
    m = np.full(n, 0.07)
    m[60:68] = 0.045                                 # nói nhỏ — cộng điểm miệng sẽ kéo về đây
    m[30:38] = 0.1
    a, b = bc_mod.tim_vung_cho(cd, m, 8, tu=14)
    assert (a, b) == (30, 37)
    assert not bc_mod.mieng_khep(m, a, b)


def test_mieng_khep_dung_nguong_tuyet_doi():
    bc_mod = _bo_cuc_mod()
    assert bc_mod.mieng_khep(np.full(20, 0.02), 2, 9)
    assert not bc_mod.mieng_khep(np.full(20, 0.05), 2, 9)     # hé ~0,05: tương đối có thể lọt
    m = np.full(20, 0.02)
    m[3] = 0.06                                               # 1/8 frame nhiễu — vẫn < 90%
    assert not bc_mod.mieng_khep(m, 2, 9)
    m = np.full(30, 0.02)
    m[5] = 0.06                                               # 1/20 frame nhiễu ⇒ 95% khép
    assert bc_mod.mieng_khep(m, 0, 19)
    assert not bc_mod.mieng_khep(None, 0, 5) and not bc_mod.mieng_khep(m, 25, 40)


@pytest.mark.parametrize("seed", range(3))
def test_vung_cho_3_frame_van_dung_yen_va_di_frame_ke(seed):
    """Vùng chờ ~0,1s (3 frame, đã cắt phần trước ⇒ [0, 2]): im lâu thì ở trong [0, 2], mọi bước
    là frame kề — vùng chờ siêu ngắn không làm đường tư thế nhảy; dải nói bắt đầu sau đoạn khép."""
    bc_mod = _bo_cuc_mod()
    cd = np.full(170, 0.007)
    mieng = np.full(170, 0.08)
    mieng[:12] = 0.02                                 # phần còn lại của đoạn im lặng
    bc = bc_mod.do_bo_cuc(cd, mieng, vung_cho=(0, 2), toc_cho=0.3)
    bc.noi_tu = bc_mod.noi_tu_sau_khep(mieng, 2, bc.noi_tu, bc.noi_den)
    assert (bc.idle_from, bc.idle_to) == (0, 2) and bc.noi_tu == 12
    seq = _chay_bo_cuc(bc, _hoi_thoai(180, seed), seed)
    assert _buoc_hop_le(seq, bc)
    tieng = ([True] * 300 + [False] * 400) * 3      # người đi xa tận dải nói rồi mới im
    seq = _chay_bo_cuc(bc, tieng, seed)
    im_lau = [seq[n] for n in range(len(seq)) if not any(tieng[max(0, n - 200):n + 1])]
    assert im_lau and all(0 <= x <= 2 for x in im_lau)


def test_noi_tu_sau_khep_khong_day_qua_dai_noi():
    bc_mod = _bo_cuc_mod()
    m = np.full(100, 0.08)
    assert bc_mod.noi_tu_sau_khep(m, 2, 8, 80) == 8           # nói ngay sau vùng chờ: giữ
    m[:95] = 0.02
    assert bc_mod.noi_tu_sau_khep(m, 2, 8, 80) == 8           # khép gần hết clip: không đẩy


def test_vung_cho_3_frame_nam_trong_doan_im_lang_0_5_den_2_giay():
    """Prompt: 0–0,5s vào dáng, 0,5–2s im lặng môi khép, sau đó nói. Vùng chờ 3 frame phải nằm
    TRONG đoạn im lặng, ở chỗ yên nhất; đứng chờ dùng frame gốc."""
    bc_mod = _bo_cuc_mod()
    n = 200
    tay = np.full(n, 0.92)
    tay[:12] = np.linspace(0.99, 0.92, 12)           # vào dáng trong ~0,5s
    cd = np.full(n, 0.007)
    cd[:13] = 0.03
    cd[30:34] = 0.002                                # khoảnh khắc đứng yên nhất trong đoạn im
    m = np.full(n, 0.08)
    m[:8] = 0.02                                     # dáng ảnh: môi khép (phải bị loại)
    m[12:50] = 0.02                                  # im lặng 0,5–2s
    on_dinh = bc_mod.diem_on_dinh(tay)
    a, b = bc_mod.tim_vung_cho(cd, m, 3, tu=on_dinh)
    assert b - a == 2 and 12 <= a and b < 50, (on_dinh, a, b)
    assert 30 <= a <= 31
    assert bc_mod.mieng_khep(m, a, b)


@pytest.mark.parametrize("seed", range(5))
def test_nhan_vat_khach_het_tieng_la_ve_cho_ngay(seed):
    """Bug người dùng báo 2026-10-08: hết câu mà người còn cử động 1,2–2,4s rồi mới đứng yên
    (giữ «đang nói» 1s + lùi từng frame từ tận frame ~60). Bố cục THẬT của nhân vật vừa dựng;
    KHÔNG báo `het_luot` trước (thực tế agent_done thường tới khi tư thế đã tính xong)."""
    bc = tu_the.BoCuc(f_cuoi=140, g_dai=0, noi_tu=8, noi_den=117, nhac_tay=0, idle_from=0, idle_to=2,
                      idle_speed=0.3, vong=False)
    for giay in (3, 5, 8, 12):
        tieng = [False] * 50 + [True] * (25 * giay) + [False] * 300
        het = 50 + 25 * giay - 1
        seq = _chay_bo_cuc(bc, tieng, seed)
        ve = next(n for n in range(het, len(seq)) if all(0 <= seq[k] <= 2 for k in range(n, n + 10)))
        assert ve - het <= 18, (giay, seq[het], ve - het)              # ≤ 0,72s (trước: tới 61 nhịp)


def test_nguoi_dan_goc_van_giu_noi_1s_va_lui_tung_frame():
    """Người dẫn mặc định (có clip đưa tay) KHÔNG đổi: vẫn giữ GIU_NOI, về chờ từng frame."""
    d = tu_the.DuongTuThe(tu_the.BoCuc())
    assert d.giu_noi == tu_the.GIU_NOI and d._buoc_ve(80) == 1


# Bố cục THẬT (info.json) — nhân vật khách nay có clip đưa tay (g_dai=125) và người dẫn mặc định.
BO_CUC_THAT = [
    tu_the.BoCuc(),
    tu_the.BoCuc(f_cuoi=149, g_dai=125, noi_tu=15, noi_den=124, nhac_tay=21, idle_from=0, idle_to=2,
                 idle_speed=0.3, vong=False),
    tu_the.BoCuc(f_cuoi=94, g_dai=125, noi_tu=11, noi_den=79, nhac_tay=23, idle_from=0, idle_to=2,
                 idle_speed=0.3, vong=False),
]


def _chay_het_luot(bc, tieng, seed, het, bao, lenh_tay=()):
    """Như server: `het_luot` tới ở nhịp `bao` (agent_done), tư thế tính lần lượt từng nhịp."""
    random.seed(seed)
    d = tu_the.DuongTuThe(bc)
    out = []
    for n in range(len(tieng)):
        if n in lenh_tay:
            d.yeu_cau_gio_tay(n)
        if n == bao:
            d.dat_het_luot(het)
        out.append(d.toi(n, lambda m: tu_the.dang_noi(lambda k: 0 <= k < len(tieng) and tieng[k], d.het, m,
                                                      d.giu_noi)))
    return out


def _nhip_ve_cho(seq, bc, het):
    lo, hi = bc.idle_from, bc.idle_to
    return next(n for n in range(het, len(seq)) if all(lo <= seq[k] <= hi for k in range(n, n + 10))) - het


@pytest.mark.parametrize("bc", BO_CUC_THAT, ids=["mac_dinh", "khach_dai", "khach_ngan"])
@pytest.mark.parametrize("seed", range(4))
def test_het_luot_ve_cho_ngay_ca_khi_co_dua_tay(bc, seed):
    """Bug 2026-10-14: hết voice mà nhân vật còn cử động/mấp máy 1–2s (đo: tb 1,1–1,4s, tệ nhất
    ~4s) — nhân vật có clip đưa tay lùi về chờ TỪNG frame, đang giơ tay thì làm nốt cử chỉ.
    Đã biết hết lượt (`het_luot`) ⇒ tới vùng chờ trong ≤ 0,4s kể cả đang giơ tay."""
    for giay in (2, 4, 7, 11):
        tieng = [False] * 50 + [True] * (25 * giay) + [False] * 300
        het = 50 + 25 * giay - 1
        for bao in (het - 12, het, het + 4):
            seq = _chay_het_luot(bc, tieng, seed, het, bao, lenh_tay={60})
            assert _nhip_ve_cho(seq, bc, het) <= 10, (giay, bao, seq[het])


@pytest.mark.parametrize("bc", BO_CUC_THAT, ids=["mac_dinh", "khach_dai", "khach_ngan"])
def test_het_luot_tre_chi_tre_dung_bang_do_tre(bc):
    """agent_done tới muộn 0,5s (tư thế đã tính theo «giữ 1s») ⇒ từ lúc biết là về ngay."""
    tieng = [False] * 50 + [True] * 100 + [False] * 300
    het = 149
    seq = _chay_het_luot(bc, tieng, 0, het, het + 13)
    assert _nhip_ve_cho(seq, bc, het) <= 13 + 10


@pytest.mark.parametrize("bc", BO_CUC_THAT, ids=["mac_dinh", "khach_dai", "khach_ngan"])
def test_ve_cho_cuoi_luot_van_la_mot_duong_lien(bc):
    """Về nhanh nhưng KHÔNG nhảy cắt cảnh: mỗi bước ≤ một nửa quãng còn lại (chậm dần khi tới nơi)."""
    tieng = [False] * 50 + [True] * 175 + [False] * 300
    het = 224
    seq = _chay_het_luot(bc, tieng, 1, het, het)
    lo, hi = bc.idle_from, bc.idle_to
    sau = seq[het + tu_the.GIU_NGAN:]
    g0 = bc.f_cuoi + 1                                     # mối nối F↔G đã đo: chỉ số nhảy, hình liền
    bc_ve = [abs(b - a) for a, b in zip(sau, sau[1:], strict=False)
             if not (lo <= a <= hi) and (a >= g0) == (b >= g0)]
    assert bc_ve and max(bc_ve) <= max(bc.f_cuoi, bc.g_dai) // 2 + 1


# ── clip đưa tay sinh TỪ khung chờ: lần dựng 1 lưu khung chờ, lần dựng có G cắt F đúng chỗ đó ──

def test_khung_cho_luu_roi_doc_lai_chi_so(tmp_path):
    bc_mod = _bo_cuc_mod()
    assert bc_mod.doc_khung_cho(tmp_path) is None
    bc_mod.luu_khung_cho(tmp_path, 41, b"JPEG")
    assert bc_mod.doc_khung_cho(tmp_path) == 41
    assert (tmp_path / bc_mod.KHUNG_CHO_JPG).read_bytes() == b"JPEG"


def test_khung_cho_xoa_khi_video_noi_doi(tmp_path):
    bc_mod = _bo_cuc_mod()
    bc_mod.luu_khung_cho(tmp_path, 41, b"JPEG")
    bc_mod.xoa_khung_cho(tmp_path)
    assert bc_mod.doc_khung_cho(tmp_path) is None
    assert not (tmp_path / bc_mod.KHUNG_CHO_JPG).exists()
    bc_mod.xoa_khung_cho(tmp_path)                  # chưa có gì: không lỗi


def test_khung_cho_hong_coi_nhu_chua_co(tmp_path):
    bc_mod = _bo_cuc_mod()
    (tmp_path / bc_mod.KHUNG_CHO_JSON).write_text("{hỏng")
    assert bc_mod.doc_khung_cho(tmp_path) is None


def test_vung_cho_da_luu_bat_dau_dung_khung_cho():
    bc_mod = _bo_cuc_mod()
    assert bc_mod.vung_cho_da_luu(41, 3, 200) == (41, 43)
    assert bc_mod.vung_cho_da_luu(None, 3, 200) is None
    assert bc_mod.vung_cho_da_luu(199, 3, 200) is None   # vượt clip (video nói đã đổi) ⇒ đo lại
    assert bc_mod.vung_cho_da_luu(-1, 3, 200) is None


# ── biết trước câu sắp hết (portal ước lượng từ `agent_speaking`) ⇒ không đưa tay sát cuối câu ──

def _chay_cau(bc, cau, seed, lenh_tay=()):
    """`cau` = [(bắt đầu, độ dài thật, độ dài ước lượng)] theo nhịp; portal báo `cau` lúc câu bắt đầu."""
    random.seed(seed)
    tong = max(a + d for a, d, _ in cau) + 300
    tieng = [False] * tong
    for a, d, _ in cau:
        tieng[a:a + d] = [True] * d
    d = tu_the.DuongTuThe(bc)
    out = []
    for n in range(tong):
        if n in lenh_tay:
            d.yeu_cau_gio_tay(n)
        for a, _, uoc in cau:
            if n == a:
                d.dat_cau(a + uoc)
        out.append(d.toi(n, lambda m: tu_the.dang_noi(lambda k: 0 <= k < tong and tieng[k], d.het, m,
                                                      d.giu_noi)))
    return out


def _vao_g(seq, bc):
    g0 = bc.f_cuoi + 1
    return [n for n in range(1, len(seq)) if seq[n] == g0 and seq[n - 1] < g0]


@pytest.mark.parametrize("bc", BO_CUC_THAT, ids=["mac_dinh", "khach_dai", "khach_ngan"])
@pytest.mark.parametrize("seed", range(4))
def test_khong_dua_tay_khi_cau_khong_du_dai_lam_tron_cu_chi(bc, seed):
    """Câu nối nhau 2–5s (ngắn hơn cử chỉ ~5s), có lệnh đưa tay ⇒ không lần nào vào G: vào G
    sát cuối câu thì hết câu tay đang giơ, về chờ đột ngột — trông giả."""
    random.seed(100 + seed)
    cau, a = [], 50
    for _ in range(12):
        dai = random.randint(50, 125)
        cau.append((a, dai, dai))
        a += dai + random.randint(5, 15)
    seq = _chay_cau(bc, cau, seed, lenh_tay={c[0] + 5 for c in cau})
    assert _vao_g(seq, bc) == []


@pytest.mark.parametrize("bc", BO_CUC_THAT, ids=["mac_dinh", "khach_dai", "khach_ngan"])
@pytest.mark.parametrize("seed", range(4))
def test_cau_dai_van_dua_tay_va_lam_xong_truoc_khi_het_cau(bc, seed):
    """Câu 14s + lệnh đưa tay ⇒ vẫn đưa tay, và mọi lần vào G đều còn đủ câu để làm trọn cử chỉ."""
    cau = [(50, 350, 350), (410, 100, 100)]
    seq = _chay_cau(bc, cau, seed, lenh_tay={60})
    vao = _vao_g(seq, bc)
    assert vao, "câu dài phải còn đưa tay"
    for n in vao:
        ket = next(a + uoc for a, _, uoc in reversed(cau) if a <= n)
        assert ket - n >= bc.g_dai, (n, ket)


def test_chua_biet_do_dai_cau_giu_hanh_vi_cu():
    """Không có `cau` (portal cũ, xem trước offline) ⇒ đưa tay như trước."""
    tieng = [True] * (25 * 20)
    seq = _chay(tieng, 0, lenh_tay={25})
    vao_g = [n for n in range(1, len(seq)) if seq[n] == 121 and seq[n - 1] in (0, 120)]
    assert vao_g and vao_g[0] < 25 * 4
