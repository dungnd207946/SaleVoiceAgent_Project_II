"""Đánh số nguồn [n], kiểm trích dẫn, và payload/id cho các point public_web."""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from portal.modules.kb.web.contracts import (
    DIGEST_REGION,
    MAX_DIGEST_ITEMS,
    MAX_DOSSIER_ITEMS,
    POINT_CARD,
    POINT_DIGEST,
    POINT_DOSSIER,
    Item,
    Page,
    Source,
)
from portal.modules.kb.web.locate import place_labels
from portal.modules.kb.web.normalize import norm_project, project_labels

_NS = uuid.NAMESPACE_URL
_CITE = re.compile(r"\[(\d{1,3})\]")
# "[2, 3]", "[2; 3]", "[2-4]" → "[2][3]…" trước khi kiểm số — không thì số toàn cục còn nguyên trong text
_MULTI_CITE = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})+)\]")
_MAX_RANGE = 10
MAX_SOURCE_CHARS = 4000
MAX_CARD_LOCATION = 4
_VN = ZoneInfo("Asia/Ho_Chi_Minh")
# dòng ngày ghi + (tuỳ chọn) dòng tiêu đề `[...]` ngay sau — cả hai do code thêm lúc ghi
_WRITTEN = re.compile(r"\(Cập nhật \d{2}/\d{2}/\d{4}\)\n(?:\[([^\n]*)\]\n)?")


def strip_written(text: str) -> str:
    """Bỏ dòng đầu `(Cập nhật dd/mm/yyyy)` và dòng tiêu đề đi kèm; dòng không khớp đúng mẫu thì giữ."""
    while m := _WRITTEN.match(text):
        text = text[m.end() :]
    return text


def with_written(text: str, written_at: datetime, header: str = "") -> str:
    head = f"[{' '.join(header.split())}]\n" if header.strip() else ""
    return f"(Cập nhật {written_at.astimezone(_VN):%d/%m/%Y})\n{head}{strip_written(text)}"


def searchable(text: str) -> str:
    """Chữ đem embed: tiêu đề (tên, địa danh, loại) + nội dung — bỏ dòng ngày, giữ tiêu đề."""
    m = _WRITTEN.match(text)
    if not m:
        return text
    body = strip_written(text)
    return f"{m.group(1)}\n{body}" if m.group(1) else body


def point_kind(point_id: str, projects: Sequence[str]) -> str:
    """Loại point suy từ dải id (id mã hoá sẵn loại) — một nguồn sự thật, không để bên gọi tự khai."""
    if point_id in digest_ids(DIGEST_REGION):
        return POINT_DIGEST
    if projects and point_id in (card_id(projects[0]), near_id(projects[0])):
        return POINT_CARD
    return POINT_DOSSIER


def split_cites(text: str) -> str:
    def one(m: re.Match) -> str:
        nums: list[int] = []
        for part in re.split(r"\s*[,;]\s*", m.group(1)):
            ends = [int(x) for x in re.split(r"\s*[–-]\s*", part)]
            lo, hi = ends[0], ends[-1]
            if hi < lo or hi - lo > _MAX_RANGE:
                return m.group(0)
            nums += range(lo, hi + 1)
        return "".join(f"[{n}]" for n in nums)

    return _MULTI_CITE.sub(one, text)


