"""Logic THUẦN của lipsync_musetalk — không torch, không GPU, test được trên mọi máy.

  • `DuongTuThe` — đường đi tư thế cơ thể (port `nguoiDan.ts` của người dẫn Kling cũ):
    chờ / nói (đầu có cử động) / đưa tay / về chờ đúng lúc tiếng tắt.
  • `Doan`       — bộ đệm một đoạn audio liền mạch, hạ nhịp 48→16 kHz TĂNG DẦN.

Hằng số thời gian tính bằng NHỊP = 1/25 s (một frame).
"""

import random
import threading
import time
from dataclasses import asdict, dataclass

import numpy as np

FPS = 25
SR16 = 16000
SR48 = 48000
MAU16 = SR16 // FPS          # 640 mẫu 16k / frame
MAU48 = SR48 // FPS          # 1920 mẫu 48k / frame
NGU_CANH_TRAI = 10           # frame audio bên trái đưa vào whisper (0.4s)
NGU_CANH_PHAI = 3            # frame audio bên phải cần có trước khi render (120ms — xem get_whisper_chunk)
NGUONG_IM = 0.006            # RMS (float −1…1) dưới mức này coi cả batch là im ⇒ dùng frame idle
HET_DOAN_S = 0.25            # không có audio mới bấy lâu ⇒ chốt đoạn (đệm im lặng, render nốt)
JPEG_Q = 85
GIU_NGAN = 4                 # nhịp (0,16s) giữ «đang nói» ở CUỐI LƯỢT (đã biết lượt xong)
MUON_TOI = 12                # audio có tiếng tới sau agent_done mà liền sát mốc (≤0,5s) ⇒ vẫn của lượt đó
CUA_SO_HET = 50              # nhịp sau mốc hết lượt vẫn coi là thuộc lượt đó (audio tới muộn)
GIU_NOI = 25                 # nhịp (1s) giữ «đang nói» sau tiếng cuối — bắc cầu quãng nghỉ giữa
                             # các cụm/câu TTS (0,4s là quá ngắn: người lùi về chờ giữa câu,
                             # yêu cầu đưa tay bị huỷ trước khi kịp tới đoạn G)
VE_NHANH_NHIP = 3             # nhân vật khách: im lặng ⇒ bước = quãng còn lại / 3 (chậm dần khi gần tới)
VE_NHANH_TOI_DA = 6          # … nhưng không quá 6 frame/nhịp (đầu đã khoá, thân gần như yên)
VE_CUOI_NHIP = 2             # CUỐI LƯỢT (đã biết `het_luot`): bước = nửa quãng còn lại, không trần —
                             # mọi nhân vật (kể cả có clip đưa tay) về tới chờ trong ~0,3s sau tiếng
                             # cuối. Lùi từng frame thì hết voice người còn cử động 1–4s (đo 2026-10-14).
DU_TAY = 8                   # nhịp (0,32s) dư khi xét câu còn đủ dài cho trọn cử chỉ đưa tay
DU_THUA_S = 0.35             # dư dưới (thời gian một lô + mức này) ⇒ render cách một frame
LECH_CUA_SO_S = 3.0          # cửa sổ ước lượng độ lệch đồng hồ trình duyệt ↔ server


