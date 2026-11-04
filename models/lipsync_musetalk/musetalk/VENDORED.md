# musetalk/ — code chép từ MuseTalk (vendored)

Nguồn: https://github.com/TMElyralab/MuseTalk @ `0a89dec` (2026-10), giấy phép MIT —
xem `../LICENSE-MuseTalk`. MuseTalk KHÔNG có gói PyPI (đã tra `musetalk`/`MuseTalk`/
`muse-talk`: 404) và README của họ chạy code từ trong repo, nên service mang theo đúng
phần cần: **21 file** — đo bằng cách chạy service thật rồi liệt kê module được nạp.
Không có code training, Gradio, script inference gốc.

## Ba chỗ sửa so với bản gốc (giữ ít nhất có thể)

| File | Sửa | Vì sao |
|---|---|---|
| `utils/preprocessing.py` | thiếu `mmpose` ⇒ dùng DWPose bản ONNX (`dw-ll_ucoco_384.onnx`) qua `rtmlib` | mmcv 2.0.x không có build cho torch cu128 / GPU Blackwell (sm_120). Cùng checkpoint, cùng 133 keypoint, cùng bbox cả ảnh |
| `models/unet.py` | `torch.load(..., map_location=self.device)` | bản gốc nạp fp32 thẳng lên GPU ⇒ OOM khi chung card với TTS |
| `utils/face_parsing/resnet.py` | `torch.load(..., weights_only=False)` | torch ≥ 2.6 mặc định `weights_only=True`, file resnet18 chính chủ là định dạng tar cũ |

## Lưu ý
- Code ở đây mở weights bằng đường dẫn TƯƠNG ĐỐI `./models/…` ⇒ `lipsync_server.py`
  `chdir` vào data dir trước khi import.
- Bộ dò mặt S3FD (`utils/face_detection`) bật `cudnn.benchmark` toàn cục; `avatar.py` trả
  lại giá trị cũ sau khi dựng avatar — không thì mỗi phiên gọi chậm 4s ở lô đầu.
- Nằm ngoài ruff (`pyproject.toml` → `exclude`): giữ nguyên văn để dễ so với upstream.
