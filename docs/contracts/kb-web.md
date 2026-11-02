# Hợp đồng `/api/v1/kb-web/*` — màn «Dữ liệu ngoài» (FE)

> **Đối tượng:** repo `odyssey-portal-frontend` (`features/kb-web/`). **Sở hữu:** `src/portal/modules/kb/web/`
> (`router.py` · `schemas.py` · `service.py`). Đổi hình dạng ở `schemas.py` mà không sửa tài liệu này là để tài
> liệu nói dối. Copy tay sang repo FE, không có job CI nào so hai bên.

Quyền: mọi `GET` cần `kb_web.read`; mọi `POST`/`PATCH`/`PUT`/`DELETE` cần `kb_web.write` (`0972_kb_web_actions`:
đọc cho Quản trị · Biên tập · Người xem; ghi cho Quản trị · Biên tập). Lỗi theo khuôn chung `{"error": {...}}`,
mã `KB_WEB_*` liệt kê cuối tài liệu. Mọi mốc thời gian là ISO 8601 có múi giờ (UTC); FE tự đổi sang giờ VN.

Dữ liệu là CỦA RIÊNG workspace (`tenant_data.*`, RLS): nguồn, chủ đề, lịch, trang thô, hồ sơ
(`<tenant_id>_public_web` trên Qdrant). Tenant mới nhận bộ mặc định (16 nguồn, 18 chủ đề, 3 lịch) qua trigger.

## Tổng quan

`GET /kb-web/overview` → `OverviewOut`

| Trường | Nghĩa |
|---|---|
| `soDuAn` · `soDuAnCoHoSo` | dự án published · số có ít nhất một mục hồ sơ |
| `hoSoCuNhat` | mốc `updated_at` nhỏ nhất trong mọi mục hồ sơ (null = chưa có) |
| `baiBayNgay` · `baiBaMuoiNgay` | bài `ok` nạp trong 7 / 30 ngày |
| `soNguonBat` | nguồn đang bật |
| `groundingThang` / `groundingTran` | lượt tìm Google (Gemini) đã dùng tháng này / trần tháng |
| `trinhDuyetHomNay` / `trinhDuyetTran` | lượt mở trình duyệt hôm nay / trần ngày |
| `dangChay` · `loiGanDay` | `JobOut[]` — việc `queued`/`running` (≤20) · việc `failed` gần nhất (≤5) |
| `lanKeTiep` | mốc gần nhất trong `next_run_at` của các lịch đang bật |

`GET /kb-web/worker` → `{dangChay: bool}` — crawl-worker có đang chạy không (dấu sống Redis, TTL 3 phút). FE dùng để
cảnh «Chưa có tiến trình thu thập» khi lượt thử nguồn / chạy ngay không tiến triển.

`JobOut`: `{id, loai: 'kbweb_run'|'kbweb_project'|'kbweb_probe', mode, duAn?, duAnTen?, url?, tinhTrangNguon?, nguoiTen?, trangThai: queued|running|success|failed, nguoi,
taoLuc, batDau?, ketThuc?, soLuong, thongDiep, chiPhi?}`. `nguoi` = `lich` (tự động) hoặc user id.
`chiPhi` (VND, chuỗi decimal) = tiền của lượt chạy trong sổ billing; chỉ có ở `/kb-web/jobs*` khi người xem
có `billing.read`, còn lại `null`.

## Nguồn

- `GET /kb-web/sources` → `NguonOut[]`: `{id, domain, ten, bat, macDinh, cheDo: http|browser, theoDoi: news|living,
  baiBayNgay, tinhTrang: ok|blocked|no_feed|timeout|private|null, ghiChu, thuLuc}`. Mặc định xếp trước, rồi theo id.
- **Thử nguồn (bất đồng bộ — chạy ở crawl-worker, nơi có trình duyệt):**
  1. `POST /kb-web/sources/probe` `{url}` → `202 {token, jobId}`.
  2. Poll `GET /kb-web/sources/probe/{token}` → `{trangThai: dang_chay|xong|loi, ketQua?}`. Dừng khi khác
     `dang_chay`, hoặc sau ~60 s thì hiện gợi ý xem `GET /kb-web/worker`.
  3. `ketQua: ThuNguonOut` = `{trangThai: ok|blocked|no_feed|timeout|private, ghiChu, soBai, soTrangThu, soTrangDoc,
     daCo, deXuat?}`; `deXuat: {domain, ten, cheDo, theoDoi, rss[], sitemapIndex, newsSitemaps[], categoryPages[],
     articlePattern}`. `ok`/`no_feed` thêm được; `blocked`/`timeout`/`private` thì không (`deXuat` có thể null).
     `daCo = true` ⇒ domain đã có trong danh sách, không thêm nữa.