@dataclass
class BoCuc:
    """Bố cục clip nhân vật — các mốc (chỉ số frame GỐC) mà `DuongTuThe` đi theo.

    Mặc định = clip người dẫn Kling đóng gói trong image (F 0–120 + G 121–241, đo tay).
    Nhân vật khách tự tạo thì `bo_cuc.do_bo_cuc()` tự đo từ video và lưu vào info.json.
    """

    f_cuoi: int = 120          # frame cuối đoạn nói F; G (nếu có) bắt đầu ngay sau
    g_dai: int = 121           # số frame đoạn đưa tay G; 0 = KHÔNG có cử chỉ đưa tay
    noi_tu: int = 22           # dải tư thế lúc nói (đầu có cử động)
    noi_den: int = 100
    nhac_tay: int = 46         # frame trong G bắt đầu nhấc tay
    idle_from: int = 1         # vùng tư thế chờ (miệng khép)
    idle_to: int = 15
    idle_speed: float = 0.45   # tốc đưa qua lại trong vùng chờ
    vong: bool = True          # frame cuối F ≈ frame đầu ⇒ được đi tiếp F_cuối → F1 (vòng liền)
    cho_goc: bool = True       # vùng chờ dùng frame GỐC (miệng khép thật trong clip); False ⇒ dùng
                               # frame MuseTalk trên âm im lặng (môi hơi hé, không cười được) — nhân
                               # vật khách: `dung_avatar` đo (`bo_cuc.mieng_khep`) rồi quyết

    @property
    def so_frame(self):
        return self.f_cuoi + 1 + self.g_dai

    def dict(self):
        return asdict(self)

    @classmethod
    def tu_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def dang_noi(co_tieng_luc, het, n, giu_noi=GIU_NOI):
    """Nhịp `n` có tính là «đang nói» không. Giữ GIU_NOI nhịp sau tiếng cuối — khoảng
    ngắt GIỮA CÁC CÂU trong lượt không làm người quay về chờ rồi lại đi ra. Nhưng ở
    CUỐI LƯỢT (`het` = nhịp tiếng cuối, biết qua `het_luot`) chỉ giữ GIU_NGAN: không câu
    nào tới nữa, giữ 1s là cử động thừa. `co_tieng_luc(m)` ⇒ nhịp m có tiếng không."""
    cuoi = het is not None and het - GIU_NOI <= n <= het + CUA_SO_HET
    giu = GIU_NGAN if cuoi else giu_noi
    return any(co_tieng_luc(m) for m in range(n - giu, n + 1))


