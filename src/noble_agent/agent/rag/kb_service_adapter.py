"""kb_search backend: Qdrant hybrid over `<tenant>_documents`, in-process.

Fail-closed on a missing collection BEFORE embedding → embed dense + sparse in
parallel → one Qdrant query (server-side RRF), scoped by project_id unioned with
the `__ALL__` sentinel → format into the context string noble_kb expects.

Backend name stays `kb_service` so noble_kb's dispatch is untouched. The dense
embedder is switchable via EMBED_BACKEND (see data/embed_client).

Errors are NOT caught here — noble_kb._query_via_kb_service wraps them → "".
"""

from __future__ import annotations

import asyncio
import logging
import re

from noble_agent.config import settings
from noble_agent.data import embed_client
from noble_agent.data import qdrant_search as qdrant_client
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.kb_service_adapter")

# Named vectors on the `<tenant>_documents` collection (KB collection schema).
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"

_IMG_MD = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_REMINDER_CAP = 6

# Phần 4 của kế hoạch đánh số ảnh (2bbbf9c/0a558da làm 3 phần đầu, phần này bị bỏ sót):
# nếu không có câu này, mô hình đánh số ảnh nhưng chưa bao giờ được BẢO trích số đó vào
# câu trả lời — khách nhận một bức tường chữ cộng vài ảnh không rõ ảnh nào minh hoạ gì.
_IMAGE_CITATION_INSTRUCTION = (
    "Khi câu trả lời cần minh hoạ, hãy nhắc số ảnh đó ngay trong bước tương ứng bằng lời "
    'văn (vd: "xem ảnh 2"); chỉ dùng số đã xuất hiện ở trên, không bịa số mới; không chép '
    "nguyên mốc [ảnh N — ...] vào câu trả lời."
)


def _section(h: dict) -> str:
    """Nhãn mục của một hit.

    Ưu tiên ``section_path`` (list, Portal ghi từ 2026-08-14) và lấy PHẦN TỬ CUỐI; rơi về
    khoá ``section`` cho point cũ. Portal còn ghi cả hai trong một pha rồi bỏ ``section``,
    nên chỗ này phải đọc được cả hai — xem docs/contracts/payload-qdrant.md §6.
    """
    path = h.get("section_path")
    if isinstance(path, list | tuple) and path:
        return str(path[-1]).strip()
    return (h.get("section") or "").strip()


def _number_for(url: str, numbers: dict[str, int]) -> int:
    """Số của một ảnh, cấp mới nếu chưa có. Sổ dùng chung cho CẢ CUỘC trò chuyện.

    Đánh số lại mỗi lượt là hỏng: đo 2026-08-28, 2 trên 3 kịch bản có `ảnh 1` ở lượt sau
    là một tấm khác `ảnh 1` ở lượt trước.
    """
    if url not in numbers:
        numbers[url] = len(numbers) + 1
    return numbers[url]


def _format_kb_hits(hits: list[dict], numbers: dict[str, int] | None = None, *, replace_images: bool = True) -> str:
    """One block per hit, separated by '\\n---\\n'. Only ``text`` is required;
    optional fields (project_name/section_path/updated_at) are omitted when absent.

    URL ảnh KHÔNG BAO GIỜ vào ngữ cảnh khi ``replace_images`` — thay bằng mốc
    `[ảnh N — mô tả]`. Cho mô hình chép URL thật thì 1 trên 3 lượt nó chép sai
    (`127.0.0.1` → `127.00.1`) và ảnh vỡ. ``replace_images=False`` giữ nguyên
    markdown — dùng khi ``items`` (nơi ảnh thật sự tới client) không được gửi, kẻo
    khách nhận một mốc trỏ vào hư không (xem lời gọi ở `query_kb_service_for_noble_kb`).
    """
    numbers = {} if numbers is None else numbers
    blocks: list[str] = []
    substituted = False

    def _replace(m: re.Match) -> str:
        nonlocal substituted
        substituted = True
        return f"[ảnh {_number_for(m.group(2), numbers)} — {m.group(1)}]"

    for h in hits:
        text = (h.get("text") or "").strip()
        if not text:
            continue
        if replace_images:
            text = _IMG_MD.sub(_replace, text)
        name = (h.get("project_name") or "").strip()
        section = _section(h)
        updated = (h.get("updated_at") or "").strip()
        parts: list[str] = []
        if name and section:
            parts.append(f"[{name} › {section}]")
        elif name:
            parts.append(f"[{name}]")
        elif section:
            parts.append(f"[{section}]")
        parts.append(text)
        if updated:
            parts.append(f"(cập nhật: {updated})")
        blocks.append("\n".join(parts))
    out = "\n---\n".join(blocks)
    # Chỉ trả tiền token cho câu dặn dò khi lượt này THẬT SỰ có mốc [ảnh N] — tenant
    # không ảnh không thấy gì thêm.
    if substituted:
        out += "\n---\n" + _IMAGE_CITATION_INSTRUCTION
    return out


