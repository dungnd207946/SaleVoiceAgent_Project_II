# lipsync-musetalk :8020

Lip sync **thời gian thực** cho người dẫn ở tab Voice của portal (`/thu-agent`): nhân vật
mấp máy môi khớp từng âm tiết agent nói, đầu cử động khi nói, thỉnh thoảng đưa tay giới
thiệu, đứng yên khi chờ. Mô hình: [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk)
(MIT) — code mô hình chép vào `musetalk/` vì MuseTalk không có gói PyPI, xem
[musetalk/VENDORED.md](musetalk/VENDORED.md).

| | |
|---|---|
| Client | **trình duyệt** — portal `src/features/platform/avatarLipSync.ts` (không phải agent) |
| GPU | ~4,3 GB VRAM, ~30 fps trên RTX 5060 Ti ⇒ mặc định **một phiên một lúc** (`LIPSYNC_MAX_SESSIONS`, phiên vượt trần bị đóng `1013`) |
| Weights | ~3,9 GB, tải về volume `lipsync_cache` lúc boot đầu (`weights.py`, kiểm SHA-256) |
| UNet | **bản fine-tune tiếng Việt** `NobleX-AI/santa-lipsync-musetalk` (private, cần `HF_TOKEN`) — xem §UNet tiếng Việt |
| Nhân vật | `avatars/nguoi-dan.mp4` — người dẫn Kling của portal (clip stacked-alpha) |

## Cơ chế «dựng avatar một lần»

MuseTalk không dùng thẳng video được: mỗi frame cần vị trí mặt, landmark, latent VAE của
vùng mặt và mặt nạ ghép. Tính chúng mất ~1–2 phút GPU nên chỉ làm **một lần** — và việc đó
**tự động**, không ai phải chạy tay:

```
boot ─► weights.py  : thiếu file nào thì tải từ HF, kiểm SHA-256   (lần đầu ~3,9 GB)
     ─► avatar.py   : SHA-256(avatars/nguoi-dan.mp4) + tham số  ==  /data/avatars/<id>/info.json ?
                       ├─ khớp   ⇒ nạp cache (~10s)
                       └─ lệch/thiếu ⇒ dựng lại: tách F+G + mặt nạ gốc → dò mặt/landmark →
                                       latent → mặt nạ ghép → ghi info.json CUỐI CÙNG
     ─► render frame «miệng khép» cho các tư thế (một lần, cache) → warm-up GPU → mở cổng
```

- Cache nằm trong volume `lipsync_cache` (`/data`) ⇒ sống qua restart / redeploy.
- **Đổi nhân vật** = thay `avatars/nguoi-dan.mp4` (cùng bố cục — xem dưới), commit, CI build
  image mới ⇒ SHA-256 đổi ⇒ boot sau tự dựng lại. Không có bước tay nào.
- Container bị kill giữa lúc dựng ⇒ chưa có `info.json` ⇒ lần sau dựng lại từ đầu.
- Healthcheck `start_period` 20 phút để chừa cho boot đầu (tải weights + dựng).

## UNet tiếng Việt

Từ 2026-10-14 UNet mặc định là MuseTalk V1.5 **fine-tune trên ~3,5 h video tiếng Việt**
(+1,5 h HDTF chống quên). Cùng kiến trúc và định dạng file với `unet.pth` gốc, nên chỉ đổi
nguồn tải. Đo trên người nói chưa có trong train, cùng đường inference với service:

| | V1.5 gốc | Fine-tune |
|---|---|---|
| LSE-C ↑ / LSE-D ↓, audio chéo (như production) | 4.16 / 10.15 | **6.66 / 7.93** |
| LSE-C ↑ / LSE-D ↓, người dẫn `nguoi_dan_FG` | 5.03 / 9.64 | **6.37 / 8.65** |
| LMD miệng ↓ · LPIPS ↓ · SSIM ↑ (tái dựng có GT) | 7.51 · 0.200 · 0.739 | **6.15 · 0.182 · 0.772** |

Quy trình dữ liệu / train / đo: `MuseTalk/vi_finetune/BAO_CAO.md` (ngoài repo này).

- **Đưa weights lên HF** (một lần, PHẢI xong trước khi deploy — thiếu repo là service chết
  ở bước tải, healthcheck bắt):
  ```bash
  hf repos create NobleX-AI/santa-lipsync-musetalk --repo-type model --private
  hf upload NobleX-AI/santa-lipsync-musetalk MuseTalk/models/musetalkV15_vi/unet.pth unet.pth
  ```
  `HF_TOKEN` trong `ODYSSEY_SECRET_MODELS_ENV` phải đọc được repo này (cùng org với
  santa-stt / santa-tts-omnivoice). SHA-256 file: `6db22374…a726244` (đủ trong `weights.py`).
- **Nguồn**: `weights.py` (`UNET_REPO/UNET_FILE/UNET_SHA256`), đổi bằng env
  `LIPSYNC_UNET_{REPO,FILE,SHA256}` — đặt đủ cả ba. Về bản gốc: `TMElyralab/MuseTalk` ·
  `musetalkV15/unet.pth` · `7ebf6c98…b787007` (giá trị đủ trong `weights.py`).