class DuongTuThe:
    """Đường đi tư thế cơ thể theo NHỊP (1/25s, đồng hồ server) — bản port của
    `nguoiDan.ts` (người dẫn Kling cũ). Clip gốc = F (0…f_cuoi, nói) + G (đưa tay).

      • IM:  xuôi–ngược chậm trong vùng chờ [cho_tu, cho_den] (miệng khép, gần đứng yên).
      • NÓI: đi tiếp từ chỗ đang đứng vào dải nói [noi_tu, noi_den] (đầu có cử động),
             xuôi–ngược, đổi chiều ngẫu nhiên mỗi 1,2–3s để không thành vòng lặp đều.
      • ĐƯA TAY: nói liên tục ≥ 3s (cách nhau 8–14s) hoặc có lệnh `gio_tay` ⇒ chạy tới
             cuối F, nối sang G0, hết G nối về F1 (các mối nối đã đo ≈ hai frame liền kề).
      • HẾT NÓI: về vùng chờ theo hướng gần hơn; trong G mà tay chưa nhấc ⇒ lùi về G0≈F0,
             tay đã nhấc ⇒ làm nốt cử chỉ.

    Tư thế của nhịp n chỉ phụ thuộc tiếng ở nhịp ≤ n (nhân quả) và được tính MỘT lần,
    lưu lại ⇒ frame nói (render trước ~1s) và frame chờ (gửi đúng lúc) luôn khớp nhau.

    Nhân vật khách tự tạo (`BoCuc`): `g_dai = 0` ⇒ không bao giờ đưa tay; `vong = False`
    (frame cuối F không giống frame đầu) ⇒ không bao giờ đi qua mối nối F_cuối → F1, mọi
    đường về chờ / vào G đều đi LÙI.
    """

    def __init__(self, a):
        self.cho = (a.idle_from, a.idle_to)
        self.toc_cho = a.idle_speed
        self.noi = (a.noi_tu, a.noi_den)
        self.f1 = a.f_cuoi
        self.g0 = a.f_cuoi + 1
        g_dai = getattr(a, "g_dai", a.f_cuoi + 1)  # clip gốc: G dài bằng F
        self.co_tay = g_dai > 0
        # Nhân vật KHÁCH (không đưa tay): hết tiếng là về chờ NGAY. Giữ 1s (GIU_NOI) chỉ để yêu cầu
        # đưa tay kịp tới G và người dẫn Kling không lùi giữa câu; ở đây đầu khoá, thân gần như yên
        # ⇒ lùi về giữa câu không lộ, còn giữ 1s + lùi từng frame thì sau tiếng cuối người còn chạy
        # 1,2–2,4s (đo bằng giả lập trên bố cục thật, 2026-10-08) — `het_luot` (agent_done) tới
        # thường đã muộn: tư thế được tính lúc audio tới, trước khi phát ~1s.
        self.giu_noi = GIU_NOI if self.co_tay else GIU_NGAN
        self.ve_nhanh = not self.co_tay
        self.g1 = self.g0 + g_dai - 1
        self.vong = getattr(a, "vong", True)
        self.nhac = self.g0 + a.nhac_tay
        self.khoa = threading.Lock()
        self.bang: dict[int, int] = {}
        self.n = None                              # nhịp cuối đã tính
        self.vt = float(a.idle_from)               # vị trí (frame gốc), số thực khi đi chậm
        self.huong = 1
        self.noi_tu = None                         # nhịp bắt đầu lượt nói hiện tại
        self.muon_tay = False
        self.lenh_tay = -1e9
        self.hen_tay = -1e9
        self.hen_dao = 0
        self.het = None                            # nhịp tiếng cuối của lượt vừa xong (nếu biết)
        self.ket_cau = None                        # nhịp (ước lượng) câu đang nói sẽ hết — `dat_cau`

    def dat_het_luot(self, n):
        """Lượt trả lời đã xong, tiếng cuối ở nhịp `n` (biết trước ~1,2s nhờ trễ phát)."""
        with self.khoa:
            self.het = n if self.het is None or n > self.het + CUA_SO_HET else max(self.het, n)

    def dat_cau(self, n):
        """Câu vừa bắt đầu sẽ hết ở nhịp `n` (portal ước lượng từ text `agent_speaking`)."""
        with self.khoa:
            self.ket_cau = n

    def _du_cho_tay(self, n, duong):
        """Câu còn đủ dài để đi `duong` nhịp tới G rồi làm TRỌN cử chỉ đưa tay trước khi hết câu.
        Vào G sát cuối câu thì hết câu tay đang giơ, về chờ đột ngột — trông giả. Chưa biết độ dài
        câu (portal cũ, xem trước offline) ⇒ cho phép như trước."""
        return self.ket_cau is None or self.ket_cau - n >= duong + (self.g1 - self.g0 + 1) + DU_TAY

    def _duong_vao_g(self, i):
        """Số nhịp từ tư thế `i` (trong F) tới điểm vào G — cùng đường với nhánh `muon_tay`."""
        if i <= 0 or (self.vong and i >= self.f1):
            return 0
        if not self.vong or i <= (self.cho[0] + self.f1) // 2:
            return i
        return self.f1 - i

    def _dang_ket(self, n, i):
        """Cuối lượt và còn ít nhịp hơn quãng đường về ⇒ phải đi về NGAY để tới vùng
        chờ đúng lúc tiếng tắt (như `taoBoDoNoi`/`giayVeNghi` của người dẫn cũ)."""
        if self.het is None or n > self.het + GIU_NGAN:
            return False
        return self.het - n <= self._so_nhip_ve(self._duong_ve(i)) + 1

    def _cuoi_luot(self, n):
        """Nhịp `n` nằm quanh tiếng cuối của lượt đã biết (`het_luot`) ⇒ về chờ kiểu cuối lượt."""
        return self.het is not None and self.het - GIU_NOI <= n <= self.het + CUA_SO_HET

    @staticmethod
    def _so_nhip_ve(con):
        """Số nhịp đi hết quãng `con` frame theo bước cuối lượt (`_buoc_ve(con, True)`)."""
        k = 0
        while con > 0:
            con -= max(1, -(-con // VE_CUOI_NHIP))
            k += 1
        return k

    def _duong_ve(self, i):
        lo, hi = self.cho
        if lo <= i <= hi:
            return 0
        if i < lo:
            return lo - i
        if not self.vong or i < (hi + self.f1) // 2:
            return i - hi
        return self.f1 - i + 1

    def yeu_cau_gio_tay(self, n):
        with self.khoa:
            self.lenh_tay = n

    def toi(self, n, co_tieng):
        with self.khoa:
            if self.n is None:
                self.n = n - 1
            if n <= self.n:
                return self.bang.get(n, int(self.vt))
            while self.n < n:
                self.n += 1
                self._buoc(self.n, co_tieng(self.n))
                self.bang[self.n] = int(self.vt)
            if len(self.bang) > 6000:
                self.bang = {k: v for k, v in self.bang.items() if k > n - 3000}
            return self.bang[n]

    def _buoc_ve(self, con, cuoi=False):
        """Số frame mỗi nhịp khi đi về chờ lúc IM: 1 (người dẫn gốc), nhân vật khách thì chậm dần
        — xa thì bước dài, gần thì bước 1 — về tới nơi trong vài nhịp. CUỐI LƯỢT (`cuoi`) thì mọi
        nhân vật đi nửa quãng còn lại mỗi nhịp: không câu nào tới nữa, cử động thêm là giả."""
        if cuoi:
            return max(1, -(-con // VE_CUOI_NHIP))
        if not self.ve_nhanh:
            return 1
        return max(1, min(VE_NHANH_TOI_DA, -(-con // VE_NHANH_NHIP)))

    def _buoc(self, n, noi):
        i = int(self.vt)
        lo, hi = self.cho
        if self.g0 <= i <= self.g1:                # ── trong G (đưa tay)
            lui, tien = i - self.g0 + 1, self.g1 - i + 1   # nhịp tới F0 (lùi) / tới F1 (tiến)
            ket = self.het is not None and n <= self.het + GIU_NGAN and \
                self.het - n <= self._so_nhip_ve(min(lui, tien)) + 1
            if ket or (not noi and self._cuoi_luot(n)):
                # Cuối lượt mà tay đang giơ: hạ tay theo hướng GẦN hơn để về chờ đúng lúc
                # tiếng tắt — lùi = phát ngược đoạn giơ tay (tay hạ theo đường đã lên). Bước
                # cuối lượt (nửa quãng/nhịp): làm nốt cử chỉ 125 frame là cử động thừa tới 5s.
                if lui <= tien:
                    b = self._buoc_ve(lui - 1, True)
                    self.vt = max(self.g0, i - b) if i > self.g0 else 0
                else:
                    b = self._buoc_ve(tien - 1, True)
                    self.vt = min(self.g1, i + b) if i < self.g1 else 1
            elif noi or i >= self.nhac - 4:
                self.vt = i + 1 if i < self.g1 else 1      # G120 → F1
            else:
                self.vt = i - 1 if i > self.g0 else 0      # chưa nhấc tay ⇒ lùi về G0 ≈ F0
            if noi and self.noi_tu is None:
                self.noi_tu = n
            if not noi:
                self.noi_tu = None
            return
        if noi and self._dang_ket(n, i):          # ── cuối lượt: đi về chờ, KHÔNG đưa tay
            self.muon_tay = False
            noi = False                            # đi đúng đường «im lặng» bên dưới
        if noi:                                    # ── trong F, đang nói
            if self.noi_tu is None:
                self.noi_tu, self.huong = n, 1
                self.hen_dao = n + random.randint(30, 75)
            if (self.co_tay and not self.muon_tay
                    and (n - self.lenh_tay < 250 or (n - self.noi_tu >= 75 and n >= self.hen_tay))
                    and self._du_cho_tay(n, self._duong_vao_g(i))):
                self.muon_tay = True               # câu ngắn ⇒ chờ câu sau (lệnh còn hiệu lực 10s)
            if self.muon_tay and (i <= 0 or (self.vong and i >= self.f1)) and not self._du_cho_tay(n, 0):
                self.muon_tay = False              # tới cửa G mà câu đã ngắn lại (ước lượng mới) ⇒ thôi
            if self.muon_tay:
                # Vào G theo hướng GẦN hơn (như nguoiDan.ts): nửa đầu F lùi về F0 (G0 ≈ F0),
                # nửa sau tiến tới F120 (F120 ≈ G0). Từ vùng chờ ⇒ tay nhấc sau ~2s thay vì ~6s.
                if i <= 0 or (self.vong and i >= self.f1):
                    self.vt = self.g0
                    self.muon_tay = False
                    self.lenh_tay = -1e9
                    self.hen_tay = n + random.randint(200, 350)
                elif not self.vong or i <= (self.cho[0] + self.f1) // 2:
                    self.vt = i - 1
                else:
                    self.vt = i + 1
                return
            a, b = self.noi
            if i < a:
                self.huong = 1
            elif i >= b:
                self.huong = -1
            elif n >= self.hen_dao:
                self.huong = -self.huong
                self.hen_dao = n + random.randint(30, 75)
            self.vt = i + self.huong
            return
        # ── trong F, im lặng
        self.noi_tu = None
        self.muon_tay = False
        cuoi = self._cuoi_luot(n)
        if lo <= i <= hi:                          # vùng chờ: xuôi–ngược chậm
            v = self.vt + self.huong * self.toc_cho
            if v > hi:
                v, self.huong = hi - (v - hi), -1
            elif v < lo:
                v, self.huong = lo + (lo - v), 1
            self.vt = v
        elif i < lo:
            self.vt = min(lo, i + self._buoc_ve(lo - i, cuoi))
        elif not self.vong or i < (hi + self.f1) // 2:   # nửa đầu (hoặc clip không vòng) ⇒ lùi về chờ
            self.vt, self.huong = max(hi, i - self._buoc_ve(i - hi, cuoi)), -1
        elif i < self.f1:                          # nửa sau ⇒ tiến tới F120 rồi nối F1
            self.vt = min(self.f1, i + self._buoc_ve(self.f1 - i, cuoi))
        else:
            self.vt, self.huong = float(lo), 1


class Doan:
    """Một đoạn audio LIỀN MẠCH (các khối nối đuôi nhau trên đồng hồ trình duyệt).

    ⚠ Gateway đẩy audio LIÊN TỤC suốt cuộc gọi (khối 10ms, cả lúc im) nên một đoạn
    có thể dài bằng cả cuộc gọi. Bản đầu nối mảng + tính lại TOÀN BỘ bản 16 kHz ở
    mỗi khối ⇒ chi phí mỗi khối tăng theo độ dài cuộc gọi; ~1–1,5 phút là event loop
    nghẽn, audio tới chỗ render muộn, mọi frame quá hạn ⇒ miệng đứng yên từ lượt thứ
    3–4. Nay: hạ nhịp TĂNG DẦN (chỉ phần mới), bộ đệm 16 kHz tăng gấp đôi khi đầy,
    và CẮT phần đã render (chỉ giữ ngữ cảnh trái cho whisper) ⇒ chi phí mỗi khối hằng số.
    Chỉ số mẫu 16 kHz ở mọi hàm là TUYỆT ĐỐI (tính từ đầu đoạn).
    """

    def __init__(self, t0):
        self.t0 = t0                         # giây AudioContext của mẫu đầu tiên
        self.n48 = 0                         # tổng số mẫu 48 kHz đã nhận
        self._du = np.zeros(0, np.int16)     # 0–2 mẫu 48k chưa đủ nhóm 3 để hạ nhịp
        self._buf = np.zeros(SR16 * 8, np.float32)
        self._goc = 0                        # chỉ số tuyệt đối của _buf[0]
        self._dai = 0                        # số mẫu hợp lệ trong _buf
        self._khoa = threading.Lock()        # them() ở event loop, lay16() ở thread render
        self.xong = 0                        # số frame đã render
        self.da_do = 0                       # số frame đã đo tiếng
        self.nhan_luc = time.monotonic()
        self.chot = False

    @property
    def t_cuoi(self):
        return self.t0 + self.n48 / SR48

    @property
    def tong16(self):
        return self._goc + self._dai

    def them(self, pcm48):
        x = np.concatenate([self._du, pcm48])
        n = len(x) // 3 * 3
        self._du = x[n:]
        y = x[:n].reshape(-1, 3).astype(np.float32).mean(1) / 32768.0
        with self._khoa:
            self.n48 += len(pcm48)
            # Cắt phần đã render, chừa NGU_CANH_TRAI frame cho whisper.
            giu = max(self._goc, (self.xong - NGU_CANH_TRAI) * MAU16)
            if giu - self._goc > SR16 * 4:
                bo = giu - self._goc
                self._buf[: self._dai - bo] = self._buf[bo : self._dai]
                self._dai -= bo
                self._goc = giu
            can = self._dai + len(y)
            if can > len(self._buf):
                moi = np.zeros(max(can, 2 * len(self._buf)), np.float32)
                moi[: self._dai] = self._buf[: self._dai]
                self._buf = moi
            self._buf[self._dai : can] = y
            self._dai = can
        self.nhan_luc = time.monotonic()

    def lay16(self, a, b):
        """Mẫu 16 kHz tuyệt đối [a, b) (cắt theo phần đang có; bản sao)."""
        with self._khoa:
            a = max(a, self._goc)
            return self._buf[a - self._goc : max(a, min(b, self.tong16)) - self._goc].copy()
