"""kb/web theo tenant: trang thô, nguồn, chủ đề, lịch, giới hạn, mục ẩn, bài loại.

`0969` dựng `public_data.web_pages` dùng chung mọi tenant. Người dùng chốt (2026-10-05): mỗi
workspace một kho riêng, kể cả trang thô — tenant tự chọn nguồn, tự thêm chủ đề, tự đặt lịch,
nên bài crawl về cho tenant này không còn là của tenant kia. Bảng mới `tenant_data.web_pages`
có `tenant_id`, PK `(tenant_id, url)`, RLS FORCE như mọi bảng `tenant_data`.

Backfill: hàng `public_data` hiện có là dữ liệu công khai, chép sang MỌI tenant active có ít
nhất một dự án published — dev/UAT không bắt đầu từ kho trống. Rồi `DROP SCHEMA public_data`.

Cấu hình mặc định (16 nguồn, 18 chủ đề, 3 lịch, giới hạn) được seed cho tenant hiện có và cho
tenant mới qua trigger trên `control.tenants` (khuôn `0967`). Bộ mặc định ĐÓNG BĂNG trong file này
— không import `portal.*` (luật migration); `sources.yaml`/`topics.yaml` của gói đã bị bỏ.

Revision ID: 0971_kbweb_theo_tenant
Revises: 0970_hop_nhat_hai_head
"""

from alembic import op

revision = "0971_kbweb_theo_tenant"
down_revision = "0970_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE tenant_data.web_pages (
    tenant_id       text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    url             text NOT NULL CHECK (url <> ''),
    source_url      text NOT NULL DEFAULT '',
    domain          text NOT NULL CHECK (domain <> ''),
    title           text NOT NULL DEFAULT '',
    published_at    timestamptz,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    last_checked_at timestamptz NOT NULL DEFAULT now(),
    content_text    text,
    content_hash    text NOT NULL DEFAULT '',
    found_via       text NOT NULL CHECK (found_via IN ('sitemap', 'rss', 'grounding', 'probe')),
    status          text NOT NULL CHECK (status IN ('ok', 'irrelevant', 'fetch_failed', 'needs_browser')),
    projects        text[] NOT NULL DEFAULT '{}',
    location        text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant_id, url)
);
CREATE INDEX web_pages_projects_gin ON tenant_data.web_pages USING gin (projects);
CREATE INDEX web_pages_location_gin ON tenant_data.web_pages USING gin (location);
CREATE INDEX web_pages_published_idx ON tenant_data.web_pages (tenant_id, published_at);
CREATE INDEX web_pages_fetched_idx ON tenant_data.web_pages (tenant_id, fetched_at);
CREATE INDEX web_pages_hash_idx ON tenant_data.web_pages (tenant_id, content_hash) WHERE content_hash <> '';

CREATE TABLE tenant_data.kbweb_sources (
    id              bigserial PRIMARY KEY,
    tenant_id       text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    domain          text NOT NULL CHECK (domain <> ''),
    name            text NOT NULL DEFAULT '',
    enabled         boolean NOT NULL DEFAULT true,
    origin          text NOT NULL DEFAULT 'custom' CHECK (origin IN ('default', 'custom')),
    fetch_mode      text NOT NULL DEFAULT 'http' CHECK (fetch_mode IN ('http', 'browser')),
    kind            text NOT NULL DEFAULT 'news' CHECK (kind IN ('news', 'living')),
    rss             text[] NOT NULL DEFAULT '{}',
    sitemap_index   text NOT NULL DEFAULT '',
    child_hint      text NOT NULL DEFAULT '',
    news_sitemaps   text[] NOT NULL DEFAULT '{}',
    category_pages  text[] NOT NULL DEFAULT '{}',
    article_pattern text NOT NULL DEFAULT '',
    category_paths  text[] NOT NULL DEFAULT '{}',
    probe_at        timestamptz,
    probe_status    text CHECK (probe_status IN ('ok', 'blocked', 'no_feed', 'timeout', 'private')),
    probe_note      text NOT NULL DEFAULT '',
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, domain)
);

