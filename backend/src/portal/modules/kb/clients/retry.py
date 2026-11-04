"""Phân loại mã HTTP đáng thử lại. Thuần, test không cần mạng.

santa-models trả 429 khi queue model layer quá sâu (§2.3) — retry ngay lập tức thì
backpressure chỉ là đổi tên của việc spam.
"""


def should_retry(status: int) -> bool:
    """429 và 5xx thì thử lại. 4xx còn lại là lỗi của chính chỉ thị ta gửi."""
    return status == 429 or 500 <= status < 600
