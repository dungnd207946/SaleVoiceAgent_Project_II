"""Ba job vận hành: cascade theo dự án, dựng collection lúc cấp workspace, thu hồi caption cũ.

Router KHÔNG được enqueue N job trực tiếp — một dự án có 20 phân khu + 96 media thì
giao dịch của request mở suốt 116 lần INSERT trong khi người dùng ngồi chờ.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.kb import jobs
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE
from portal.modules.kb.index.store import PointIn, QdrantStore, point_id_of
from portal.modules.kb.ops import sync
from portal.modules.kb.state import repo
from tests.modules.kb.fake import FakeIndexClient, FakeObjectStore

TENANT = "kb_acme"


@pytest.fixture
def fakes(monkeypatch):
    rag, media, store = FakeIndexClient(), FakeIndexClient(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    return rag, media, store


async def test_enqueue_project_xep_job_cho_moi_record_published(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        n = await sync.enqueue_project(conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test")
        kinds = await conn.fetch(
            "SELECT kind, payload FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )
    assert n == len(kinds) > 0
    assert all(p["payload"] for p in kinds)


async def test_khong_xep_job_cho_du_an_khac(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        await sync.enqueue_project(conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test")
        rows = await conn.fetch(
            "SELECT payload->>'record_id' AS rid FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'",
            TENANT,
        )
        thuoc_du_an_khac = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.documents "
            "WHERE tenant_id = portal.current_tenant() AND project_code <> 'nplb' "
            "  AND id::text = ANY($1::text[])",
            [r["rid"] for r in rows],
        )
    assert thuoc_du_an_khac == 0, "cascade tràn sang dự án khác"


async def test_du_an_khong_ton_tai_tra_khong(pool, seed_kb):
    async with tenant_conn(pool, TENANT) as conn:
        n = await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="khong_co", vertical=REAL_ESTATE, actor="test"
        )
    assert n == 0


async def test_handle_sync_project_uy_thac_cho_ops_sync(pool, seed_kb, fakes):
    """Handler chỉ đọc `payload["project_code"]` rồi giao việc — logic thật đã có test riêng ở trên."""
    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_sync_project(conn, {"vertical": "real_estate", "project_code": "nplb"})
        n_thuc = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_index'", TENANT
        )
    assert result.count == n_thuc > 0


async def test_handle_sync_project_dung_collection_truoc_khi_xep_job(pool, seed_kb, fakes):
    """Không ai enqueue `kb_provision` — `KIND_PROVISION` chỉ có ở chỗ khai và chỗ register.

    Với tenant mới chưa có collection, mọi job con của lần sync đầu nổ 404 ở
    `delete_by_record`. 8 collection có sẵn trên dev che chuyện này. `collections.create`
    idempotent sẵn nên gọi mỗi lần sync là an toàn.
    """
    rag, media, _store = fakes
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_sync_project(conn, {"vertical": "real_estate", "project_code": "nplb"})

    assert rag.created_collections == [TENANT]
    assert media.created_collections == [TENANT]


class _ClientDemLuotDong(FakeIndexClient):
    def __init__(self) -> None:
        super().__init__()
        self.so_lan_dong = 0

    async def aclose(self) -> None:
        self.so_lan_dong += 1


@pytest.fixture
def fakes_dong_duoc(monkeypatch):
    rag, media, store = _ClientDemLuotDong(), _ClientDemLuotDong(), FakeObjectStore()
    monkeypatch.setattr(jobs, "dependencies", lambda: (rag, media, store))
    return rag, media, store


async def test_handler_dong_client_sau_moi_job(pool, seed_kb, fakes_dong_duoc):
    """Worker là tiến trình sống dài và `dependencies()` dựng client MỚI mỗi job.

    Một lần bấm "Đồng bộ tri thức" cho dự án 116 record = 116 job = 116 httpx client
    (embed) + 116 AsyncQdrantClient bỏ lại chờ GC.
    """
    rag, media, _store = fakes_dong_duoc
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_provision(conn, {})

    assert (rag.so_lan_dong, media.so_lan_dong) == (1, 1)


async def test_handler_dong_client_ca_khi_job_no(pool, seed_kb, fakes_dong_duoc, monkeypatch):
    """Job lỗi là lúc rò rỉ tệ nhất: worker retry, mỗi lần retry thêm một cặp client."""
    rag, media, _store = fakes_dong_duoc

    async def no(**_kw):
        raise RuntimeError("Qdrant từ chối")

    monkeypatch.setattr(rag, "create_collection", no)
    async with tenant_conn(pool, TENANT) as conn:
        with pytest.raises(RuntimeError):
            await jobs.handle_provision(conn, {})

    assert (rag.so_lan_dong, media.so_lan_dong) == (1, 1)


async def test_handle_provision_dung_ca_hai_collection(pool, seed_kb, fakes):
    rag, media, _store = fakes
    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_provision(conn, {})
    assert result.count == 2
    assert rag.created_collections == [TENANT]
    assert media.created_collections == [TENANT]


async def test_handle_provision_khong_dung_dependencies_that(pool, seed_kb, fakes):
    """`dependencies()` thật dựng EmbedClient và raise nếu thiếu KB_SANTA_MODELS_TOKEN —
    handler phải đi qua seam `jobs.dependencies`, không tự dựng client bên trong."""
    async with tenant_conn(pool, TENANT) as conn:
        await jobs.handle_provision(conn, {})  # không raise nghĩa là seam được tôn trọng


@pytest.fixture
async def media_id_co_caption(pool, seed_kb, qdrant_url, monkeypatch):
    """Media rỗng caption ở Postgres + một point Qdrant có caption — mô phỏng hệ cũ.

    ⚠️ Bộ khoá payload dưới đây là bộ ĐO THẬT trên máy chủ dev (2026-08-10), và điều
    quan trọng nhất của nó là thứ KHÔNG có: `anchor_code`. Bản trước của fixture seed
    kèm khoá đó, tức mô phỏng định dạng MỚI, nên nó không bắt được việc job thu hồi
    lọc scroll theo anchor và trả về 0 point cho toàn bộ dữ liệu cũ.
    """
    from portal.core.config import Settings
    from portal.modules.kb.clients.media import collection_name

    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, qdrant_url=qdrant_url))
    async with tenant_conn(pool, TENANT) as conn:
        record_id = await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/a.jpg', 'published')
               RETURNING id"""
        )
    ten = collection_name(TENANT)
    store = QdrantStore(url=qdrant_url)
    # `qdrant_url` là container CHUNG cho cả phiên test, và tên collection suy từ tenant
    # là cố định ("kb_acme_media") — dọn trước khi ghi để point của test khác không lẫn vào.
    await store.drop_collection(ten)
    await store.ensure_collection(ten, media=True)
    await store.upsert(
        ten,
        [
            PointIn(
                point_id_of("", record_id, 0),
                {"text": [0.1] * 1024},
                {
                    "project_id": "nplb",
                    "content_type": "image",
                    "category": "mat_bang",
                    "caption": "chú thích hệ cũ",
                    "media_url": "https://nbx-sales-dev.noble.vn/a.jpg",
                    "content_hash": "8386ca49",
                    "record_id": record_id,
                    "thumb_url": "http://10.50.13.220:9000/t.webp",
                },
            )
        ],
    )
    await store.aclose()
    return record_id