- **Đổi UNet trên máy đã chạy**: không cần bước tay. Mốc `models/musetalkV15/unet.pth.sha256`
  khác ⇒ boot sau tự tải đè; `don_cache_theo_unet` bỏ `im_lang.pkl` + `poster.png` của
  mọi nhân vật có mốc `unet.sha256` khác (render lại ở lần nạp đầu, vài giây). Frame,
  mặt nạ, latent VAE của nhân vật không phụ thuộc UNet nên giữ — **không phải dựng lại
  nhân vật**. Video «nói thử» backend đã lưu lúc tạo nhân vật vẫn là của UNet cũ.

### Bố cục video nhân vật
Clip **stacked alpha** (nửa trên màu đã nhân alpha trên nền đen, nửa dưới mặt nạ), 242
vị trí: 0–120 đoạn F (đứng nói, tay đan), 121–241 đoạn G (đưa tay giới thiệu) — đúng
`DOAN` của portal `nguoiDan.ts`. Mặt phải dò được ở MỌI frame (dựng sẽ dừng nếu không).
Đổi sang clip bố cục khác thì đo lại các mốc `--f-cuoi/--noi-tu/--noi-den/--nhac-tay/
--idle-from/--idle-to` (`lipsync_server.py`) — chúng đánh số theo frame của clip này.

## Nhân vật khách tự tạo (nhiều nhân vật)

Ngoài nhân vật mặc định, portal cho khách tạo người dẫn riêng từ **video tự quay** hoặc
**ảnh → video AI** (phần sinh video nằm ở portal backend). Service này nhận video thường
(có nền) và dựng thành nhân vật dùng được như mặc định:

```
PUT /avatars/<id>/video/chinh (+ /video/tay tuỳ chọn)  →  POST /avatars/<id>/dung
   luồng dựng nền (tuần tự, ~1–2 phút/nhân vật trên 5060 Ti):
   chuẩn hoá (25 fps, ≤ 640k điểm ảnh, F ≤ 8s, G ≤ 5s) → tách nền RVM → đo bố cục tư thế
   (bo_cuc.py) → MuseTalk (dò mặt mọi frame, latent, mặt nạ) → miệng khép + poster → info.json
GET /avatars/<id>  → cho | dang_dung (buoc, tien_do) | san_sang | loi {ma, chi_tiet}
POST /avatars/<id>/xem-truoc {"text"} → mp4 nhân vật nói câu đó (TTS LIPSYNC_TTS_URL, ~1×thời lượng)
WS  /avatar?avatar=<id>  → phiên dùng nhân vật đó (chưa sẵn sàng ⇒ đóng 4404)
```

Chi tiết route: docstring [quan_ly.py](quan_ly.py). Mã lỗi khách sửa được: `VIDEO_HONG`,
`VIDEO_NGAN`, `KHONG_THAY_NGUOI`, `KHONG_THAY_MAT`, `MAT_NHO`; còn lại `LOI_HE_THONG`.

### Chuẩn video nhân vật (để dựng đạt)
- Một người, bán thân, nhìn thẳng, **máy quay đứng yên**, mặt rõ ở MỌI frame, tay không che miệng.
- **Mở đầu 1–2s đứng yên, miệng khép** (thành tư thế chờ), rồi nói tự nhiên. 3–8s là đủ.
- Clip đưa tay (tuỳ chọn): bắt đầu và kết thúc ở tư thế đứng như frame CHỜ của clip chính. Portal
  làm hai lượt: dựng clip nói ⇒ lấy `GET /avatars/<id>/khung_cho.jpg` (frame gốc tại vùng chờ, lưu
  kèm chỉ số trong `khung_cho.json`) ⇒ sinh clip tay với ảnh đó làm khung đầu + cuối ⇒ dựng lại có G:
  clip nói được cắt ĐÚNG tại chỉ số đã lưu nên F0 = G0. Đổi video nói (`PUT video/chinh`) xoá khung chờ.
- Nền bất kỳ (tự tách). Frame cuối giống frame đầu (vd. video AI đặt ảnh đầu = ảnh cuối)
  ⇒ đo được «vòng» ⇒ chuyển động tự nhiên hơn; không thì người luôn lùi về chờ.

Vùng chờ của nhân vật khách: chọn trong 4s đầu cửa sổ có ≥ 90% frame **miệng khép**, rồi yên
nhất (video AI hay nói liên tục mà thân rất yên — chọn theo «yên» thì đứng chờ vẫn mấp máy môi);
phần trước nó bị cắt (đoạn AI chỉnh dáng); frame chờ hiển thị là frame MuseTalk trên âm im lặng
(`BoCuc.cho_goc = False`), không phải frame gốc. Khung hình = khung ảnh/video nguồn — ảnh cắt sát
đỉnh đầu thì nhân vật cũng mất đỉnh đầu (không có bước nào thêm khoảng trống phía trên).

