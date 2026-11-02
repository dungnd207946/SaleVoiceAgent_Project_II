# Worker trả việc khi dừng và phát hiện việc mồ côi

## Vấn đề

Deploy thay container `worker` và `crawl-worker` bất kỳ lúc nào. Việc đang chạy chết theo container cũ, còn
hàng `control.jobs` vẫn ghi `running`. Container mới chỉ thu hồi việc `running` quá ngưỡng kẹt của loại việc:
15 phút (mặc định), 120 phút (`kbweb_project`), 360 phút (`kbweb_run`).

Đo trên dev ngày 07/10: ba lượt «Cập nhật mỗi đêm» bắt đầu 08:32, `crawl-worker` được thay lúc 10:06, ba hàng
nằm `running` tới khi bị thu hồi lúc 14:32 dù không tiến trình nào chạy chúng.

## Thiết kế

Sửa ở lõi (`core/jobs.py`, `worker/__main__.py`), nên cả `worker` và `crawl-worker` cùng được.

1. **Trả việc khi dừng.**
   - Worker bắt `SIGTERM`/`SIGINT` (entrypoint đã `exec` nên Python là PID 1).
   - Huỷ các làn, rồi đưa những việc chính tiến trình này đang giữ về `queued` ngay:
     - `run_after = now()`;
     - **không** tăng `attempts`;
     - chỉ hàng còn `running`.
   - Docker cho 10 giây trước khi giết, một câu UPDATE là đủ.
2. **Nhịp tim từng việc.**
   - Cột mới `control.jobs.heartbeat_at`.
   - Ghi lúc nhận việc, rồi mỗi 30 giây trong lúc handler chạy.
   - Ghi vào DB, không dùng Redis: worker chính cố ý không có `REDIS_URL`.
3. **Thu hồi theo nhịp tim.**
   - Việc `running` có `heartbeat_at` cũ quá 5 phút thì coi là worker đã chết (OOM, máy khởi động lại, bị giết thẳng).
   - Thu hồi như việc kẹt: **có** tăng `attempts`. Một việc tự làm worker chết không được nhặt lại vô hạn.
   - Hàng có `heartbeat_at` NULL (nhận bởi bản cũ) chỉ theo ngưỡng kẹt cũ.
   - Ngưỡng kẹt theo `started_at` giữ nguyên cho việc còn sống nhưng treo.

## Chạy lại có an toàn không

Chạy lại từ đầu, phần đã gọi LLM/Google bị tính tiền lại. Dữ liệu không sai vì các việc ghi đè. Đã đọc kiểm các
việc dễ nghi:

- `kb_provision`: chỉ tạo collection khi chưa có.
- `kb_file_index`: chạy trong giao dịch, bị huỷ thì rollback.
- `kb_doi_co`: đọc trạng thái hiện tại từ DB.
- `kb_doi_nhan`: chỉ thay khi dòng đầu khớp đúng tên cũ.
- `kbweb_run`: bỏ qua bài đã thu.
- `kbweb_project`: viết đè hồ sơ.

## Test

- Bị huỷ giữa handler: việc về `queued`, `attempts` giữ nguyên, `started_at` NULL.
- Việc đã xong trước khi trả: không bị đưa lại hàng đợi.
- Nhịp tim được ghi trong lúc handler chạy.
- Mất nhịp tim quá 5 phút: thu hồi, `attempts + 1`, kể cả khi chưa tới ngưỡng kẹt.
- Nhịp tim còn mới và chưa quá ngưỡng kẹt: không thu hồi.
- `heartbeat_at` NULL: giữ nguyên hành vi cũ.
