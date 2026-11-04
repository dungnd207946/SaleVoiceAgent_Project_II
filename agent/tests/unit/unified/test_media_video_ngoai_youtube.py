"""Video KHÔNG phải YouTube phải tới được khách — bug prod 2026-08-25.

Khách xin video dự án ALLUVIA CITY, agent trả «không có». Ba tầng đều đúng:
Postgres có 2 video `published`, Qdrant có đúng 2 point kèm caption, và search TRẢ
VỀ chúng. `_hit_to_item` bỏ cả hai vì `media_url` là link Google Drive — không phải
host YouTube, không có đuôi ảnh. Log prod có đúng ba dòng «cannot render».

Quy mô: 38/93 video của tenant `aina_test` là link Drive (đo cùng ngày).

Bản vá chiều (56a058f) phát `kind: "file"` để không đổi client. TỐI CÙNG NGÀY đổi
sang BIẾN THỂ `url` của `video` (`{url, embed_url?, thumb?, title}` — quyết định sản
phẩm đã chốt với user): đúng nghĩa video, client có lightbox nhúng được player Drive.
Hợp đồng client (portal FE `chatGateway.ts` + AINA) cập nhật cùng đợt; bài cuối vẫn neo
«không bịa `kind` mới» — biến thể mới nằm TRONG `video`, không phải kind thứ năm.
"""

from noble_agent.data import media_data

# Hai video THẬT của ALLUVIA_CITY, nguyên văn.
DRIVE_TIEN_DO = "https://drive.google.com/file/d/1I4OvI-fWVeK-0jdDnNFxxWPihbkUh3yq/view?usp=drive_link"
DRIVE_TONG_QUAN = "https://drive.google.com/file/d/1ELqDCUYvCzfkxo_UwRAEVAOxTut5QHXb/view?usp=drive_link"

# Hợp đồng client (`chatGateway.ts::chuanHoaMedia`) chỉ nhận đúng bốn giá trị này.
KIND_CLIENT_BIET = frozenset({"image", "video", "tour", "file"})


def _hit(url: str, *, caption: str = "T05/2026", content_type: str = "video") -> dict:
    return {"media_url": url, "caption": caption, "content_type": content_type, "id": "x"}


def test_video_drive_khong_con_bi_bo():
    """Tiền đề của cả bản vá: trước đây hàm này trả None cho đúng hit này."""
    item = media_data._hit_to_item(_hit(DRIVE_TIEN_DO))
    assert item is not None
    assert item["url"] == DRIVE_TIEN_DO
    assert item["title"] == "T05/2026"


def test_video_drive_ra_kind_video_bien_the_url():
    """`video` không `video_id` mà có `url` — client nhận theo trường có mặt."""
    item = media_data._hit_to_item(_hit(DRIVE_TONG_QUAN))
    assert item["kind"] == "video"
    assert item["kind"] in KIND_CLIENT_BIET
    assert "video_id" not in item


def test_embed_url_va_thumbnail_drive_suy_tu_id_tep():
    """Client có lightbox nhúng `embed_url` (/preview); tile dùng `thumb`."""
    item = media_data._hit_to_item(_hit(DRIVE_TONG_QUAN))
    assert item["embed_url"] == "https://drive.google.com/file/d/1ELqDCUYvCzfkxo_UwRAEVAOxTut5QHXb/preview"
    assert item["thumb"] == "https://drive.google.com/thumbnail?id=1ELqDCUYvCzfkxo_UwRAEVAOxTut5QHXb&sz=w400"


def test_thumb_drive_KHONG_gac_sau_include_thumb():
    """`include_thumb` nghĩa là «client rơi về `url` được rồi» — đúng với ảnh, sai ở
    đây: link Drive `/view` không hiện được trong `<img>`, nên thumbnail là hình DUY
    NHẤT của thẻ chứ không phải bản đẹp hơn của một hình đã có."""
    item = media_data._hit_to_item(_hit(DRIVE_TIEN_DO), include_thumb=False)
    assert "thumb" in item


def test_youtube_khong_doi_hanh_vi():
    """Nhánh cũ phải nguyên vẹn: 55/93 video của tenant là YouTube."""
    item = media_data._hit_to_item(_hit("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    assert item["kind"] == "video"
    assert item["video_id"] == "dQw4w9WgXcQ"
    assert "url" not in item


def test_link_thu_muc_drive_van_gui_duoc_nhung_khong_thumb_khong_embed():
    """`/drive/folders/<id>` không phải một tệp nên không có thumbnail lẫn player —
    vẫn gửi `video{url}` để khách bấm mở được, thay vì bỏ im lặng như trước."""
    item = media_data._hit_to_item(_hit("https://drive.google.com/drive/folders/1i42ugexarq7"))
    assert item == {"kind": "video", "url": "https://drive.google.com/drive/folders/1i42ugexarq7", "title": "T05/2026"}


def test_host_khac_mang_duong_dan_file_d_khong_bi_doc_thanh_drive():
    """`_parse_drive_id` neo theo HOST, cùng lệ `_parse_youtube_id`."""
    assert media_data._parse_drive_id("https://evil.test/file/d/abc123/view") is None
    assert media_data._parse_drive_id(DRIVE_TIEN_DO) == "1I4OvI-fWVeK-0jdDnNFxxWPihbkUh3yq"


def test_pdf_trong_media_van_bi_bo():
    """Bản vá KHÔNG mở cửa cho mọi thứ: chỉ `content_type == 'video'`."""
    assert media_data._hit_to_item(_hit("https://x.test/a.pdf", content_type="document")) is None


def test_video_drive_tieu_slot_VIDEO_khong_lan_slot_anh():
    """Hai video Drive không được đẩy ảnh ra khỏi kết quả."""
    hits = [_hit(DRIVE_TIEN_DO), _hit(DRIVE_TONG_QUAN)]
    hits += [_hit(f"https://s3.test/anh{i}.jpg", content_type="image") for i in range(6)]
    items = media_data._map_items(hits, max_videos=1)
    assert sum(1 for i in items if i["kind"] == "image") == 6
    assert sum(1 for i in items if i["kind"] == "video") == 1


def test_moi_kind_tra_ve_deu_nam_trong_hop_dong_client():
    """Cổng chống bịa `kind` mới: client bỏ im lặng phần tử có `kind` nó không biết."""
    hits = [
        _hit(DRIVE_TIEN_DO),
        _hit("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        _hit("https://s3.test/a.jpg", content_type="image"),
        _hit("https://kuula.co/share/abc", content_type="tour_360"),
    ]
    for item in media_data._map_items(hits, max_videos=3):
        assert item["kind"] in KIND_CLIENT_BIET
