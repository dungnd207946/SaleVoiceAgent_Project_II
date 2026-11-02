"""Cấu hình gói kb/web của MỘT tenant: nguồn đang bật, chủ đề đang bật.

Đọc từ `tenant_data.kbweb_sources`/`kbweb_topics` (tenant tự sửa trên màn «Dữ liệu ngoài»).
"""

from dataclasses import dataclass

import asyncpg

TARGET_PER_TOPIC = 5
# Từ khoá lọc thô bài BĐS khi báo không có chuyên mục trong URL (so trên URL + tiêu đề, không dấu và có dấu).
BDS_KEYWORDS: tuple[str, ...] = (
    "bat-dong-san", "nha-dat", "du-an", "chung-cu", "can-ho", "biet-thu", "lien-ke", "dat-nen", "quy-hoach",
    "ha-tang", "vanh-dai", "cao-toc", "metro", "khu-do-thi", "nha-o", "gia-nha", "dia-oc", "bất động sản",
    "nhà đất", "dự án", "chung cư", "căn hộ", "biệt thự", "liền kề", "đất nền", "quy hoạch", "hạ tầng",
    "vành đai", "cao tốc", "khu đô thị", "nhà ở", "giá nhà", "địa ốc",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class SourceSite:
    domain: str
    name: str
    whitelisted: bool
    fetch_mode: str
    kind: str
    rss: tuple[str, ...]
    sitemap_index: str
    child_hint: str
    news_sitemaps: tuple[str, ...]
    category_pages: tuple[str, ...]
    article_pattern: str
    category_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Topic:
    code: str
    label: str
    keywords: tuple[str, ...]
    queries: tuple[str, ...]
    heading: str = ""
    """Nhãn mở đầu mục hồ sơ ("Tiện ích – Y tế"); rỗng thì dùng `label`."""
    dossier: bool = True
    """False: chủ đề chỉ dùng để TÌM bài, không thành mục hồ sơ (dự án lân cận nằm ở point "Các dự án gần X")."""


@dataclass(frozen=True, slots=True)
class WebConfig:
    sources: tuple[SourceSite, ...]
    topics: tuple[Topic, ...]
    target_per_topic: int = TARGET_PER_TOPIC
    bds_keywords: tuple[str, ...] = BDS_KEYWORDS

    def source_of(self, domain: str) -> SourceSite | None:
        return next((s for s in self.sources if s.domain == domain), None)

    def names_of(self) -> dict[str, str]:
        return {s.domain: s.name for s in self.sources}

    def headings(self) -> tuple[str, ...]:
        """Nhãn mở đầu mục hồ sơ: "Tổng quan" + nhãn từng chủ đề, theo thứ tự chủ đề."""
        return tuple(dict.fromkeys(["Tổng quan", *(t.heading or t.label for t in self.topics if t.dossier)]))

    def excluded_headings(self) -> tuple[str, ...]:
        """Nhãn của chủ đề không thành mục hồ sơ — mục cũ/LLM lỡ viết mang nhãn này bị bỏ."""
        return tuple(t.heading or t.label for t in self.topics if not t.dossier)


def _tup(v) -> tuple[str, ...]:
    return tuple(str(x) for x in (v or []))


def _source(domain, name, fetch_mode, kind, rss, sitemap_index, child_hint, news_sitemaps, category_pages,
            article_pattern, category_paths) -> SourceSite:  # fmt: skip
    return SourceSite(
        domain=str(domain),
        name=str(name),
        whitelisted=True,
        fetch_mode=str(fetch_mode),
        kind=str(kind),
        rss=_tup(rss),
        sitemap_index=str(sitemap_index or ""),
        child_hint=str(child_hint or ""),
        news_sitemaps=_tup(news_sitemaps),
        category_pages=_tup(category_pages),
        article_pattern=str(article_pattern or ""),
        category_paths=_tup(category_paths),
    )


def _topic(code, label, heading, dossier, keywords, queries) -> Topic:
    return Topic(
        code=str(code),
        label=str(label),
        keywords=_tup(keywords),
        queries=_tup(queries),
        heading=str(heading or label),
        dossier=bool(dossier),
    )


async def load_for_tenant(conn: asyncpg.Connection) -> WebConfig:
    """Nguồn + chủ đề ĐANG BẬT của tenant hiện tại (`tenant_conn`), theo thứ tự tạo/`position`."""
    src = await conn.fetch(
        """SELECT domain, name, fetch_mode, kind, rss, sitemap_index, child_hint, news_sitemaps, category_pages,
                  article_pattern, category_paths
             FROM tenant_data.kbweb_sources
            WHERE tenant_id = portal.current_tenant() AND enabled
            ORDER BY id"""
    )
    top = await conn.fetch(
        """SELECT code, label, heading, dossier, keywords, queries
             FROM tenant_data.kbweb_topics
            WHERE tenant_id = portal.current_tenant() AND enabled
            ORDER BY position, id"""
    )
    return WebConfig(sources=tuple(_source(*r) for r in src), topics=tuple(_topic(*r) for r in top))