def _id(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def dossier_ids(project_name: str) -> list[str]:
    key = norm_project(project_name)
    return [_id(f"kbweb:dossier:{key}:{i}") for i in range(MAX_DOSSIER_ITEMS)]


def card_id(project_name: str) -> str:
    return _id(f"kbweb:card:{norm_project(project_name)}")


def near_id(project_name: str) -> str:
    """Point "Các dự án gần X" — cùng loại `du_an_lan_can` với thẻ, `projects` = [X]."""
    return _id(f"kbweb:near:{norm_project(project_name)}")


def digest_ids(region: str) -> list[str]:
    key = _norm(region)
    return [_id(f"kbweb:digest:{key}:{i}") for i in range(MAX_DIGEST_ITEMS)]


def source_of(page: Page, names: Mapping[str, str]) -> Source:
    return Source(url=page.url, name=names.get(page.domain, page.domain), published_at=page.published_at)


def renumber(text: str, own_sources: Sequence[Source], index: Mapping[str, int]) -> str:
    def sub(m: re.Match) -> str:
        k = int(m.group(1))
        if 1 <= k <= len(own_sources) and own_sources[k - 1].url in index:
            return f"[{index[own_sources[k - 1].url]}]"
        return ""

    replaced = _CITE.sub(sub, text)
    replaced = re.sub(r"[ \t]+", " ", replaced)  # gộp khoảng trắng ngang liền nhau, GIỮ \n
    replaced = re.sub(r"[ \t]*\n[ \t]*", "\n", replaced)  # bỏ đệm ngang quanh xuống dòng
    replaced = re.sub(r" +([.,;:)])", r"\1", replaced)  # bỏ khoảng trắng ngay trước dấu câu
    return replaced.strip()


def number_sources(
    pages: Sequence[Page], carried: Sequence[Item], names: Mapping[str, str]
) -> tuple[str, list[Source], list[str]]:
    index: dict[str, int] = {}
    sources: list[Source] = []

    def add(src: Source) -> None:
        if src.url not in index:
            sources.append(src)
            index[src.url] = len(sources)

    for it in carried:
        for s in it.sources:
            add(s)
    by_url: dict[str, Page] = {}
    for p in pages:
        add(source_of(p, names))
        by_url[p.url] = p
    texts = [renumber(strip_written(it.text), it.sources, index) for it in carried]
    lines = []
    for n, s in enumerate(sources, 1):
        page = by_url.get(s.url)
        day = s.published_at.date().isoformat() if s.published_at else "không rõ ngày"
        body = page.content_text[:MAX_SOURCE_CHARS] if page else "(nguồn đã dùng trong nội dung hiện có)"
        lines.append(f"[{n}] {s.name} · {day} · {page.title if page else ''}\n{body}")
    return "\n\n".join(lines), sources, texts


def parse_items(
    raw: dict, sources: Sequence[Source], *, projects: Sequence[str], location: Sequence[str], limit: int
) -> list[Item]:
    rows = raw.get("items") if isinstance(raw.get("items"), list) else [raw]
    out: list[Item] = []
    for r in rows:
        if len(out) >= limit:
            break
        if not isinstance(r, dict):
            continue
        text = split_cites(str(r.get("text") or "").strip())
        if not text:
            continue
        cited = {int(x) for x in _CITE.findall(text)}
        cited |= {int(x) for x in (r.get("cites") or []) if str(x).isdecimal()}
        if not cited or any(n < 1 or n > len(sources) for n in cited):
            continue
        # [k] trong text là chỉ số TOÀN CỤC (vào `sources`) — đổi sang chỉ số CỤC BỘ
        # khớp đúng thứ tự của tuple sources sẽ lưu, để [k] luôn == item.sources[k-1].
        order = sorted(cited)
        if not _CITE.search(text):
            # LLM chỉ khai nguồn ở `cites` — gắn [k] cuối mục để mọi mục đều có trích dẫn trong câu
            text = text.rstrip() + " " + "".join(f"[{n}]" for n in order)
        local_index = {sources[n - 1].url: i for i, n in enumerate(order, 1)}
        own_text = renumber(text, sources, local_index)
        out.append(Item(own_text, tuple(sources[n - 1] for n in order), tuple(projects), tuple(location)))
    return out


_EN_ADMIN = re.compile(r"\b(district|province|town|ward|city|commune|street)\b")
_PLACE_SPLIT = re.compile(r",|\s+[-–]\s+")
MAX_PLACE_WORDS = 5


def card_location(raw: dict) -> tuple[str, ...]:
    """Vị trí của dự án trong thẻ: trường `location` cấp gốc của trả lời LLM, tách phần tử ghép nhiều địa danh
    ("xã A, huyện B"), bỏ địa danh tiếng Anh và cụm dài hơn `MAX_PLACE_WORDS` từ (địa chỉ đầy đủ)."""
    v = raw.get("location")
    parts = [part for e in (v if isinstance(v, list) else ()) if isinstance(e, str) for part in _PLACE_SPLIT.split(e)]
    labels = [lb for lb in place_labels(parts) if not _EN_ADMIN.search(lb) and len(lb.split()) <= MAX_PLACE_WORDS]
    return tuple(labels[:MAX_CARD_LOCATION])


NEAR_PREFIX = "Gần các dự án: "
NEAR_TITLE = "Các dự án gần "
_LEAD_WORDS = 45
_SENTENCE_END = re.compile(r"[.!?](?:\[\d{1,3}\])*(?=\s|$)")
_WORD = re.compile(r"\w{3,}")


def split_near(text: str) -> tuple[tuple[str, ...], str]:
    """Tách dòng đầu "Gần các dự án: A, B." của thẻ (do code ghi) khỏi phần LLM viết."""
    if not text.startswith(NEAR_PREFIX):
        return (), text
    line, _, rest = text.partition("\n")
    names = tuple(n.strip() for n in line[len(NEAR_PREFIX) :].rstrip(".").split(",") if n.strip())
    return names, rest


def with_near(text: str, names: Sequence[str]) -> str:
    body = split_near(text)[1]
    names = list(dict.fromkeys(names))
    return f"{NEAR_PREFIX}{', '.join(names)}.\n{body}" if names else body


def is_near_item(item: Item) -> bool:
    return strip_written(item.text).startswith(NEAR_TITLE)


def _lead(text: str) -> str:
    body = split_near(strip_written(text))[1].strip()
    m = _SENTENCE_END.search(body)
    lead = body[: m.end()] if m else body
    words = lead.split()
    return " ".join(words[:_LEAD_WORDS]) + "…" if len(words) > _LEAD_WORDS else lead


def _title(name: str) -> str:
    return name.title() if name == name.lower() else name


def near_item(name: str, place: str, cards: Sequence[Item], location: Sequence[str], project: str) -> Item | None:
    """Point "Các dự án gần X" do code dựng (không qua LLM): mỗi dự án lân cận một câu đầu thẻ kèm nguồn."""
    sources: list[Source] = []
    index: dict[str, int] = {}
    lines = []
    for card in cards:
        if not card.projects or not card.sources:
            continue
        lead = _lead(card.text)
        cited = [k for k in (int(x) for x in _CITE.findall(lead)) if 1 <= k <= len(card.sources)]
        if not cited:
            lead, cited = f"{lead} [1]", [1]
        for k in cited:
            url = card.sources[k - 1].url
            if url not in index:
                sources.append(card.sources[k - 1])
                index[url] = len(sources)
        where = f", {', '.join(card.location[:3])}" if card.location else ""
        # nhắc lại tên X ở mỗi dòng: search "dự án nào gần X" chỉ theo text, point của X phải trội hơn
        # point "gần Y" khác chỉ tình cờ liệt kê X
        lines.append(f"- {_title(card.projects[0])} (gần {name}{where}): {renumber(lead, card.sources, index)}")
    if not lines:
        return None
    head = f"{NEAR_TITLE}{name}" + (f" ({place})" if place else "") + ":"
    return Item("\n".join([head, *lines]), tuple(sources), (project,), tuple(location))


def _words(text: str) -> set[str]:
    return set(_WORD.findall(_CITE.sub(" ", text.lower())))


def carry_dropped(old: Sequence[Item], new: Sequence[Item], limit: int, *, covered: float = 0.5) -> list[Item]:
    """`new` + các mục cũ mà LLM làm rơi: mục cũ có dưới `covered` số từ nằm trong MỌI mục mới."""
    out = list(new)
    bags = [_words(it.text) for it in new]
    for it in old:
        if len(out) >= limit:
            break
        w = _words(it.text)
        if w and all(len(w & b) / len(w) < covered for b in bags):
            out.append(it)
    return out


def payload_of(
    item: Item, updated_at: datetime, *, kind: str, written_at: datetime | None = None, header: str = ""
) -> dict:
    """`text` mở đầu bằng dòng ngày GHI (giờ VN của `written_at`, mặc định `updated_at`), rồi dòng tiêu đề."""
    dates = [s.published_at for s in item.sources if s.published_at]
    return {
        "kind": kind,
        "text": with_written(item.text, written_at or updated_at, header),
        "location": list(place_labels(item.location)),
        "projects": list(project_labels(item.projects)),
        "sources": [
            {"url": s.url, "name": s.name, "published_at": s.published_at.isoformat() if s.published_at else None}
            for s in item.sources
        ],
        "published_at": max(dates).isoformat() if dates else None,
        "updated_at": updated_at.isoformat(),
    }


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def item_from_payload(p: dict) -> Item:
    return Item(
        text=strip_written(str(p.get("text") or "")),
        sources=tuple(Source(s["url"], s["name"], _dt(s.get("published_at"))) for s in p.get("sources") or []),
        projects=tuple(p.get("projects") or []),
        location=tuple(p.get("location") or []),
        updated_at=_dt(p.get("updated_at")),
    )


MAX_ITEM_WORDS = 350


def heading_of(text: str, headings: Sequence[str]) -> str:
    return next((h for h in headings if text.startswith(f"{h}:")), "")


def merge_same_heading(items: Sequence[Item], headings: Sequence[str], max_words: int = MAX_ITEM_WORDS) -> list[Item]:
    """Gộp các mục cùng nhãn chủ đề vào mục đầu tiên của nhãn đó (tới `max_words` từ) — câu hỏi theo chủ đề
    ("có tiện ích gì") phải trúng một mục đủ ý, không phải nhiều mục rải rác."""
    out: list[Item] = []
    for it in items:
        h = heading_of(it.text, headings)
        k = next(
            (
                i
                for i, o in enumerate(out)
                if h and heading_of(o.text, headings) == h and len(o.text.split()) + len(it.text.split()) <= max_words
            ),
            None,
        )
        if k is None:
            out.append(it)
            continue
        first = out[k]
        sources = list(first.sources)
        index = {s.url: i for i, s in enumerate(sources, 1)}
        for src in it.sources:
            if src.url not in index:
                sources.append(src)
                index[src.url] = len(sources)
        body = it.text[len(h) + 1 :].strip()
        text = f"{renumber(first.text, first.sources, index)} {renumber(body, it.sources, index)}"
        out[k] = replace(first, text=text, sources=tuple(sources))
    return out


# Câu tin xấu — hồ sơ và thẻ dùng khi tư vấn, không được nói xấu dự án nào (kể cả dự án lân cận). LLM vẫn
# hay chép "Tuy nhiên, dự án chậm cấp sổ…" dù prompt đã dặn, nên code bỏ thẳng các câu đó.
_NEGATIVE = re.compile(
    r"chậm trễ|chậm tiến độ|chậm cấp|chậm bàn giao|chưa (được )?cấp (sổ|giấy)|chưa nhận được (sổ|giấy)"
    r"|chưa hoàn thành nghĩa vụ|vi phạm|xử phạt|bị phạt|tranh chấp|khởi tố|sai phạm|lừa đảo|xả hàng|cắt lỗ"
    r"|giá giảm|giảm giá sâu|đình chỉ|bị thu hồi|nợ đọng|thanh khoản chậm|đóng băng|kém sôi động|bị đình trệ",
    re.IGNORECASE,
)


def drop_negative(text: str) -> str:
    """Bỏ những câu mang tin xấu (giữ nguyên các câu còn lại và trích dẫn của chúng); rỗng nếu không còn câu nào."""
    pieces = re.split(r"((?<=[.!?])(?:\[\d{1,3}\])*(?:\s+|$)|\n+)", text)
    out: list[str] = []
    for k in range(0, len(pieces), 2):
        sentence = pieces[k]
        tail = pieces[k + 1] if k + 1 < len(pieces) else ""
        if sentence.strip() and not _NEGATIVE.search(sentence):
            out.append(sentence + tail)
        elif "\n" in tail and out:
            out.append("\n")
    return re.sub(r"\n{2,}", "\n", "".join(out)).strip()


def without_negative(items: Sequence[Item]) -> list[Item]:
    """`drop_negative` cho từng mục; mục chỉ toàn tin xấu thì bỏ, mục mất hết `[k]` thì bỏ."""
    out: list[Item] = []
    for it in items:
        text = drop_negative(it.text)
        if text and _CITE.search(text):
            out.append(replace(it, text=text))
    return out