CREATE TABLE tenant_data.kbweb_topics (
    id          bigserial PRIMARY KEY,
    tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    code        text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_]{0,39}$'),
    label       text NOT NULL CHECK (btrim(label) <> ''),
    heading     text NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    keywords    text[] NOT NULL DEFAULT '{}',
    queries     text[] NOT NULL DEFAULT '{}',
    dossier     boolean NOT NULL DEFAULT true,
    enabled     boolean NOT NULL DEFAULT true,
    origin      text NOT NULL DEFAULT 'custom' CHECK (origin IN ('default', 'custom')),
    position    integer NOT NULL DEFAULT 0,
    created_by  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, code)
);

-- weekdays: 0 = thứ Hai … 6 = Chủ nhật (quy ước `date.weekday()`); chỉ lịch `weekly` dùng.
-- every_months/day_rule: chỉ lịch `rebuild` dùng (mỗi N tháng).
-- next_run_at NULL = scheduler tự tính ở lượt kế.
CREATE TABLE tenant_data.kbweb_schedules (
    tenant_id   text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    mode        text NOT NULL CHECK (mode IN ('nightly', 'weekly', 'rebuild')),
    enabled     boolean NOT NULL DEFAULT true,
    at_time     time NOT NULL,
    weekdays    smallint[] NOT NULL DEFAULT '{}',
    every_months smallint CHECK (every_months BETWEEN 1 AND 12),
    day_rule    text CHECK (day_rule IN ('d1', 'd15', 'first_sunday')),
    slices      integer NOT NULL DEFAULT 1 CHECK (slices >= 1 AND slices <= 7),
    last_run_at timestamptz,
    next_run_at timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, mode)
);

CREATE TABLE tenant_data.kbweb_limits (
    tenant_id         text PRIMARY KEY REFERENCES control.tenants(id) ON DELETE CASCADE,
    grounding_monthly integer NOT NULL DEFAULT 1000 CHECK (grounding_monthly >= 0),
    browser_daily     integer NOT NULL DEFAULT 300 CHECK (browser_daily >= 0),
    asked_days        integer NOT NULL DEFAULT 28 CHECK (asked_days >= 1),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant_data.kbweb_hidden_items (
    tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    project_code text NOT NULL,
    heading      text NOT NULL CHECK (heading <> ''),
    hidden_by    text,
    hidden_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, project_code, heading)
);

CREATE TABLE tenant_data.kbweb_page_exclusions (
    tenant_id    text NOT NULL REFERENCES control.tenants(id) ON DELETE CASCADE,
    project_code text NOT NULL,
    url          text NOT NULL CHECK (url <> ''),
    excluded_by  text,
    excluded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, project_code, url)
);
"""

_TABLES = (
    "web_pages",
    "kbweb_sources",
    "kbweb_topics",
    "kbweb_schedules",
    "kbweb_limits",
    "kbweb_hidden_items",
    "kbweb_page_exclusions",
)

# Chép từ public_data: chỉ tenant active có dự án published thật (bỏ sentinel `__ALL__`).
_BACKFILL_PAGES = """
INSERT INTO tenant_data.web_pages
    (tenant_id, url, source_url, domain, title, published_at, fetched_at, last_checked_at,
     content_text, content_hash, found_via, status, projects, location)
SELECT t.id, w.url, w.source_url, w.domain, w.title, w.published_at, w.fetched_at, w.last_checked_at,
       w.content_text, w.content_hash, w.found_via, w.status, w.projects, w.location
  FROM public_data.web_pages w
 CROSS JOIN control.tenants t
 WHERE t.lifecycle = 'active'
   AND EXISTS (SELECT 1 FROM tenant_data.projects p
                WHERE p.tenant_id = t.id AND p.status = 'published' AND p.project_code <> '__ALL__')
