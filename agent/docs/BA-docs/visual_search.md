# media — media search service (:8015)

Hybrid search ảnh/tài liệu dự án: embed query (tiếng Việt) bằng **E5-large (text)** +
**SigLIP2 (visual)**, Qdrant fuse **RRF server-side** trên collection `media_v2`
(named vector `text`+`visual`). Gọi qua HTTP như một cloud vendor — không cần import code.

## Gọi (client)

`POST http://10.50.12.70:8015/search` — header `Authorization: Bearer <SANTA_MODELS_TOKEN>`.

Body:
| field | type | bắt buộc | mặc định | ý nghĩa |
|---|---|---|---|---|
| `query` | string | ✓ | | câu truy vấn tiếng Việt |
| `project_code` | string | ✓ | | lọc 1 dự án, vd `"NPLB"` |
| `category` | string | ✓ | | `tong_quan`/`ngoai_that`/`noi_that`/`tien_ich`/`mat_bang`/`vi_tri`/`phap_ly`/`tien_do` |
| `top_k` | int | | 10 | số kết quả |
| `threshold` | float | | 0.4 | score_threshold nhánh text (`<=0` = tắt) |

Response: `{"hits": [ <hit>, ... ]}` — mỗi `hit` (xếp theo `score` giảm dần):

| field | type | ý nghĩa |
|---|---|---|
| `id` | string | id point trong Qdrant (uuid) |
| `score` | float | điểm RRF (càng cao càng liên quan) |
| `media_url` | string | link ảnh/tài liệu (S3 public) — dùng để hiển thị |
| `thumb_url` | string | poster/thumbnail (video/file); `""` nếu media_v2 không có field này |
| `content_type` | string | `image`/`video`/`file` |
| `project_code` | string | mã dự án của hit |
| `category` | string[] | danh mục (payload là mảng, vd `["mat_bang"]`) |
| `caption` | string | mô tả nội dung media |
| `rel_path` | string | đường dẫn gốc (debug/hiển thị) |

Ví dụ:
```json
{"hits": [
  {"id": "3f9c...", "score": 0.033, "media_url": "https://.../abc.webp", "thumb_url": "",
   "content_type": "image", "project_code": "NPLB", "category": ["tien_ich"],
   "caption": "bể bơi vô cực tầng cao", "rel_path": "NPLB/tien_ich/pool.jpg"}
]}
```

```bash
curl -s -XPOST http://10.50.12.70:8015/search \
  -H "Authorization: Bearer <SANTA_MODELS_TOKEN>" -H 'Content-Type: application/json' \
  -d '{"query":"phối cảnh hồ bơi","top_k":5,"project_code":"NPLB","category":"tien_ich"}'
```

```python
import httpx
r = httpx.post("http://10.50.12.70:8015/search",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json={"query": "mặt bằng căn hộ 2 phòng ngủ", "project_code": "NPLB", "category": "mat_bang", "top_k": 3})
hits = r.json()["hits"]   # mỗi hit: media_url, caption, score, ...
```