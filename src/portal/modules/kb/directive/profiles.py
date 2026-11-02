"""Chọn TÊN profile. Nội dung prompt VLM nay do Portal own (`portal.modules.kb.prompts`)."""

from portal.modules.kb.contracts import MediaDirective, VerticalSpec
from portal.modules.kb.directive.verticals import profiles as profile_names


def caption_profile(vertical: VerticalSpec, category: str) -> str:
    return vertical.caption_profiles.get(category) or vertical.caption_profiles.get(
        "default", profile_names.DEFAULT_CAPTION
    )


def should_index_media(vertical: VerticalSpec, category: str) -> bool:
    """Category ngoài media.visual thì không index, vẫn giữ ở Postgres cho dashboard."""
    return category in vertical.media_visual


def extract_profile(vertical: VerticalSpec, *, body: str, file_url: str | None) -> str | None:
    """Chỉ trích khi body rỗng và có file — trích một lần rồi cache vào body (§4.2b).

    `pypdf` (clients/extract.py) đọc lớp chữ — KHÔNG phải Docling như bản cũ ghi. Và từ
    2026-08-25 mọi PDF đi qua `ocr_markdown`, lớp chữ chỉ còn là đường lùi."""
    if body.strip() or not file_url:
        return None
    return vertical.document_extract.get("pdf_scan")


def resolve_media(
    *,
    workspace_slug: str,
    row: dict,
    vertical: VerticalSpec,
    file_url: str | None,
    thumb_url: str | None = None,
) -> MediaDirective:
    """caption rỗng → gửi None để service sinh; có → gửi đi để service bỏ qua VLM.

    HAI CỘT, THỨ TỰ CỐ ĐỊNH: `caption` (khách gửi qua cổng nạp, hoặc người gõ trong form)
    thắng `caption_auto` (job `kb_caption` sinh bằng VLM). Khách bắt đầu gửi mô tả ảnh
    thật thì bản của họ tự lên trên mà không cần dọn cột kia — xem migration `0936`.
    """
    caption = (row.get("caption") or "").strip() or (row.get("caption_auto") or "").strip()
    return MediaDirective(
        workspace_slug=workspace_slug,
        record_id=int(row["id"]),
        anchor_code=str(row[vertical.media_anchor_col]),
        anchor_name=str(row.get("anchor_name") or ""),
        content_type=row["content_type"],
        category=row["category"],
        media_url=row["media_url"],
        file_url=file_url,
        caption=caption or None,
        caption_profile=caption_profile(vertical, row["category"]),
        thumb_url=thumb_url or row.get("thumb_url") or None,
        status=str(row.get("status") or ""),
        anchor_status=str(row.get("anchor_status") or ""),
    )
