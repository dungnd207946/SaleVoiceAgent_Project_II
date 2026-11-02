"""Hằng số và kiểu dùng chung của gói kb/web. Không logic."""

from dataclasses import dataclass
from datetime import datetime

COLLECTION = "public_web"
KIND_PROJECT = "kbweb_project"
KIND_RUN = "kbweb_run"
"""Một lượt theo lịch (đêm/tuần/dựng lại) của MỘT tenant — payload `{mode, slices}`."""
KIND_PROBE = "kbweb_probe"
KIND_PURGE = "kbweb_purge"
"""Dọn hồ sơ + thẻ của MỘT dự án khỏi `<tenant>_public_web` (dự án đổi tên, gỡ công bố, bị xoá)."""
"""Thử một nguồn người dùng gõ — payload `{url, token}`; kết quả JSON vào Redis `kbweb:probe:<tenant>:<token>`."""
PROBE_RESULT_TTL_SEC = 3600

MODE_NIGHTLY = "nightly"
MODE_WEEKLY = "weekly"
MODE_REBUILD = "rebuild"
MODE_INIT = "init"
MODES = (MODE_NIGHTLY, MODE_WEEKLY, MODE_REBUILD, MODE_INIT)
SCHEDULE_MODES = (MODE_NIGHTLY, MODE_WEEKLY, MODE_REBUILD)

MAX_DOSSIER_ITEMS = 25
MAX_DIGEST_ITEMS = 30
DIGEST_REGION = "toan_quoc"

# khoá `kind` của payload public_web — giá trị tiếng Việt cho bên đọc dễ hiểu
POINT_DOSSIER = "ho_so_du_an"
POINT_CARD = "du_an_lan_can"
POINT_DIGEST = "ban_tin_thi_truong"

PROFILE_TAG = "web_tag"
PROFILE_DOSSIER = "web_dossier"
PROFILE_CARD = "web_card"
PROFILE_DIGEST = "web_digest"
PROFILE_GROUNDING = "web_grounding"

JOB_SESSION_PREFIX = "kbweb:"
"""`billing.usage_events.session_id` của một lượt chạy = tiền tố + id job."""
PROFILE_TOPIC_DRAFT = "web_topic_draft"

FOUND_SITEMAP = "sitemap"
FOUND_RSS = "rss"
FOUND_GROUNDING = "grounding"

STATUS_OK = "ok"
STATUS_IRRELEVANT = "irrelevant"
STATUS_FAILED = "fetch_failed"
STATUS_NEEDS_BROWSER = "needs_browser"


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    name: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    domain: str
    title: str
    published_at: datetime | None
    fetched_at: datetime | None
    content_text: str
    projects: tuple[str, ...]
    location: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Tags:
    relevant: bool
    projects: tuple[str, ...]
    location: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Item:
    text: str
    sources: tuple[Source, ...]
    projects: tuple[str, ...]
    location: tuple[str, ...]
    updated_at: datetime | None = None