def _dinh_kem(hits: list[dict], numbers: dict[str, int] | None = None) -> list[dict]:
    """Tệp/ảnh nguồn của các hit, để client gửi kèm câu trả lời.

    VÌ SAO QUA ``items`` CHỨ KHÔNG NHÉT LINK VÀO ``text``: nhét vào text nghĩa là LLM phải
    CHÉP LẠI đường dẫn khi trả lời, và một URL dài nhiều tham số thì chép sai là chuyện sẽ
    xảy ra. Đi qua ``items`` thì client tự render và LLM không bao giờ chạm vào chuỗi link.
    Cùng lý lẽ đã đưa tour 360 từ collection documents sang media.

    Trùng lặp bị loại theo URL: một tài liệu 12 chunk mà 3 chunk cùng khớp thì khách không
    cần nhận cùng một tệp/ảnh ba lần. Hai nguồn khác nhau chia sẻ chung tập `da_co`:
    `file_public_url` (tệp nguồn đính kèm nguyên văn) và `![alt](url)` trong `text` (ảnh
    nhúng trong nội dung KB, đánh số qua `numbers` — cùng sổ với `_format_kb_hits`).
    """
    numbers = {} if numbers is None else numbers
    ra: list[dict] = []
    da_co: set[str] = set()
    for h in hits:
        url = (h.get("file_public_url") or "").strip()
        if url and url not in da_co:
            da_co.add(url)
            muc = {
                "kind": "file",
                "url": url,
                "label": (h.get("file_name") or _section(h) or "Tài liệu").strip(),
            }
            thumb = (h.get("thumb_url") or "").strip()
            if thumb:
                muc["thumb"] = thumb
            trang = h.get("page") or 0
            if isinstance(trang, int) and trang > 0:
                muc["page"] = trang
            ra.append(muc)
        for alt, img_url in _IMG_MD.findall(h.get("text") or ""):
            if img_url in da_co:
                continue
            da_co.add(img_url)
            ra.append({"kind": "image", "url": img_url, "label": alt, "index": _number_for(img_url, numbers)})
    return ra


def earlier_image_lines(numbers: dict[str, int], *, in_use: set[str]) -> list[str]:
    """Dòng nhắc cho ảnh ĐÃ cấp số nhưng không có trong tài liệu lượt này.

    ⚠️ CHẶN Ở SÁU MỤC GẦN NHẤT. Thả tự do tới 20 mục thì tỉ lệ nhắc ảnh của chính lượt
    đang trả lời tụt còn 2/3 (sổ trống: 3/3) — danh sách dài chen vào ngữ cảnh kéo mô
    hình khỏi tài liệu. Giữ đuôi vì "ảnh lúc nãy" luôn là chuyện gần.
    """
    earlier = sorted((n, u) for u, n in numbers.items() if u not in in_use)
    return [f"- ảnh {n}: {u.rsplit('/', 1)[-1]}" for n, u in earlier[-_REMINDER_CAP:]]


def _du_an_duy_nhat(hits: list[dict]) -> str:
    """Mã dự án nếu MỌI hit (bỏ qua sentinel tenant-wide) thuộc cùng một dự án.

    Rỗng khi hits trống, khi có từ hai dự án trở lên, hoặc khi chỉ có tài liệu
    dùng chung toàn tenant. Chặt là có chủ ý: một câu so sánh nhiều dự án ra hits
    không đồng nhất, và ghim sticky theo dự án nào trong đó cũng là đoán.

    Sentinel `__ALL__` bị bỏ qua chứ không tính là một dự án — brochure dùng chung
    thường lọt vào mọi phép tìm, và tính nó vào là mọi câu hỏi đều hoá "hai dự án".
    """
    ma = {(h.get("project_id") or "").strip() for h in hits}
    ma.discard("")
    ma.discard(qdrant_client.SYSTEM_ANCHOR)
    return next(iter(ma)) if len(ma) == 1 else ""