Bố cục tự đo (`bo_cuc.do_bo_cuc`): vùng chờ = cửa sổ yên + khép miệng nhất trong 3s đầu,
dải nói sau đó, nhấc tay = lúc cổ tay (DWPose) lên ≥ 4% khung. Đo thử trên chính clip người
dẫn gốc (ghép lại nền): ra chờ 1–15, nói 21–100, nhấc tay 53 — số đo tay là 1–15/22–100/46.

**RAM**: frames/alpha mở bằng mmap; `LIPSYNC_MAX_AVATARS` (3) nhân vật khách nạp sẵn (LRU).
**Giấy phép**: RobustVideoMatting là GPL-3.0 — tải qua `torch.hub` lúc dựng lần đầu (cache
`/data/torch`), KHÔNG đóng gói trong image. Đổi model tách nền: `LIPSYNC_RVM_REPO/MODEL`.

## Protocol — xem docstring `lipsync_server.py`

Tóm tắt: trình duyệt gửi từng khối PCM agent (48 kHz) kèm **thời điểm nó sẽ phát** trên
đồng hồ AudioContext (đã trễ phát ~1,2s); service trả frame JPEG «stacked alpha» mang đúng
thời điểm đó ⇒ trình duyệt vẽ khi tới giờ, hình và tiếng chung một đồng hồ. Lệnh text:
`het_luot` (agent_done — về tư thế chờ đúng lúc tiếng tắt), `gio_tay` (agent gửi ảnh).

## Xác thực

`ODYSSEY_MODELS_TOKEN` như mọi service. Trình duyệt không đặt được header cho WebSocket
nên service nhận thêm `?token=` trên URL. **Đừng nhét token chung vào bundle portal**:
cho portal gọi qua reverse proxy (nginx của portal) và để proxy gắn token phía server.
Dev local (loopback) để token rỗng = tắt auth.

## Chạy

```bash
# Docker (máy có nvidia-container-toolkit)
docker compose --profile gpu up -d lipsync-musetalk

# Native (máy dev không có toolkit — như tts-omnivoice). Cần ffmpeg trong PATH.
python3.11 -m venv .venv-lipsync && .venv-lipsync/bin/pip install -r lipsync_musetalk/requirements.txt
LIPSYNC_DATA_DIR=$PWD/.lipsync-data .venv-lipsync/bin/python lipsync_musetalk/lipsync_server.py
#   --prepare-only : tải weights + dựng avatar rồi thoát (làm ấm cache trước khi bật)
```

Portal bật lip sync bằng `VITE_AVATAR_WS_URL` (xem `.env.example` của portal).

## Nhiều phiên cùng lúc — `LIPSYNC_MAX_SESSIONS`

Trần là **sức tính**, không phải VRAM: model dùng chung (thêm phiên gần như không tốn
VRAM), nhưng mỗi phiên cần ~25 frame/giây real-time và các phiên xếp hàng trên cùng GPU
(`gpu_lock`). Vượt sức GPU thì **mọi** phiên cùng giật — nên phiên dư bị từ chối `1013`.
Tranh GPU nhẹ thì từng phiên tự chuyển sang render thưa (12,5 fps) thay vì trễ hạn.

Chọn số trên máy deploy bằng phép đo, không đoán:

```bash
# đặt tạm LIPSYNC_MAX_SESSIONS đủ lớn (vd 6) trong .env của deploy rồi up lại, sau đó:
for n in 1 2 3 4; do
  docker exec odyssey-models-lipsync-musetalk-1 python3 do_tai.py -n $n --tts ws://tts-omnivoice:8016/tts
done
```

Lấy N lớn nhất mà mọi phiên «ĐẠT» kèm tải TTS; «thưa» đã cao (> ~30%) thì lùi một nấc.
Máy dev 5060 Ti: giữ **1** — 2 phiên là cả hai cùng giật và OmniVoice chậm theo.

## Kiểm thử

- `pytest tests/test_lipsync_musetalk.py` — logic thuần (tư thế, bộ đệm audio), không GPU.
- Render cần GPU + weights: đo bằng client giả lập phát audio thật đúng nhịp, đếm frame
  về trước hạn. Số đo 2026-10-06 (5060 Ti): câu 25s có OmniVoice sinh câu song song —
  đủ frame, sớm hơn hạn ≥ 0,15s; không tải — sớm ≥ 0,35s.

## Bẫy đã gặp (đọc trước khi sửa)

- **Gateway stream audio LIÊN TỤC** (khối 10ms, cả lúc im) ⇒ một đoạn có thể dài bằng cả
  cuộc gọi. Xử lý phải tăng dần (`tu_the.Doan`); bản đầu tính lại cả đoạn mỗi khối và lip
  sync chết từ lượt thứ 3–4.
- **TTS chạy chung GPU** ⇒ render có lúc < 25 fps. Khi sắp trễ service render cách một frame
  (12,5 fps) thay vì để trình duyệt bỏ cả loạt — thưa còn hơn đơ.
- **S3FD bật `cudnn.benchmark`** khi dựng avatar ⇒ `avatar.py` trả lại; không thì lô đầu
  mỗi phiên mất 4s.