"""

# ─── Bộ mặc định — đóng băng từ `kb/web/defaults.py` (đo 29/09/2026); cổng unit so hai bản ────
# fmt: off
# (domain, name, fetch_mode, kind, rss, sitemap_index, child_hint, news_sitemaps, category_pages,
#  article_pattern, category_paths)
_SOURCES = (
    ('cafef.vn', 'CafeF', 'http', 'news', ['https://cafef.vn/bat-dong-san.rss'], 'https://cafef.vn/sitemap.xml', '-{y}-{m}-', ['https://cafef.vn/google-news-sitemap.xml'], [], '', []),  # noqa: E501
    ('vnexpress.net', 'VnExpress', 'http', 'news', ['https://vnexpress.net/rss/bat-dong-san.rss'], '', '', [], [], '', []),  # noqa: E501
    ('dantri.com.vn', 'Dân trí', 'http', 'news', ['https://dantri.com.vn/rss/bat-dong-san.rss'], '', '', ['https://dantri.com.vn/google-news-sitemap.xml'], [], '', ['/bat-dong-san']),  # noqa: E501
    ('baoxaydung.vn', 'Báo Xây dựng', 'http', 'news', ['https://baoxaydung.vn/rss/bat-dong-san.rss'], 'https://baoxaydung.vn/sitemap.xml', '-{y}-{m}-', [], [], '', []),  # noqa: E501
    ('vneconomy.vn', 'VnEconomy', 'http', 'news', ['https://vneconomy.vn/dia-oc.rss'], '', '', ['https://vneconomy.vn/sitemap/google-news.xml'], [], '', []),  # noqa: E501
    ('thanhnien.vn', 'Thanh Niên', 'http', 'news', ['https://thanhnien.vn/rss/kinh-te/dia-oc.rss'], 'https://thanhnien.vn/sitemap.xml', '-{y}-{m}-', [], [], '', []),  # noqa: E501
    ('tuoitre.vn', 'Tuổi Trẻ', 'http', 'news', ['https://tuoitre.vn/rss/nha-dat.rss'], '', '', ['https://tuoitre.vn/sitemaps/latest-news.rss'], [], '', []),  # noqa: E501
    ('vietnamnet.vn', 'VietNamNet', 'http', 'news', ['https://vietnamnet.vn/bat-dong-san.rss'], '', '', ['https://vietnamnet.vn/sitemap-news.xml'], [], '', []),  # noqa: E501
    ('cafeland.vn', 'CafeLand', 'http', 'news', [], '', '', [], ['https://cafeland.vn/tin-tuc/'], '^https://cafeland\\.vn/tin-tuc/.+-\\d+\\.html$', []),  # noqa: E501
    ('batdongsan.com.vn', 'Batdongsan', 'http', 'news', [], '', '', [], ['https://wiki.batdongsan.com.vn/tin-tuc'], '^https://(wiki\\.)?batdongsan\\.com\\.vn/tin-tuc/[a-z0-9.-]+-\\d{5,}$', ['/tin-tuc/']),  # noqa: E501
    ('reatimes.vn', 'Reatimes', 'http', 'news', [], '', '', ['https://reatimes.vn/sitemaps/googlenews.ashx'], [], '', []),  # noqa: E501
    ('nhipsongkinhdoanh.vn', 'Nhịp sống kinh doanh', 'http', 'news', [], '', '', [], ['https://nhipsongkinhdoanh.vn/hashtag/bat-dong-san-191'], '^https://nhipsongkinhdoanh\\.vn/[a-z0-9-]+-\\d+\\.htm$', []),  # noqa: E501
    ('baochinhphu.vn', 'Báo Chính phủ', 'http', 'news', [], '', '', [], ['https://baochinhphu.vn/kinh-te.htm'], '^https://baochinhphu\\.vn/.+-\\d+\\.htm$', []),  # noqa: E501
    ('hanoi.gov.vn', 'Cổng thông tin Hà Nội', 'http', 'living', [], '', '', [], [], '', []),
    ('quyhoach.hanoi.vn', 'Quy hoạch Hà Nội', 'http', 'living', [], '', '', [], [], '', []),
    ('savills.com.vn', 'Savills', 'http', 'living', [], '', '', [], [], '', []),
)

# (code, label, heading, dossier, keywords, queries)
_TOPICS = (
    ('road', 'Đường bộ', 'Hạ tầng giao thông – Đường bộ', True, ['đường', 'đại lộ', 'cao tốc', 'vành đai', 'quốc lộ', 'nút giao'], ['hạ tầng giao thông đường bộ quanh {project}', '{location} đường vành đai cao tốc tiến độ']),  # noqa: E501
    ('bridge', 'Cầu và vượt sông', 'Hạ tầng giao thông – Cầu', True, ['cầu', 'vượt sông'], ['cầu mới gần {location} tiến độ', '{project} cầu kết nối']),  # noqa: E501
    ('transit', 'Giao thông công cộng', 'Hạ tầng giao thông – Giao thông công cộng', True, ['metro', 'đường sắt đô thị', 'brt', 'xe buýt'], ['metro đường sắt đô thị {location}', 'tuyến xe buýt {location}']),  # noqa: E501
    ('travel_time', 'Thời gian di chuyển', 'Vị trí và thời gian di chuyển', True, ['phút', 'km', 'trung tâm', 'sân bay'], ['{project} cách trung tâm bao nhiêu km', 'từ {location} đến sân bay Nội Bài mất bao lâu', 'vị trí {project} kết nối giao thông']),  # noqa: E501
    ('education', 'Giáo dục', 'Tiện ích – Giáo dục', True, ['trường', 'mầm non', 'tiểu học', 'thcs', 'thpt', 'đại học'], ['trường học gần {location}', 'trường quốc tế {location}']),  # noqa: E501
    ('healthcare', 'Y tế', 'Tiện ích – Y tế', True, ['bệnh viện', 'phòng khám', 'trạm y tế'], ['bệnh viện gần {location}', 'bệnh viện đa khoa {location}']),  # noqa: E501
    ('retail', 'Thương mại', 'Tiện ích – Thương mại', True, ['trung tâm thương mại', 'siêu thị', 'chợ', 'aeon', 'vincom'], ['trung tâm thương mại siêu thị gần {location}']),  # noqa: E501
    ('leisure', 'Cảnh quan và giải trí', 'Tiện ích – Cảnh quan và giải trí', True, ['công viên', 'hồ', 'sân golf', 'khu vui chơi'], ['công viên hồ sân golf gần {location}']),  # noqa: E501
    ('employment', 'Việc làm và hành chính', '', True, ['khu công nghiệp', 'khu công nghệ cao', 'trụ sở', 'hành chính'], ['khu công nghiệp khu công nghệ cao gần {location}']),  # noqa: E501
    ('zoning', 'Quy hoạch', '', True, ['quy hoạch', 'phân khu', 'lên quận', 'đô thị vệ tinh', 'sáp nhập'], ['quy hoạch {location} mới nhất', '{location} lên quận quy hoạch đô thị', '{project} quy hoạch 1/500']),  # noqa: E501
    ('area_development', 'Dự án lớn trong khu vực', '', True, ['khởi công', 'đầu tư', 'dự án lớn', 'động lực'], ['dự án hạ tầng lớn khởi công {location}', 'hạ tầng mới quanh {project} khởi công']),  # noqa: E501
    ('nearby_projects', 'Dự án lân cận', '', False, ['dự án', 'khu đô thị', 'chủ đầu tư'], ['dự án bất động sản gần {project}', 'dự án khu đô thị {location}']),  # noqa: E501
    ('price_trend', 'Mặt bằng giá', '', True, ['giá', 'triệu/m2', 'tỷ', 'tăng giá', 'thanh khoản'], ['giá nhà đất {location} hiện nay', 'giá bán {project}', '{project} giá chuyển nhượng thứ cấp', 'giá thuê căn hộ {project}']),  # noqa: E501
    ('project_news', 'Tin về dự án', 'Tin về dự án và tiến độ', True, ['mở bán', 'bàn giao', 'tiến độ', 'ra mắt', 'giải thưởng'], ['{project} tin tức mới nhất', '{project} tiến độ bàn giao', '{project} mở bán đợt mới', '{project} chủ đầu tư công bố']),  # noqa: E501
    ('onsite_amenities', 'Tiện ích nội khu', '', True, ['tiện ích', 'bể bơi', 'clubhouse', 'công viên nội khu'], ['{project} tiện ích nội khu', '{project} quy mô thiết kế mặt bằng']),  # noqa: E501
    ('offsite_amenities', 'Tiện ích ngoại khu', '', True, ['tiện ích ngoại khu', 'tiện ích xung quanh', 'liên kết vùng'], ['{project} tiện ích ngoại khu', 'tiện ích xung quanh {location}']),  # noqa: E501
    ('legal', 'Pháp lý dự án', 'Pháp lý', True, ['giấy phép xây dựng', 'sổ hồng', 'pháp lý', 'phê duyệt', 'chủ trương đầu tư'], ['{project} pháp lý giấy phép xây dựng', '{project} sổ hồng cấp sổ']),  # noqa: E501
    ('investor', 'Chủ đầu tư', '', True, ['chủ đầu tư', 'nhà phát triển', 'năng lực', 'dự án đã bàn giao'], ['chủ đầu tư {project} là ai', '{project} chủ đầu tư các dự án đã bàn giao']),  # noqa: E501
)
# fmt: on


# Mô tả hiện ở màn «Dữ liệu ngoài» (cột Mô tả của bảng Chủ đề).
_TOPIC_DESCRIPTIONS = {
    "road": "Đường, cao tốc, vành đai và nút giao kết nối dự án.",
    "bridge": "Cầu và tuyến vượt sông gần dự án, tiến độ xây dựng.",
    "transit": "Metro, đường sắt đô thị, BRT và xe buýt quanh khu vực.",
    "travel_time": "Khoảng cách và thời gian di chuyển tới trung tâm, sân bay.",
    "education": "Trường mầm non, phổ thông, đại học và trường quốc tế gần dự án.",
    "healthcare": "Bệnh viện, phòng khám quanh khu vực.",
    "retail": "Trung tâm thương mại, siêu thị và chợ gần dự án.",
    "leisure": "Công viên, hồ, sân golf và khu vui chơi gần dự án.",
    "employment": "Khu công nghiệp, khu công nghệ cao và trụ sở hành chính lân cận.",
    "zoning": "Quy hoạch phân khu, lên quận, đô thị vệ tinh của khu vực.",
    "area_development": "Dự án hạ tầng và đầu tư lớn đang triển khai trong khu vực.",
    "nearby_projects": "Các dự án bất động sản khác gần dự án.",
    "price_trend": "Giá bán, giá thứ cấp và thanh khoản của dự án và khu vực.",
    "project_news": "Tin mở bán, tiến độ, bàn giao và giải thưởng của dự án.",
    "onsite_amenities": "Tiện ích nội khu, quy mô và thiết kế của dự án.",
    "offsite_amenities": "Tiện ích xung quanh dự án và liên kết vùng.",
    "legal": "Giấy phép, chủ trương đầu tư, sổ hồng và tình trạng pháp lý.",
    "investor": "Chủ đầu tư, năng lực và các dự án đã bàn giao.",
}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _arr(items: list[str]) -> str:
    return "ARRAY[" + ", ".join(_q(x) for x in items) + "]::text[]" if items else "'{}'::text[]"


def _seed_body() -> str:
    sources = ",\n".join(
        f"(p_tenant, {_q(d)}, {_q(n)}, 'default', {_q(fm)}, {_q(k)}, {_arr(rss)}, {_q(si)}, {_q(ch)}, "
        f"{_arr(ns)}, {_arr(cp)}, {_q(ap)}, {_arr(cpa)}, 'ok', now())"
        for d, n, fm, k, rss, si, ch, ns, cp, ap, cpa in _SOURCES
    )
    topics = ",\n".join(
        f"(p_tenant, {_q(c)}, {_q(lb)}, {_q(h)}, {_q(_TOPIC_DESCRIPTIONS[c])}, {'true' if ds else 'false'}, "
        f"{_arr(kw)}, {_arr(qs)}, 'default', {i})"
        for i, (c, lb, h, ds, kw, qs) in enumerate(_TOPICS)
    )
    return f"""
