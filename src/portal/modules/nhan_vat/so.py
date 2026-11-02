"""Hằng số module nhân vật (người dẫn lip sync do workspace tự tạo)."""

import re

TOI_DA_MOI_WORKSPACE = 10
"""Mỗi nhân vật chiếm ~1 GB cache trên service lipsync (GPU dùng chung) — giới hạn mềm."""

VIDEO_MAX_BYTE = 100 * 1024 * 1024
ANH_MAX_BYTE = 10 * 1024 * 1024
LOAI_VIDEO = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
LOAI_ANH = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

CAU_DEMO = (
    "Xin chào, tôi là trợ lý ảo của quý khách. Rất vui được hỗ trợ quý khách hôm nay.",
    "Quý khách cần tìm hiểu thông tin gì, cứ hỏi tôi nhé, tôi sẽ trả lời ngay.",
    "Cảm ơn quý khách đã quan tâm. Hẹn gặp lại quý khách lần sau!",
)
CAU_TOI_DA = 300
NEN_XEM_TRUOC = "#eef1f5"

# Thăm dò (giây): nhà cung cấp sinh video mất vài phút; dựng trên lipsync ~1–2 phút.
CHO_NHA_CUNG_CAP_S = 15
CHO_DUNG_S = 5
LOI_TAM_TOI_DA = 20
"""Số lượt liên tiếp không gọi được service (lipsync/nhà cung cấp) trước khi bỏ cuộc."""

KIND_BUOC = "nhan_vat.buoc"
KIND_DON = "nhan_vat.don_lipsync"

MA_AVATAR = re.compile(r"^nv-[0-9a-f]{32}$")

HUONG_DAN_LOI: dict[str, str] = {
    # mã từ service lipsync (bo_cuc.LoiDung / dung_avatar)
    "VIDEO_HONG": "Không đọc được video. Hãy xuất lại thành MP4 (H.264) rồi tải lên.",
    "VIDEO_NGAN": "Video quá ngắn — cần ít nhất 3 giây người nói trước máy quay.",
    "KHONG_THAY_NGUOI": "Không tách được người khỏi nền. Quay rõ người, bán thân, ánh sáng đủ.",
    "KHONG_THAY_MAT": (
        "Có đoạn không thấy rõ mặt. Mặt phải luôn nhìn về máy quay, không bị tay hay vật che, không quay đi chỗ khác."
    ),
    "MAT_NHO": "Mặt quá nhỏ trong khung hình. Hãy quay gần hơn (bán thân, mặt chiếm ~1/5 chiều cao).",
    "THIEU_VIDEO": "Thiếu video chính.",
    "LOI_HE_THONG": "Lỗi hệ thống khi dựng nhân vật. Hãy thử lại; nếu vẫn lỗi, báo quản trị.",
    # mã của module này
    "TAO_VIDEO_LOI": "Dịch vụ tạo video từ ảnh báo lỗi. Thử ảnh khác (rõ mặt, bán thân, nhìn thẳng).",
    "TAO_VIDEO_QUA_LAU": "Dịch vụ tạo video từ ảnh không phản hồi kịp. Hãy thử lại.",
    "CHUA_CAU_HINH_AI": "Chưa cấu hình dịch vụ tạo video từ ảnh.",
    "MAT_KET_NOI": "Không kết nối được dịch vụ dựng nhân vật. Hãy thử lại sau ít phút.",
}