async def test_handle_reclaim_caption_ghi_caption_tu_qdrant_ve_aurora(pool, media_id_co_caption):
    record_id = media_id_co_caption
    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_reclaim_caption(conn, {"vertical": "real_estate"})
        caption = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert result.count == 1
    assert caption == "chú thích hệ cũ"


async def test_handle_reclaim_caption_khong_de_len_caption_da_co(pool, media_id_co_caption):
    """Idempotent qua luật chỉ-ghi-khi-rỗng của `cache_caption` — chạy job hai lần không
    đè caption mà biên tập viên đã tự sửa giữa hai lần chạy."""
    record_id = media_id_co_caption
    async with tenant_conn(pool, TENANT) as conn:
        await repo.cache_caption(conn, record_id=record_id, caption="bản người sửa", force=True)
        result = await jobs.handle_reclaim_caption(conn, {"vertical": "real_estate"})
        caption = await conn.fetchval(
            "SELECT caption FROM tenant_data.media WHERE tenant_id = portal.current_tenant() AND id = $1",
            record_id,
        )
    assert result.count == 1, "vẫn đếm là đã thấy caption trong Qdrant, dù không ghi đè"
    assert caption == "bản người sửa"


async def test_handle_reclaim_caption_bo_qua_point_khong_co_caption(pool, seed_kb, qdrant_url, monkeypatch):
    from portal.core.config import Settings
    from portal.modules.kb.clients.media import collection_name

    monkeypatch.setattr("portal.core.config.get_settings", lambda: Settings(_env_file=None, qdrant_url=qdrant_url))
    async with tenant_conn(pool, TENANT) as conn:
        record_id = await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/b.jpg', 'published')
               RETURNING id"""
        )
    ten = collection_name(TENANT)
    store = QdrantStore(url=qdrant_url)
    await store.drop_collection(ten)
    await store.ensure_collection(ten, media=True)
    await store.upsert(
        ten,
        [
            PointIn(
                point_id_of("", record_id, 0), {"text": [0.1] * 1024}, {"record_id": record_id, "project_id": "nplb"}
            )
        ],
    )
    await store.aclose()

    async with tenant_conn(pool, TENANT) as conn:
        result = await jobs.handle_reclaim_caption(conn, {"vertical": "real_estate"})
    assert result.count == 0


async def test_nap_lai_mo_chuoi_boc_chu_cho_tai_lieu_chua_co_chu(pool, seed_kb):
    """Tài liệu CÓ tệp mà CHƯA có chữ cần chặng BÓC CHỮ, không phải chặng nạp.

    Nạp thẳng nó chỉ cho 0 chunk và không point nào — nên "Nạp lại toàn bộ" không chữa được
    đúng cái class lỗi mà người vận hành bấm nó để chữa. Đo trên dữ liệu thật (mockdb,
    2026-08-15): 34 tài liệu CSBH ở đúng trạng thái đó, và không lượt nạp lại nào chạm tới.
    """
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status) VALUES "
            "(portal.current_tenant(), 'nplb', 'CSBH — bảng giá', '', 'tenants/x/kb-bds/a/bg.png', 'published'), "
            "(portal.current_tenant(), 'nplb', 'Đã có chữ', 'nội dung sẵn', 'tenants/x/kb-bds/a/c.pdf', 'published'),"
            "(portal.current_tenant(), 'nplb', 'Không tệp', '', NULL, 'published')"
        )
        await sync.enqueue_project(conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test")
        thumb = await conn.fetch(
            "SELECT (payload->>'record_id')::bigint AS rid FROM control.jobs "
            " WHERE tenant_id = $1 AND kind = 'kb_thumb' AND payload->>'entity' = 'documents'",
            TENANT,
        )
        theo_ten = {
            r["title"]: r["id"]
            for r in await conn.fetch(
                "SELECT id, title FROM tenant_data.documents WHERE tenant_id = portal.current_tenant()"
            )
        }

    ids = {int(r["rid"]) for r in thumb}
    assert theo_ten["CSBH — bảng giá"] in ids, "tài liệu có tệp mà thiếu chữ KHÔNG được mở chuỗi bóc chữ"
    assert theo_ten["Đã có chữ"] not in ids, "tài liệu đã có chữ thì không bóc lại"
    assert theo_ten["Không tệp"] not in ids, "không có tệp thì không có gì để bóc"


async def test_count_KHONG_dem_viec_thumb_bi_gop(pool, seed_kb):
    """`dat_viec_thumb` tự gộp: đã có việc `kb_thumb` chờ cho cùng record thì nó trả `None`
    và KHÔNG tạo job. Đếm cả những lượt đó là con số trả về nói dối — nạp lại hai lần liên
    tiếp báo cùng một khối lượng dù lượt thứ hai không xếp thêm gì."""
    async with tenant_conn(pool, TENANT) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.documents (tenant_id, project_code, title, body, file_url, status) "
            "VALUES (portal.current_tenant(), 'nplb', 'CSBH — chờ bóc', '', 'tenants/x/a.png', 'published')"
        )
        lan1 = await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test"
        )
        lan2 = await sync.enqueue_project(
            conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test"
        )
        thumb = await conn.fetchval(
            "SELECT count(*) FROM control.jobs WHERE tenant_id = $1 AND kind = 'kb_thumb'", TENANT
        )

    assert thumb == 1, "việc thumb thứ hai phải bị gộp, không tạo job mới"
    assert lan2 == lan1 - 1, "count lượt hai phải THIẾU đúng một việc thumb bị gộp"


async def test_dong_bo_mo_chuoi_mo_ta_cho_anh_chua_ai_mo_ta(pool, seed_kb):
    """Nút «Đồng bộ tri thức» LÀ đường backfill mô tả — không cần script riêng.

    Và ảnh đó chỉ nhận MỘT job: chặng mô tả tự nối sang việc nạp, nên đặt thêm `kb_index`
    ở đây là hai lượt embed cho một ảnh, lượt đầu cho một point chắc chắn bị thay ngay
    sau đó (`content_hash` của point media là `sha256(media_url␟caption)`).
    """
    async with tenant_conn(pool, TENANT) as conn:
        chua = await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/chua-mo-ta.jpg', 'published')
               RETURNING id"""
        )
        roi = await conn.fetchval(
            """INSERT INTO tenant_data.media
                      (tenant_id, project_code, content_type, category, media_url, caption, status)
               VALUES (portal.current_tenant(), 'nplb', 'image', 'tong_quan',
                       'https://cdn.test/da-mo-ta.jpg', 'Khách đã mô tả', 'published')
               RETURNING id"""
        )
        await sync.enqueue_project(conn, tenant_id=TENANT, project_code="nplb", vertical=REAL_ESTATE, actor="test")
        viec = await conn.fetch(
            "SELECT kind, (payload->>'record_id')::bigint AS rid FROM control.jobs "
            " WHERE tenant_id = $1 AND (payload->>'record_id')::bigint = ANY($2)",
            TENANT,
            [chua, roi],
        )

    theo_anh = {r["rid"]: [x["kind"] for x in viec if x["rid"] == r["rid"]] for r in viec}
    assert theo_anh[chua] == ["kb_caption"], "ảnh chưa mô tả phải đi qua chặng mô tả, và CHỈ một job"
    assert theo_anh[roi] == ["kb_index"], "ảnh đã có mô tả nạp thẳng, không tốn một lượt VLM nào"