- `POST /kb-web/sources` body `ThemNguonIn` = `deXuat` (+ `ten` người dùng sửa) + `tinhTrang` (`ok`|`no_feed`) +
  `ghiChu` → `201 NguonOut`. Trùng domain ⇒ `409 KB_WEB_NGUON_DA_CO`.
- `PATCH /kb-web/sources/{id}` `{bat?, ten?}` → `NguonOut`.
- `DELETE /kb-web/sources/{id}` → `204`, kể cả nguồn mặc định (bộ mặc định chỉ seed lúc tạo tenant, không chép lại).
- `POST /kb-web/sources/{id}/retry` → `202 {token, jobId}` (thử lại, poll như trên); sau khi `xong`, FE gọi
  `POST /kb-web/sources/{id}/probe-result` body = `ketQua` để ghi `tinhTrang`/`ghiChu`/`cheDo` vào hàng nguồn → `NguonOut`.

## Chủ đề

- `GET /kb-web/topics` → `ChuDeOut[]`: `{id, code, ten, nhan, moTa, cauTim[], tuKhoa[], bat, macDinh, vaoHoSo, thuTu}`.
  `nhan` = nhãn mở đầu mục trong hồ sơ (chủ đề mặc định có nhãn riêng, đổi `ten` không đổi `nhan`); `vaoHoSo=false`
  (chủ đề «Dự án lân cận») chỉ dùng để tìm bài.
- `POST /kb-web/topics/draft` `{ten, moTa}` → `{cauTim[], tuKhoa[]}` — LLM soạn câu tìm bài (2–4 câu, mỗi câu có
  `{project}` hoặc `{location}`). `503 KB_WEB_LLM_CHUA_CAU_HINH` khi môi trường chưa có khoá.
- `POST /kb-web/topics` `{ten, moTa?, cauTim[1..4], tuKhoa[]?}` → `201 ChuDeOut`. Trần 20 chủ đề ⇒
  `409 KB_WEB_CHU_DE_QUA_GIOI_HAN`; câu thiếu biến ⇒ `422 KB_WEB_CHU_DE_CAU_TIM_THIEU_BIEN`.
- `PATCH /kb-web/topics/{id}` `{bat?, ten?, moTa?, cauTim?, tuKhoa?}` → `ChuDeOut`.
- `DELETE /kb-web/topics/{id}` → `204`, kể cả chủ đề mặc định.
  Đang có lượt chờ ⇒ `409 KB_WEB_DANG_CHAY`.

## Lịch và giới hạn

- `GET /kb-web/schedules` → `{lich: LichOut[3], gioiHan: {groundingThang, trinhDuyetNgay, ngayHoi}}`.
  `LichOut`: `{mode: nightly|weekly|rebuild, bat, gio: 'HH:MM' (giờ VN), ngayTrongTuan[] (0=T2…6=CN, chỉ weekly),
  soThang: 1..12 — viết lại mỗi N tháng (rebuild), ngayTrongChuKy: d1|d15|first_sunday (rebuild), latCat 1..7 (weekly),
  lanGanNhat, lanKeTiep}`.
- `PUT /kb-web/schedules` body `{lich: LichIn[], gioiHan?}` (chỉ cần gửi nhịp muốn đổi) → cùng hình `GET`.
  `lanKeTiep` tính ngay theo giờ VN. Weekly bật mà không ngày ⇒ `422 KB_WEB_LICH_THIEU_NGAY`; rebuild thiếu
  chu kỳ ⇒ `422 KB_WEB_LICH_THIEU_CHU_KY`.
- `POST /kb-web/schedules/{mode}/run` → `202 JobOut` («Chạy ngay»). Đang chờ/chạy ⇒ `409 KB_WEB_DANG_CHAY`.

Mode: `nightly` = Cập nhật mỗi đêm (crawl nguồn → thử lại trang chặn bằng trình duyệt → trang cố định → bản tin →
dọn → cập nhật hồ sơ dự án đang được hỏi); `weekly` = Tìm sâu (Google cho chủ đề thiếu + thẻ lân cận, 1/latCat số
dự án mỗi lượt); `rebuild` = Viết lại toàn bộ hồ sơ.

## Dự án

