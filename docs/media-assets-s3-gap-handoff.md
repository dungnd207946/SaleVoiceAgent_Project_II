# Bàn giao: ảnh dự án thiếu trên S3 (chặn tính năng Luna gửi ảnh)

**Ngày:** 2026-07-12 · **Cho:** team CMS / media (`santa-agent-cms`) · **Từ:** hotline-agent

> ## ✅ ĐÃ XỬ LÝ (CMS · 2026-07-12)
> **Đã copy 745 object** từ `noble-agent-data` → `noble-cms-media` (đúng key, giữ nguyên content-type),
> 0 lỗi. Verify: 745/745 có mặt trong `noble-cms-media`; endpoint CMS trả 200/206 + `content-type: image/*`
> cho các id trước đây 404. **Không sửa code/config, không restart.**
>
> **Đính chính chẩn đoán:** KHÔNG phải 2.275 ảnh hỏng. `project_media` có 2.447 doc (đều có `storage_key`);
> byte nằm ở **2 bucket rời nhau hoàn toàn** (0 id trùng — cms-media 1.707 vs agent-data 1.759):
> - **1.702 doc** (1.560 `anh` + 120 `file` + 22 `video`) — byte ở `noble-cms-media` → **vẫn 200, không hỏng**.
> - **745 doc** (715 `anh` + 23 `file` + 7 `video`) — byte ở `noble-agent-data` → CMS 404. **Đây là phần đã fix.**
> - **0 doc mất hẳn.** 4 ảnh test lúc bàn giao tình cờ đều rơi vào nhóm 745.
>
> ⚠️ **ĐỪNG dùng option 2 (đổi `AGENT_S3_BUCKET` → bucket khác):** hai bucket rời nhau, đổi sẽ làm
> **1.702 doc đang chạy bị 404**. Cách đúng là copy byte vào `noble-cms-media` (đã làm).

## Triệu chứng
Luna (hotline) đã có tính năng `send_via_app` trả `items[]` ảnh/video và app/demo render đúng
(đã verify). **Nhưng ảnh dự án hiện lên là ảnh vỡ** — không tải được.

## Nguyên nhân (đã chẩn đoán, hệ thống)
`project_media` trong Mongo `noble_agent` có **đầy đủ metadata** (`storage_key`, `mime`,
kích thước thật 0.8–28 MB) nhưng **byte ảnh KHÔNG có trong bucket S3 `noble-cms-media`**:

```
GET https://agent-cms.noble.vn/api/v1/projects/media/<id>/download?inline=true
  → 302 → https://noble-cms-media.s3.amazonaws.com/agent/<id>/v1/<file>
  → 404  <Error><Code>NoSuchKey</Code>...
```
Thử 4 ảnh khác nhau → **đều `NoSuchKey`** → metadata đã import vào Mongo nhưng file thật
chưa được upload lên bucket này (hoặc đang ở bucket/tài khoản khác, hoặc đã bị xoá).

Số liệu kho: `anh` = 2.275 · `video` (mp4) = 29 · `file` (pdf) = 143 · `link`/YouTube = **0**.

## Cần làm (CMS/media)
1. **Upload byte ảnh** lên bucket `noble-cms-media` (region `ap-southeast-1`) đúng key
   `agent/{media_id}/v1/{ten_file}` (khớp `storage_key` trong doc `project_media`).
   **HOẶC** nếu byte đang ở bucket/tài khoản khác → sửa `AGENT_S3_BUCKET` (+ `AGENT_S3_*` creds)
   trong `.env` deploy CMS trỏ đúng chỗ rồi restart CMS.
2. **Kiểm chứng:** `curl -IL "https://agent-cms.noble.vn/api/v1/projects/media/<id>/download?inline=true"`
   → phải ra `200` + `content-type: image/*`.

→ Sau khi S3 có file, **hotline + app chạy nguyên, không cần sửa code** (cùng URL đó trả 200).

## Follow-up (tùy chọn, SAU khi S3 đã có ảnh)
- **Thumbnail nhẹ (render nhanh):** branch CMS `feat/media-web-thumbnails` (commit `c389cb4`) —
  deploy + chạy `backend/scripts/backfill_image_thumbnails.py` (dry-run trước; ~2.275 ảnh).
  Lưu ý: backfill **tải ảnh gốc từ S3** để sinh thumbnail → **phải có byte gốc trên S3 trước**.
- **Video:** client phát **YouTube** (qua `video_id`); từ 2026-08-25 video KHÔNG phải YouTube đi
  biến thể `{url, embed_url?, thumb?}` (Google Drive nhúng được, mp4/Vimeo là thẻ link mở tab mới).
  Muốn có video ngay: thêm media `loai_media=link` + URL YouTube vào `project_media`
  (không đụng S3). Muốn phát mp4: cần thêm player phía client (effort riêng).

## Trạng thái phía hotline (đã xong, không chờ gì)
- `send_via_app → items[]` đã deploy (image `:local`, develop @ merge `fix/agent-improvements`).
- Contract cho app: `docs/api/noblex-app-dev-guide.md` §4 (media) + §3.1 (voice text+media).
