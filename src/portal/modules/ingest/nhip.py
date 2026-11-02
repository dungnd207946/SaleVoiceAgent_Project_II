"""Giới hạn tốc độ theo TOKEN — §8 mục 2 của spec cổng nạp.

Token nạp nằm trong hệ thống của BÊN THỨ BA. Mình không xem được cron của họ,
không sửa được vòng lặp của họ, và không gọi điện được lúc 2 giờ sáng. Một job
lỗi bên đó — retry không backoff, cron chồng lượt, một `while True` thiếu điều
kiện thoát — là tải thật đổ vào DB của mọi tenant khác trên cùng cụm.

── ĐẾM REQUEST, KHÔNG ĐẾM BẢN GHI ──────────────────────────────────────────
`TRAN_LO` (500) đã chặn khối lượng MỖI request, nên số request nhân với nó là đã
chặn được tổng công. Đếm bản ghi thì ngược lại: một vòng lặp hỏng gửi lô 1 bản
ghi sẽ chạy được 30.000 lượt/phút trong khi vẫn «dưới hạn mức», và chính SỐ LƯỢT
mới là thứ giết kết nối DB chứ không phải số hàng.

── HAI CỬA, HAI NHỊP ───────────────────────────────────────────────────────
Không gộp làm một, vì hai endpoint khác nhau cả về giá lẫn về nhịp hợp lệ:

    /events    500 bản ghi + một lượt chiếu   ·  chạy LIÊN TỤC theo thay đổi
    /manifest  tới 20.000 mục, một phép so
               trên TOÀN BỘ bảng               ·  chạy HẰNG ĐÊM

Cho `/manifest` cùng nhịp với `/events` là cho phép quét toàn bảng 120 lần mỗi
phút — đúng thứ đắt nhất, ở nhịp mà nghiệp vụ không bao giờ cần.

── ĐẾM THEO BĂM, VÀ ĐẾM TRƯỚC KHI TRA DB ───────────────────────────────────
Băm chứ không phải chuỗi thô: Redis không phải chỗ cho bí mật đi qua, kể cả trong
TÊN key. Cùng lý lẽ `enrollment.service._cho_qua_nhip`.

Trước khi tra DB: nếu không, một máy dò token bắt portal chạy một truy vấn cho
mỗi lần đoán, và chính phép kiểm nhịp lại thành thứ được đếm sau khi hại đã xảy
ra.

⚠️ KHÔNG PHỦ được request KHÔNG kèm token — không có gì để quy trách nhiệm, nên
không có khoá nào để đếm. Chặn dạng đó là việc của tầng vào (WAF/ingress), không
phải của tầng ứng dụng.
"""

from redis.asyncio import Redis

from portal.api.loi import LoiPortal

TIEN_TO = "ingest:nhip:"

CUA_EVENTS = "events"
CUA_MANIFEST = "manifest"


async def cho_qua(redis: Redis, *, bam_token: str, cua: str, so_lan: int, giay: int) -> None:
    """Ném `429` nếu vượt nhịp. Cửa sổ CỐ ĐỊNH, không trượt.

    Cửa sổ trượt chính xác hơn nhưng cần một sorted set và một lượt dọn mỗi
    request. Ở đây mình chặn một job hỏng, không chia băng thông công bằng — sai
    số của cửa sổ cố định (tối đa 2× ở đúng ranh giới) không đổi kết luận nào.

    NGƯỠNG TRONG THÔNG ĐIỆP, và cả số giây còn lại: bên nhận là một adapter do
    người khác viết, và thứ họ cần để sửa là «bao nhiêu là quá nhiều» chứ không
    phải chữ «rate limited». Số giây đi CẢ HAI đường: header `Retry-After`
    (chuẩn HTTP — backoff logic đọc bằng thư viện sẵn có) và trong câu chữ (cho
    người đang đọc log; trước 2026-08-16 câu chữ là đường DUY NHẤT vì
    `LoiPortal` chưa mang được header).
    """
    key = f"{TIEN_TO}{cua}:{bam_token}"
    dem = await redis.incr(key)

    if dem == 1 or await redis.ttl(key) < 0:
        await redis.expire(key, giay)

    if dem > so_lan:
        con = max(await redis.ttl(key), 1)
        raise LoiPortal(
            "RATE_LIMITED",
            429,
            f"Quá {so_lan} request/{_doc_cua_so(giay)} cho token này. Thử lại sau {con} giây.",
            headers={"Retry-After": str(con)},
        )


def _doc_cua_so(giay: int) -> str:
    """`60 → "phút"`. Câu lỗi đọc ra tiếng người, không phải một con số giây."""
    if giay == 60:
        return "phút"
    if giay == 3600:
        return "giờ"
    return f"{giay} giây"