- `GET /kb-web/projects` → `DuAnOut[]`: `{code, ten, soMuc, soChuDe, capNhatLuc, dangChay, viecGanNhat?: JobOut}`.
  `soChuDe` = số dòng của `muc` bên dưới, `soMuc` = số dòng có nội dung và không bị ẩn.
- `GET /kb-web/projects/{code}` → `{code, ten, muc: [{nhan, ten, noiDung, nguon: [{url, ten, ngay}], capNhatLuc, an}],
  mucAn: string[], bai: [{url, tieuDe, domain, ngayDang, thuLuc, loai}], dangChay}`. `muc` có đúng một dòng cho
  mỗi chủ đề đang bật của `GET /kb-web/topics`, cùng thứ tự (không có «Tổng quan» — agent vẫn đọc mục đó); `ten` là tên chủ đề như tab Chủ đề,
  `nhan` là nhãn mục trong hồ sơ (dùng cho `POST …/items`); `noiDung` rỗng = chưa có thông tin; «Dự án lân cận» lấy
  từ point "Các dự án gần X". `noiDung` là nguyên `text` (FE bỏ hai dòng đầu nếu muốn — xem `public-web.md`);
  `bai` ≤100 bài liên quan mới nhất; `loai=true` = đã loại khỏi hồ sơ.
- `POST /kb-web/projects/{code}/refresh` `{mode: init|rebuild}` → `202 JobOut`. `init` = cập nhật (giữ mục cũ),
  `rebuild` = viết lại từ đầu. Đang chờ ⇒ `409`.
- `POST /kb-web/projects/{code}/items` `{nhan, an}` → `204` — ẩn/hiện một mục (áp từ lượt viết kế tiếp; FE có thể
  ẩn ngay trên màn theo `an`).
- `POST /kb-web/projects/{code}/pages` `{url, loai}` → `204` — loại/dùng lại một bài.

## Nhật ký chạy

- `GET /kb-web/jobs?limit=50&ngay=7` → `JobOut[]` của `ngay` ngày gần nhất (mặc định 7, tối đa 90), mới nhất trước (`kbweb_run`, `kbweb_project`, `kbweb_probe`; lượt kiểm tra nguồn mang `url`).
- `GET /kb-web/jobs/{id}` → `JobOut` (dùng để poll một lượt vừa bấm).
- Mỗi lượt `kbweb_run`/`kbweb_project` (kể cả lượt lỗi) và mỗi lần «Tạo cách tìm bài» ghi chi phí vào
  `billing.usage_events`: `purpose = channel = 'kb_web'`, `session_id = 'kbweb:<job id>'`
  (`'kbweb-draft:<uuid>'`), `seq` = số lần thử. Xem `usage-billing.md` §8.

## Mã lỗi

`KB_WEB_NGUON_KHONG_TON_TAI` 404 · `KB_WEB_NGUON_DA_CO` 409 · 
`KB_WEB_NGUON_KHONG_HOP_LE` 422 · `KB_WEB_THU_KHONG_TON_TAI` 404 · `KB_WEB_CHU_DE_KHONG_TON_TAI` 404 ·
 `KB_WEB_CHU_DE_QUA_GIOI_HAN` 409 · `KB_WEB_CHU_DE_THIEU_CAU_TIM` 422 ·
`KB_WEB_CHU_DE_CAU_TIM_THIEU_BIEN` 422 · `KB_WEB_CHU_DE_CAU_TIM_SAI` 422 · `KB_WEB_CHU_DE_SOAN_HONG` 502 ·
`KB_WEB_LLM_CHUA_CAU_HINH` 503 · `KB_WEB_LICH_TRUNG` 422 · `KB_WEB_LICH_THIEU_NGAY` 422 ·
`KB_WEB_LICH_THIEU_CHU_KY` 422 · `KB_WEB_MODE_KHONG_HOP_LE` 422 · `KB_WEB_DANG_CHAY` 409 ·
`KB_WEB_DU_AN_KHONG_TON_TAI` 404 · `KB_WEB_VIEC_KHONG_TON_TAI` 404.

## Nhật ký hoạt động (`control.audit_log`)

`kb_web.nguon_them` · `kb_web.nguon_sua` · `kb_web.nguon_xoa` · `kb_web.chu_de_them` · `kb_web.chu_de_sua` ·
`kb_web.chu_de_xoa` · `kb_web.lich_sua` · `kb_web.gioi_han_sua` · `kb_web.chay` · `kb_web.ho_so_sua` — đã có trong
`contracts/audit-actions.json`.
