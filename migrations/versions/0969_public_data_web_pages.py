"""public_data.web_pages — bài web công khai do gói kb/web crawl về, dùng chung mọi tenant.

Không có tenant_id nên không có RLS: đây là dữ liệu công khai (sitemap/RSS/grounding
của web bên ngoài), không phải dữ liệu nghiệp vụ của một tenant. Chỉ tiến trình crawl
(qua `portal_api`) đọc và ghi.

`found_via`/`status` là danh sách ĐÓNG (khác `escalations.reason_kind` ở `0968` —
ở đó tập giá trị do agent quyết; ở đây do chính gói `kb/web` quyết, cùng codebase).

Revision ID: 0969_public_data_web_pages
Revises: 0968_escalations_lead
"""

from alembic import op

revision = "0969_public_data_web_pages"
down_revision = "0968_escalations_lead"
branch_labels = None
depends_on = None

_DDL = """
CREATE SCHEMA IF NOT EXISTS public_data;

CREATE TABLE IF NOT EXISTS public_data.web_pages (
    url             text PRIMARY KEY CHECK (url <> ''),
    source_url      text NOT NULL DEFAULT '',
    domain          text NOT NULL CHECK (domain <> ''),
    title           text NOT NULL DEFAULT '',
    published_at    timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    last_checked_at timestamptz NOT NULL DEFAULT now(),
    content_text    text,
    content_hash    text NOT NULL DEFAULT '',
    found_via       text NOT NULL CHECK (found_via IN ('sitemap', 'rss', 'grounding')),
    status          text NOT NULL CHECK (status IN ('ok', 'irrelevant', 'fetch_failed', 'needs_browser')),
    projects        text[] NOT NULL DEFAULT '{}',
    location        text[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS web_pages_projects_gin ON public_data.web_pages USING gin (projects);
CREATE INDEX IF NOT EXISTS web_pages_location_gin ON public_data.web_pages USING gin (location);
CREATE INDEX IF NOT EXISTS web_pages_published_idx ON public_data.web_pages (published_at);
CREATE INDEX IF NOT EXISTS web_pages_fetched_idx ON public_data.web_pages (fetched_at);
CREATE INDEX IF NOT EXISTS web_pages_hash_idx ON public_data.web_pages (content_hash) WHERE content_hash <> '';

GRANT USAGE ON SCHEMA public_data TO portal_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON public_data.web_pages TO portal_api;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS public_data CASCADE")