CREATE FUNCTION control.kbweb_seed_defaults(p_tenant text) RETURNS void
LANGUAGE plpgsql AS $kbweb$
DECLARE v_cu text := current_setting('app.tenant_id', true);
BEGIN
    -- RLS FORCE áp cả chủ bảng: trỏ app.tenant_id vào tenant đích rồi trả lại giá trị cũ.
    PERFORM set_config('app.tenant_id', p_tenant, true);
    INSERT INTO tenant_data.kbweb_sources
        (tenant_id, domain, name, origin, fetch_mode, kind, rss, sitemap_index, child_hint,
         news_sitemaps, category_pages, article_pattern, category_paths, probe_status, probe_at)
    VALUES
{sources}
    ON CONFLICT DO NOTHING;
    INSERT INTO tenant_data.kbweb_topics
        (tenant_id, code, label, heading, description, dossier, keywords, queries, origin, position)
    VALUES
{topics}
    ON CONFLICT DO NOTHING;
    INSERT INTO tenant_data.kbweb_schedules
        (tenant_id, mode, enabled, at_time, weekdays, every_months, day_rule, slices)
    VALUES (p_tenant, 'nightly', true, '01:10', '{{}}', NULL, NULL, 1),
           (p_tenant, 'weekly', true, '04:00', '{{1,3,5}}', NULL, NULL, 3),
           (p_tenant, 'rebuild', true, '05:00', '{{}}', 3, 'd1', 1)
    ON CONFLICT DO NOTHING;
    INSERT INTO tenant_data.kbweb_limits (tenant_id) VALUES (p_tenant) ON CONFLICT DO NOTHING;
    PERFORM set_config('app.tenant_id', coalesce(v_cu, ''), true);