async def hits_for(query: str, project_filter: str, limit: int) -> list[dict]:
    """Hit thô từ Qdrant: `[{**payload, "id": str, "score": float}]` theo thứ tự RRF.

    Tách ra để `hipporag_kb` lấy đúng seed mà `kb_service` dùng, thay vì một bản sao
    của khối embed+search sẽ lệch vào ngày hợp đồng payload đổi.
    """
    query = (query or "").strip()
    project_filter = (project_filter or "").strip()
    if not query:
        return []

    qdrant_url = settings.qdrant_url
    if not qdrant_url:
        logger.warning("[kb_service_adapter] qdrant_url empty — returning no context")
        return []

    api_key = settings.qdrant_api_key
    collection = qdrant_client.collection_name(current_tenant(), "documents")
    if not await qdrant_client.collection_exists(qdrant_url, api_key, collection):
        logger.info("[kb_service_adapter] collection %s absent — returning no context", collection)
        return []

    dense_vecs, sparse_vecs = await asyncio.gather(
        embed_client.embed_dense([query], side="query"),
        embed_client.embed_sparse([query], side="query"),
    )
    if not dense_vecs or not sparse_vecs:
        logger.warning("[kb_service_adapter] embed returned no vectors — returning no context")
        return []
    sparse = sparse_vecs[0]

    project_codes = [project_filter] if project_filter else []
    min_score = settings.kb_search_min_score
    return await qdrant_client.search_hybrid(
        base_url=qdrant_url,
        api_key=api_key,
        collection=collection,
        prefetches=[
            qdrant_client.DensePrefetch(DENSE_VECTOR, dense_vecs[0]),
            qdrant_client.SparsePrefetch(
                SPARSE_VECTOR,
                sparse.get("indices", []),
                sparse.get("values", []),
            ),
        ],
        limit=limit,
        score_threshold=min_score if min_score > 0 else None,
        filter_=qdrant_client.build_scope_filter(project_codes),
        timeout=settings.qdrant_timeout,
    )


def render(
    hits: list[dict],
    dinh_kem: list[dict] | None,
    du_an: list[str] | None,
    numbers: dict[str, int] | None,
) -> str:
    """Hit -> chuỗi ngữ cảnh, cộng việc đổ `dinh_kem`/`du_an`. Dùng chung với
    `hipporag_kb`: hai formatter là hai hình dạng ngữ cảnh cho cùng một tool."""
    # Mốc `[ảnh N]` và `items` (bồn `dinh_kem`) đi CÙNG NHAU dưới một cờ: một mốc mà
    # ảnh thật không tới client là để lại một tham chiếu rỗng, tệ hơn cả URL thô của
    # trước nhánh này.
    attach = settings.kb_search_attach_source_files
    if dinh_kem is not None and attach:
        dinh_kem.extend(_dinh_kem(hits, numbers))
    if du_an is not None:
        ma = _du_an_duy_nhat(hits)
        if ma:
            du_an.append(ma)
    context = _format_kb_hits(hits, numbers, replace_images=attach)
    if attach and numbers:
        in_use = {u for h in hits for _, u in _IMG_MD.findall(h.get("text") or "")}
        lines = earlier_image_lines(numbers, in_use=in_use)
        if lines:
            context += (
                "\n---\nẢNH ĐÃ NHẮC TRƯỚC ĐÓ (không có trong tài liệu lượt này, "
                "chỉ để tra lại khi khách hỏi về nó):\n" + "\n".join(lines)
            )
    return context


async def query_kb_service_for_noble_kb(
    query: str,
    project_filter: str,
    top_k: int = 5,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    """`dinh_kem` là BỒN CHỨA, không phải giá trị trả về: caller truyền một list và hàm này
    đổ vào đó tệp/ảnh nguồn của các hit.

    Vì sao không đổi kiểu trả về thành tuple: `query_noble_kb` dispatch sáu backend, năm
    trong đó không có khái niệm tệp kèm. Đổi kiểu trả về là sửa cả sáu để phục vụ một.
    """
    hits = await hits_for(query, project_filter, top_k)
    return render(hits, dinh_kem, du_an, numbers)
