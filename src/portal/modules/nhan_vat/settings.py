"""Cấu hình module nhân vật — env prefix `NHAN_VAT_` (đọc `.env`, cùng nếp `kb/settings.py`).

NHÀ CUNG CẤP SINH VIDEO TỪ ẢNH chọn bằng `NHAN_VAT_VIDEO_PROVIDER` — đổi nhà cung cấp là
đổi env + restart worker, không đổi code:

    (rỗng)  tắt «tạo từ ảnh» — FE chỉ còn «upload video» (GET /nhan-vat/cau-hinh báo vậy)
    kling   API chính chủ Kling (JWT từ access key + secret key)
    fal     fal.ai queue API — một khoá dùng được NHIỀU model (Kling, Veo, Hailuo…):
            đổi `NHAN_VAT_FAL_MODEL` là đổi model
    wan     Alibaba Model Studio (DashScope) — họ model Wan. `wan2.7-*` dùng giao thức mới
            (`input.media` first_frame + last_frame); `wan2.6` trở xuống dùng giao thức cũ
            (`input.img_url`, chỉ frame đầu). Khoá đọc từ `NHAN_VAT_WAN_API_KEY` HOẶC
            `MODEL_STUDIO_API_KEY` (cùng tên biến khách đang có cho chat).
    gia     giả lập cho dev/test: trả video ở `NHAN_VAT_GIA_VIDEO` (đường dẫn file)

Tạo-từ-ảnh LUÔN CHỈNH DÁNG: clip nói (`PROMPT_NOI_CHINH_DANG`) đưa người trong ảnh về dáng
người dẫn chuẩn, KHÔNG gửi khung cuối (= ảnh gốc, tức dáng chưa chuẩn). Clip đưa tay sinh SAU
lần dựng đầu, từ KHUNG CHỜ service lipsync đã chọn (`GET …/khung_cho.jpg`) làm cả khung đầu lẫn
khung cuối (`*_TAIL`) ⇒ G0 = G_cuối = khung chờ = F0 sau khi lipsync cắt đoạn chuyển dáng ⇒ mối
nối đoạn nói ↔ đoạn đưa tay liền mạch (xem jobs._tay, lipsync_musetalk/README §Chuẩn video).
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Prompt viết cho MỘT việc: người dẫn đứng giới thiệu dự án bất động sản, gần như bất động.
# Service lipsync chỉ thay vùng MIỆNG theo giọng agent — mọi cử động đầu/vai của clip gốc lặp lại
# suốt cuộc gọi. Rút từ bốn vòng thử với Wan (2026-10-08, người dùng chốt):
#   • đầu: KHÔNG nhắc tới gật — mọi cách tả «gật nhẹ/micro-nod» Wan vẫn gật rõ (đo: mũi dao động
#     10–28‰ chiều cao khung mỗi 0,4s). Tả đầu như tượng/người dẫn bản tin: khoá cứng, mắt nhìn
#     thẳng ống kính; KHÔNG dùng từ «natural/expressive» (Wan hiểu là được cử động đầu);
#   • hai đoạn theo THỜI GIAN: giây 0,5–2 ĐỨNG IM LẶNG, môi khép rồi mới nói ⇒ service lipsync lấy
#     ~0,1s (3 frame, `dung_avatar.CHO_SO_FRAME`) yên nhất trong đoạn đó làm đứng chờ bằng frame
#     GỐC (`bo_cuc.mieng_khep`); frame MuseTalk lúc im lặng môi hơi hé. Phần nói phải nói THẬT
#     nhưng nhẹ: MuseTalk lấy chính frame gốc làm tham chiếu khuôn miệng (mím môi cả clip ⇒ khẩu
#     hình mở hẹp); há to thì cơ cổ căng, nổi gân (đo 0,10–0,14);
#   • chỉnh dáng: vào dáng NGAY trong ~0,5s rồi giữ — lipsync tự cắt đoạn trước điểm vào dáng.
# Câu đầu khoá máy quay (model ưu tiên mệnh đề đứng đầu). prompt ≤ 800, negative ≤ 500 ký tự (Wan).
PROMPT_NOI_CHINH_DANG = (
    "Fixed camera on a tripod, locked-off waist-up shot, no camera movement, no zoom. Starting from the "
    "photo, within the first half second the presenter settles into a standard stance: upright, facing "
    "the camera, both hands gently clasped at waist height; then the pose never changes. Same face, "
    "hair, outfit, background. The head and neck are completely steady and locked in place for the entire "
    "video: no nodding, no tilting, no "
    "turning, no swaying, no forward or backward movement, eyes fixed on the lens. From 0.5 to 2 seconds "
    "the presenter is silent, lips gently closed "
    "in a natural, pleasant neutral expression, with relaxed mouth corners and no visible smile. "
    "Then the presenter talks softly while keeping the head perfectly still: only lips and jaw move "
    "slightly, mouth never wide open. "
    "Neck relaxed and smooth as in the photo, no tendons or veins. Body motionless."
)
# Clip đưa tay: khung chờ là ảnh bán thân CHẬT (người ~70% bề ngang, mỗi bên trống ~15% — đo
# 2026-10-09) và máy quay khoá + khung đầu = khung cuối ⇒ model không lùi máy được. Duỗi tay ngang
# tầm ngực cần thêm ~13–17% bề ngang ⇒ tay ra khỏi khung (nv-ac93: 49/125 frame chạm mép). Nên
# tả một cử chỉ GỌN bằng câu khẳng định cụ thể (khuỷu tay sát sườn, cẳng tay mở chéo xuống, bàn
# tay không vượt quá vai) — câu cấm kiểu «keep the hand visible» Wan tuân thủ kém.
PROMPT_TAY = (
    "Fixed camera, locked-off waist-up shot, no zoom. The presenter faces the camera, hands clasped in front. "
    "Only the hand on the left side of the image moves; the other hand rests still at the waist. "
    "A small, compact open-palm presenting gesture, like a concierge politely indicating something: "
    "the elbow stays tucked against the side of the body, only the forearm swings outward and slightly forward "
    "toward screen-left, at waist height, palm open and facing up. "
    "The hand stays close to the body, never farther out than the shoulder, with clear empty space between the hand "
    "and the edge of the image. "
    "About 2 seconds to open, a short hold, then about 2 seconds back to the clasped pose. "
    "Head, shoulders and torso stay still."
)
PROMPT_TRANH = (
    "head movement, nodding, head bobbing, head turning, head tilting, head shaking, chin lifting, "
    "looking away, eye darting, wide open mouth, exaggerated mouth movement, teeth showing broadly, "
    "neck veins, neck tendons, strained neck, swaying, shoulder movement, shrugging, leaning, hands "
    "moving after start, big smile, laughing, camera movement, zoom, pan, cut, scene change, "
    "distorted face, deformed hands, extra fingers, extra people, text, subtitles, watermark, blur"
)


class NhanVatEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NHAN_VAT_", extra="ignore", populate_by_name=True)

    # ── service lipsync-musetalk (odyssey-models): API quản lý :8021 ──
    lipsync_url: str = "http://lipsync-musetalk:8021"
    models_token: str = ""
    """ODYSSEY_MODELS_TOKEN của odyssey-models (rỗng = service tắt auth, chỉ dev loopback)."""

    # ── sinh video từ ảnh ──
    video_provider: str = ""
    tao_clip_tay: bool = True
    """Sinh thêm clip đưa tay (gấp đôi chi phí API) — nhân vật biết giơ tay giới thiệu. Clip sinh
    từ khung chờ SAU lần dựng đầu rồi dựng lại (thêm vài phút + một lượt GPU); hỏng thì bỏ."""
    thoi_luong_s: int = 5
    """Độ dài clip NÓI. Service lipsync chỉ dùng 8 giây đầu (`dung_avatar.F_TOI_DA_S`) ⇒ đặt quá
    8 là trả tiền cho phần bị cắt. Kling chỉ có 5|10, Wan 2.7 nhận 2–15, Wan 2.1/2.2 cố định 5."""
    thoi_luong_tay_s: int = 5
    """Độ dài clip ĐƯA TAY. Service chỉ dùng 5 giây đầu (`G_TOI_DA_S`) — clip dài hơn thì động
    tác HẠ TAY ở cuối bị cắt mất ⇒ nối về tư thế đứng bị giật. Giữ 5."""
    prompt_noi_chinh_dang: str = PROMPT_NOI_CHINH_DANG
    prompt_tay: str = PROMPT_TAY
    prompt_tranh: str = PROMPT_TRANH
    le_ngang_anh: float = 0.12
    """Nhân vật TẠO TỪ ẢNH: nới ảnh sang mỗi bên chừng này × bề ngang trước khi sinh clip nói, để
    tay có chỗ khi đưa ra giới thiệu (`nha_cung_cap.chua_le_ngang`). 0 = tắt. Nới nhiều thì người
    nhỏ đi trong khung 720P (mặt ít điểm ảnh hơn cho MuseTalk) — 0,12 ⇒ khung rộng ×1,24."""
    cat_dau_anh_s: float = 1.2
    """Nhân vật TẠO TỪ ẢNH: service lipsync không dùng frame nào trước mốc này của video AI. Model
    «chỉnh dáng» (từ dáng trong ảnh sang dáng người dẫn) trong ~0,75–1s đầu; bộ dò vào dáng của
    lipsync chỉ nhìn cổ tay nên có lúc không cắt (đo 2026-10-09) ⇒ nhân vật nhảy dáng trên sân
    khấu. 0 = tắt. Video khách tự quay không áp."""
    timeout_phut: int = 30
    """Nhà cung cấp chưa xong sau chừng này phút ⇒ lỗi TAO_VIDEO_QUA_LAU (khách thử lại)."""

    kling_base_url: str = "https://api-singapore.klingai.com"
    kling_access_key: str = ""
    kling_secret_key: str = ""
    kling_model: str = "kling-v2-1"
    kling_mode: str = "pro"
    kling_tail: bool = True
    """Gửi `image_tail` (= ảnh gốc). Model/mode không hỗ trợ thì tắt — API sẽ báo lỗi tham số."""

    fal_key: str = ""
    fal_model: str = "fal-ai/kling-video/v2.1/pro/image-to-video"
    fal_tail_field: str = "tail_image_url"
    """Tên trường ảnh cuối của model đang chọn (rỗng = model không có ⇒ không gửi)."""

    # ── Wan (Alibaba Model Studio / DashScope) — tài liệu: help/en/model-studio/
    #    image-to-video-general-api-reference (2.7) · legacy image-to-video-api-reference ──
    wan_api_key: str = Field(default="", validation_alias=AliasChoices("NHAN_VAT_WAN_API_KEY", "MODEL_STUDIO_API_KEY"))
    wan_base_url: str = Field(
        default="https://dashscope-intl.aliyuncs.com",
        validation_alias=AliasChoices("NHAN_VAT_WAN_BASE_URL", "MODEL_STUDIO_API_BASE"),
    )
    """Chỉ lấy ORIGIN: dán nguyên `…/compatible-mode/v1` (base của chat) vẫn đúng — API video
    là API gốc `/api/v1/…`, KHÔNG có ở chế độ tương thích OpenAI. Khoá + base + model phải CÙNG
    VÙNG (Singapore = dashscope-intl; workspace riêng `https://{WorkspaceId}.ap-southeast-1.
    maas.aliyuncs.com`)."""
    wan_model: str = "wan2.7-i2v-2026-04-25"
    wan_resolution: str = "720P"
    """2.7: 720P | 1080P (mặc định của API là 1080P — đắt hơn, mà service lipsync thu về
    ≤ ~640k điểm ảnh nên 1080P chỉ tốn tiền). Model cũ: theo bảng của từng model."""
    wan_tail: bool = True
    """2.7: gửi `last_frame` = ảnh gốc (clip khép vòng). Model cũ không có ⇒ bỏ qua."""

    gia_video: str = ""
    gia_video_tay: str = ""


def get_env() -> NhanVatEnv:
    return NhanVatEnv()