END $kbweb$;

CREATE FUNCTION control.tao_kbweb_mac_dinh() RETURNS trigger
LANGUAGE plpgsql AS $kbweb$
BEGIN
    PERFORM control.kbweb_seed_defaults(NEW.id);
    RETURN NULL;
END $kbweb$;

CREATE TRIGGER tenants_tao_kbweb_mac_dinh AFTER INSERT ON control.tenants
FOR EACH ROW EXECUTE FUNCTION control.tao_kbweb_mac_dinh();
"""


def upgrade() -> None:
    op.execute(_DDL)
    op.execute(_BACKFILL_PAGES)
    for t in _TABLES:
        op.execute(f"SELECT control.enforce_tenant_isolation('tenant_data.{t}')")
    op.execute("DROP SCHEMA public_data CASCADE")
    op.execute(_seed_body())
    op.execute("SELECT control.kbweb_seed_defaults(id) FROM control.tenants")


def downgrade() -> None:
    """Dựng lại `public_data.web_pages` RỖNG (DDL của `0969`) — bài theo tenant không gộp ngược được."""
    op.execute("DROP TRIGGER tenants_tao_kbweb_mac_dinh ON control.tenants")
    op.execute("DROP FUNCTION control.tao_kbweb_mac_dinh()")
    op.execute("DROP FUNCTION control.kbweb_seed_defaults(text)")
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE tenant_data.{t}")
    op.execute(
        """
        CREATE SCHEMA public_data;
        CREATE TABLE public_data.web_pages (
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
        CREATE INDEX web_pages_projects_gin ON public_data.web_pages USING gin (projects);
        CREATE INDEX web_pages_location_gin ON public_data.web_pages USING gin (location);
        CREATE INDEX web_pages_published_idx ON public_data.web_pages (published_at);
        CREATE INDEX web_pages_fetched_idx ON public_data.web_pages (fetched_at);
        CREATE INDEX web_pages_hash_idx ON public_data.web_pages (content_hash) WHERE content_hash <> '';
        GRANT USAGE ON SCHEMA public_data TO portal_api;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public_data.web_pages TO portal_api;
        """
    )
