"""Nghiệp vụ màn «Dữ liệu ngoài» — router gọi vào đây, mỗi hàm một giao dịch `tenant_conn`.

Lỗi nghiệp vụ ném `LoiPortal` với mã `KB_WEB_*`; nhật ký `kb_web.*` ghi CÙNG giao dịch với thay đổi.
"""

import json
import re
import secrets
from datetime import datetime, time
from uuid import uuid4

import asyncpg
from qdrant_client import AsyncQdrantClient

from portal.api.loi import LoiPortal
from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.core.db.session import tenant_conn
from portal.core.ten_tai_nguyen import ten_kho_web
from portal.modules.kb.settings import get_env
from portal.modules.kb.web import admin_repo, config, repo, scheduler, usage
from portal.modules.kb.web.browser import _KEY_PREFIX as _BROWSER_PREFIX
from portal.modules.kb.web.compose import dossier_ids, heading_of, is_near_item, near_id
from portal.modules.kb.web.contracts import (
    KIND_PROBE,
    KIND_PROJECT,
    KIND_RUN,
    MODE_INIT,
    MODE_REBUILD,
    MODE_WEEKLY,
    PROFILE_TOPIC_DRAFT,
    SCHEDULE_MODES,
)
from portal.modules.kb.web.defaults import HIDDEN_HEADINGS, HIDDEN_TOPIC_CODES
from portal.modules.kb.web.discover import VN
from portal.modules.kb.web.enqueue import enqueue_web_project
from portal.modules.kb.web.grounding import _month_key
from portal.modules.kb.web.index import WebIndex
from portal.modules.kb.web.llm import WebLlm
from portal.modules.kb.web.normalize import domain_of, project_names, strip_accents
from portal.modules.kb.web.pipeline import location_labels
from portal.modules.kb.web.probe import STATUSES as PROBE_STATUSES
from portal.modules.kb.web.probe_job import result_key
from portal.modules.kb.web.schemas import (
    BaiOut,
    ChiTietDuAnOut,
    ChuDeOut,
    DuAnOut,
    GioiHanOut,
    JobOut,
    LichOut,
    LichTongIn,
    LichTongOut,
    MucHoSoOut,
    NguonBaiOut,
    NguonDeXuat,
    NguonOut,
    OverviewOut,
    SoanChuDeOut,
    SuaChuDeIn,
    SuaNguonIn,
    ThemChuDeIn,
    ThemNguonIn,
    ThuNguonOut,
)
from portal.modules.kb.web.signal import ProjectRow, load_projects

MAX_TOPICS = 20
MAX_PAGES_DETAIL = 100


def _loi(ma: str, http: int, msg: str) -> LoiPortal:
    return LoiPortal(f"KB_WEB_{ma}", http, msg)


def _payload(r: asyncpg.Record) -> dict:
    p = r["payload"]
    return json.loads(p) if isinstance(p, str) else dict(p or {})


def job_out(r: asyncpg.Record, *, show_cost: bool = False) -> JobOut:
    p = _payload(r)
    probe_status = None
    if r["kind"] == KIND_PROBE and r["message"]:
        tail = r["message"].rsplit(": ", 1)[-1]
        probe_status = tail if tail in PROBE_STATUSES else None
    return JobOut(
        id=r["id"],
        loai=r["kind"],
        mode=str(p.get("mode") or ""),
        duAn=p.get("project_code"),
        duAnTen=r["project_name"],
        url=p.get("url"),
        tinhTrangNguon=probe_status,
        trangThai=r["state"],
        nguoi=r["actor"],
        nguoiTen=r["actor_name"],
        taoLuc=r["created_at"],
        batDau=r["started_at"],
        ketThuc=r["finished_at"],
        soLuong=int(r["count"] or 0),
        thongDiep=r["message"] or "",
        chiPhi=r["cost"] if show_cost else None,
    )


def _qdrant() -> AsyncQdrantClient:
    s = get_settings()
    return AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)


async def _dossiers(tenant: str, projects: list[ProjectRow], *, with_near: bool = False) -> dict[str, list]:
    """Mục hồ sơ hiện có của từng dự án, đọc từ Qdrant (collection chưa có ⇒ rỗng).
    `with_near`: kèm point "Các dự án gần X" (nội dung của chủ đề «Dự án lân cận»)."""
    client = _qdrant()
    try:
        idx = WebIndex(client=client, embed=None, collection=ten_kho_web(tenant))
        if not await client.collection_exists(idx.collection):
            return {p.code: [] for p in projects}
        return {
            p.code: await idx.get([*dossier_ids(p.name), *([near_id(p.name)] if with_near else [])]) for p in projects
        }
    finally:
        await client.close()


def _sections(cfg: config.WebConfig, its: list, hidden: frozenset[str]) -> list[MucHoSoOut]:
    """Một mục cho mỗi chủ đề đang bật ở tab Chủ đề, theo thứ tự của tab đó; chủ đề chưa có nội dung thì
    `noiDung` rỗng. «Tổng quan» và đoạn mang nhãn chủ đề đã tắt/đã xoá không hiện (agent vẫn đọc)."""
    headings = cfg.headings()
    near = [it for it in its if is_near_item(it)]
    by_heading: dict[str, list] = {}
    for it in its:
        if not is_near_item(it):
            by_heading.setdefault(heading_of(it.text, headings), []).append(it)
    rows = []
    for t in cfg.topics:
        if t.code in HIDDEN_TOPIC_CODES:
            continue
        h = t.heading or t.label
        rows.append((h, t.label, by_heading.get(h, []) if t.dossier else near))
    out = []
    for nhan, ten, group in rows:
        sources = list({s.url: s for it in group for s in it.sources}.values())
        stamps = [it.updated_at for it in group if it.updated_at]
        out.append(
            MucHoSoOut(
                nhan=nhan,
                ten=ten,
                noiDung="\n\n".join(it.text for it in group),
                nguon=[NguonBaiOut(url=s.url, ten=s.name, ngay=s.published_at) for s in sources],
                capNhatLuc=max(stamps) if stamps else None,
                an=nhan in hidden,
            )
        )
    return out


# ─── tổng quan ───────────────────────────────────────────────────────────────


async def overview(pool: asyncpg.Pool, redis, tenant: str) -> OverviewOut:
    async with tenant_conn(pool, tenant) as c:
        projects = await load_projects(c)
        d7, d30 = await admin_repo.page_counts(c)
        sources = await admin_repo.list_sources(c)
        limits = await admin_repo.get_limits(c)
        running = await admin_repo.list_jobs(c, states=["queued", "running"], limit=20)
        failed = await admin_repo.list_jobs(c, states=["failed"], limit=5)
        scheds = await admin_repo.list_schedules(c)
    items = await _dossiers(tenant, projects)
    stamps = [it.updated_at for its in items.values() for it in its if it.updated_at]
    now = datetime.now(VN)
    g_used = b_used = 0
    if redis is not None:
        g_used = int(await redis.get(_month_key(tenant, now.date())) or 0)
        b_used = int(await redis.get(f"{_BROWSER_PREFIX}{tenant}:{now:%Y-%m-%d}") or 0)
    nexts = [r["next_run_at"] for r in scheds if r["enabled"] and r["next_run_at"]]
    return OverviewOut(
        soDuAn=len(projects),
        soDuAnCoHoSo=sum(1 for v in items.values() if v),
        hoSoCuNhat=min(stamps) if stamps else None,
        baiBayNgay=d7,
        baiBaMuoiNgay=d30,
        soNguonBat=sum(1 for s in sources if s["enabled"]),
        groundingThang=g_used,
        groundingTran=int(limits["grounding_monthly"]) if limits else 1000,
        trinhDuyetHomNay=b_used,
        trinhDuyetTran=int(limits["browser_daily"]) if limits else 300,
        dangChay=[job_out(r) for r in running],
        loiGanDay=[job_out(r) for r in failed],
        lanKeTiep=min(nexts) if nexts else None,
    )


async def worker_alive(redis) -> bool:
    return redis is not None and bool(await redis.get(scheduler.ALIVE_KEY))


# ─── nguồn ───────────────────────────────────────────────────────────────────


def _nguon_out(r: asyncpg.Record) -> NguonOut:
    return NguonOut(
        id=r["id"],
        domain=r["domain"],
        ten=r["name"],
        bat=r["enabled"],
        macDinh=r["origin"] == "default",
        cheDo=r["fetch_mode"],
        theoDoi=r["kind"],
        baiBayNgay=int(r["pages_7d"]) if "pages_7d" in r else 0,
        tinhTrang=r["probe_status"],
        ghiChu=r["probe_note"] or "",
        thuLuc=r["probe_at"],
    )


async def list_sources(pool: asyncpg.Pool, tenant: str) -> list[NguonOut]:
    async with tenant_conn(pool, tenant) as c:
        return [_nguon_out(r) for r in await admin_repo.list_sources(c)]


async def start_probe(pool: asyncpg.Pool, tenant: str, user_id: str, url: str) -> tuple[str, int]:
    """Xếp job thử nguồn (chạy ở crawl-worker, nơi có trình duyệt). Trả (token, job_id)."""
    from portal.core.jobs import enqueue

    token = secrets.token_urlsafe(9)
    async with tenant_conn(pool, tenant) as c:
        job_id = await enqueue(
            c, tenant_id=tenant, kind=KIND_PROBE, actor=user_id, payload={"url": url.strip(), "token": token}
        )
    return token, job_id


async def probe_result(pool: asyncpg.Pool, redis, tenant: str, token: str) -> tuple[str, ThuNguonOut | None]:
    """('dang_chay' | 'xong' | 'loi', kết quả) — kết quả nằm ở Redis do job ghi."""
    raw = await redis.get(result_key(tenant, token)) if redis is not None else None
    if raw:
        d = json.loads(raw)
        site = d.get("site")
        async with tenant_conn(pool, tenant) as c:
            da_co = bool(site and await admin_repo.source_by_domain(c, site["domain"]))
        return "xong", ThuNguonOut(
            trangThai=d["status"],
            ghiChu=d.get("note") or "",
            soBai=int(d.get("articles") or 0),
            soTrangThu=int(d.get("pages_tested") or 0),
            soTrangDoc=int(d.get("pages_ok") or 0),
            daCo=da_co,
            deXuat=NguonDeXuat(
                domain=site["domain"],
                ten=site["name"],
                cheDo=site["fetch_mode"],
                theoDoi=site["kind"],
                rss=list(site["rss"]),
                sitemapIndex=site["sitemap_index"],
                newsSitemaps=list(site["news_sitemaps"]),
                categoryPages=list(site["category_pages"]),
                articlePattern=site["article_pattern"],
            )
            if site
            else None,
        )
    async with tenant_conn(pool, tenant) as c:
        job = await admin_repo.job_by_token(c, KIND_PROBE, token)
    if job is None:
        raise _loi("THU_KHONG_TON_TAI", 404, "Không có lượt thử nào với mã này")
    return ("loi" if job["state"] == "failed" else "dang_chay"), None


async def add_source(pool: asyncpg.Pool, tenant: str, user_id: str, body: ThemNguonIn) -> NguonOut:
    domain = domain_of(f"https://{body.domain}" if "://" not in body.domain else body.domain)
    if not domain:
        raise _loi("NGUON_KHONG_HOP_LE", 422, "Tên miền không hợp lệ")
    async with tenant_conn(pool, tenant) as c:
        if await admin_repo.source_by_domain(c, domain):
            raise _loi("NGUON_DA_CO", 409, f"{domain} đã có trong danh sách nguồn")
        sid = await admin_repo.insert_source(
            c,
            created_by=user_id,
            domain=domain,
            name=body.ten.strip(),
            fetch_mode=body.cheDo,
            kind=body.theoDoi,
            rss=body.rss,
            sitemap_index=body.sitemapIndex,
            news_sitemaps=body.newsSitemaps,
            category_pages=body.categoryPages,
            article_pattern=body.articlePattern,
            probe_status=body.tinhTrang,
            probe_note=body.ghiChu,
        )
        await nhat_ky.ghi(c, tenant, "kb_web.nguon_them", user_id, {"id": sid, "domain": domain, "che_do": body.cheDo})
    return await get_source(pool, tenant, sid)


async def get_source(pool: asyncpg.Pool, tenant: str, source_id: int) -> NguonOut:
    async with tenant_conn(pool, tenant) as c:
        rows = [r for r in await admin_repo.list_sources(c) if r["id"] == source_id]
    if not rows:
        raise _loi("NGUON_KHONG_TON_TAI", 404, "Không có nguồn này")
    return _nguon_out(rows[0])


async def update_source(pool: asyncpg.Pool, tenant: str, user_id: str, source_id: int, body: SuaNguonIn) -> NguonOut:
    async with tenant_conn(pool, tenant) as c:
        if await admin_repo.get_source(c, source_id) is None:
            raise _loi("NGUON_KHONG_TON_TAI", 404, "Không có nguồn này")
        await admin_repo.update_source(c, source_id, enabled=body.bat, name=body.ten and body.ten.strip())
        await nhat_ky.ghi(
            c, tenant, "kb_web.nguon_sua", user_id, {"id": source_id, **body.model_dump(exclude_none=True)}
        )
    return await get_source(pool, tenant, source_id)


async def delete_source(pool: asyncpg.Pool, tenant: str, user_id: str, source_id: int) -> None:
    async with tenant_conn(pool, tenant) as c:
        r = await admin_repo.get_source(c, source_id)
        if r is None:
            raise _loi("NGUON_KHONG_TON_TAI", 404, "Không có nguồn này")
        await admin_repo.delete_source(c, source_id)
        await nhat_ky.ghi(c, tenant, "kb_web.nguon_xoa", user_id, {"id": source_id, "domain": r["domain"]})


async def retry_source(pool: asyncpg.Pool, tenant: str, user_id: str, source_id: int) -> tuple[str, int]:
    """Thử lại một nguồn đã có: cùng job thử, URL = trang chủ của domain."""
    async with tenant_conn(pool, tenant) as c:
        r = await admin_repo.get_source(c, source_id)
    if r is None:
        raise _loi("NGUON_KHONG_TON_TAI", 404, "Không có nguồn này")
    url = r["category_pages"][0] if r["category_pages"] else f"https://{r['domain']}/"
    return await start_probe(pool, tenant, user_id, url)


async def apply_probe_to_source(pool: asyncpg.Pool, tenant: str, source_id: int, result: ThuNguonOut) -> NguonOut:
    """Ghi kết quả lượt thử lại vào hàng nguồn (màn gọi sau khi poll xong)."""
    async with tenant_conn(pool, tenant) as c:
        if await admin_repo.get_source(c, source_id) is None:
            raise _loi("NGUON_KHONG_TON_TAI", 404, "Không có nguồn này")
        await admin_repo.update_probe(
            c,
            source_id,
            fetch_mode=result.deXuat.cheDo if result.deXuat else "http",
            status=result.trangThai,
            note=result.ghiChu,
        )
    return await get_source(pool, tenant, source_id)


# ─── chủ đề ──────────────────────────────────────────────────────────────────


def _chu_de_out(r: asyncpg.Record) -> ChuDeOut:
    return ChuDeOut(
        id=r["id"],
        code=r["code"],
        ten=r["label"],
        nhan=r["heading"] or r["label"],
        moTa=r["description"] or "",
        cauTim=list(r["queries"]),
        tuKhoa=list(r["keywords"]),
        bat=r["enabled"],
        macDinh=r["origin"] == "default",
        vaoHoSo=r["dossier"],
        thuTu=r["position"],
    )


async def list_topics(pool: asyncpg.Pool, tenant: str) -> list[ChuDeOut]:
    async with tenant_conn(pool, tenant) as c:
        rows = await admin_repo.list_topics(c)
    return [_chu_de_out(r) for r in rows if r["code"] not in HIDDEN_TOPIC_CODES]


async def _visible_topic(c: asyncpg.Connection, topic_id: int) -> asyncpg.Record:
    r = await admin_repo.get_topic(c, topic_id)
    if r is None or r["code"] in HIDDEN_TOPIC_CODES:
        raise _loi("CHU_DE_KHONG_TON_TAI", 404, "Không có chủ đề này")
    return r


def _check_queries(queries: list[str]) -> list[str]:
    out = [q.strip() for q in queries if q.strip()]
    if not out:
        raise _loi("CHU_DE_THIEU_CAU_TIM", 422, "Cần ít nhất một câu tìm bài")
    for q in out:
        if "{project}" not in q and "{location}" not in q:
            raise _loi("CHU_DE_CAU_TIM_THIEU_BIEN", 422, f"Câu «{q}» phải có {{project}} hoặc {{location}}")
        try:
            q.format(project="X", location="Y")
        except (KeyError, IndexError, ValueError) as exc:
            raise _loi("CHU_DE_CAU_TIM_SAI", 422, f"Câu «{q}» chỉ được dùng {{project}} và {{location}}") from exc
    return out


def topic_code(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", strip_accents(label).lower()).strip("_")[:30] or "chu_de"
    if base[0].isdigit():
        base = "t_" + base
    code, n = base, 2
    while code in taken:
        code, n = f"{base}_{n}", n + 1
    return code


async def draft_topic(pool: asyncpg.Pool, tenant: str, ten: str, mo_ta: str) -> SoanChuDeOut:
    env = get_env()
    if not env.vlm_api_key:
        raise _loi("LLM_CHUA_CAU_HINH", 503, "Chưa cấu hình dịch vụ soạn câu tìm bài")
    llm = WebLlm(base_url=env.vlm_base_url, api_key=env.vlm_api_key, concurrency=1)
    try:
        prompt = f"TÊN CHỦ ĐỀ: {ten.strip()}\nMÔ TẢ: {mo_ta.strip() or '(không có)'}"
        with usage.metering() as m:
            raw = await llm.ask(PROFILE_TOPIC_DRAFT, prompt)
    finally:
        await llm.aclose()
    await usage.flush(pool, tenant, m, session_id=f"{usage.DRAFT_SESSION_PREFIX}{uuid4().hex}", seq=0)
    queries = [str(q) for q in raw.get("queries") or [] if isinstance(q, str)]
    queries = [q for q in queries if "{project}" in q or "{location}" in q][:4]
    keywords = [str(k).strip().lower() for k in raw.get("keywords") or [] if isinstance(k, str) and str(k).strip()][:12]
    if not queries:
        raise _loi("CHU_DE_SOAN_HONG", 502, "Không soạn được câu tìm bài, hãy thử mô tả rõ hơn")
    return SoanChuDeOut(cauTim=queries, tuKhoa=keywords)


async def add_topic(pool: asyncpg.Pool, tenant: str, user_id: str, body: ThemChuDeIn) -> ChuDeOut:
    queries = _check_queries(body.cauTim)
    async with tenant_conn(pool, tenant) as c:
        taken = await admin_repo.topic_codes(c)
        if len(taken - HIDDEN_TOPIC_CODES) >= MAX_TOPICS:
            raise _loi("CHU_DE_QUA_GIOI_HAN", 409, f"Tối đa {MAX_TOPICS} chủ đề mỗi workspace")
        code = topic_code(body.ten, taken)
        tid = await admin_repo.insert_topic(
            c,
            code=code,
            label=body.ten.strip(),
            description=body.moTa.strip(),
            keywords=[k.strip().lower() for k in body.tuKhoa if k.strip()],
            queries=queries,
            created_by=user_id,
        )
        await nhat_ky.ghi(c, tenant, "kb_web.chu_de_them", user_id, {"id": tid, "code": code, "ten": body.ten})
        r = await admin_repo.get_topic(c, tid)
    return _chu_de_out(r)


async def update_topic(pool: asyncpg.Pool, tenant: str, user_id: str, topic_id: int, body: SuaChuDeIn) -> ChuDeOut:
    queries = _check_queries(body.cauTim) if body.cauTim is not None else None
    async with tenant_conn(pool, tenant) as c:
        await _visible_topic(c, topic_id)
        await admin_repo.update_topic(
            c,
            topic_id,
            enabled=body.bat,
            label=body.ten and body.ten.strip(),
            description=body.moTa,
            keywords=[k.strip().lower() for k in body.tuKhoa if k.strip()] if body.tuKhoa is not None else None,
            queries=queries,
        )
        await nhat_ky.ghi(
            c, tenant, "kb_web.chu_de_sua", user_id, {"id": topic_id, **body.model_dump(exclude_none=True)}
        )
        r = await admin_repo.get_topic(c, topic_id)
    return _chu_de_out(r)


async def delete_topic(pool: asyncpg.Pool, tenant: str, user_id: str, topic_id: int) -> None:
    async with tenant_conn(pool, tenant) as c:
        r = await _visible_topic(c, topic_id)
        await admin_repo.delete_topic(c, topic_id)
        await nhat_ky.ghi(c, tenant, "kb_web.chu_de_xoa", user_id, {"id": topic_id, "code": r["code"]})


# ─── lịch ────────────────────────────────────────────────────────────────────


def _lich_out(r: asyncpg.Record) -> LichOut:
    return LichOut(
        mode=r["mode"],
        bat=r["enabled"],
        gio=r["at_time"].strftime("%H:%M"),
        ngayTrongTuan=list(r["weekdays"] or []),
        soThang=r["every_months"],
        ngayTrongChuKy=r["day_rule"],
        latCat=r["slices"],
        lanGanNhat=r["last_run_at"],
        lanKeTiep=r["next_run_at"],
    )


async def get_schedules(pool: asyncpg.Pool, tenant: str) -> LichTongOut:
    async with tenant_conn(pool, tenant) as c:
        rows = await admin_repo.list_schedules(c)
        lim = await admin_repo.get_limits(c)
    gh = GioiHanOut(
        groundingThang=int(lim["grounding_monthly"]) if lim else 1000,
        trinhDuyetNgay=int(lim["browser_daily"]) if lim else 300,
        ngayHoi=int(lim["asked_days"]) if lim else 28,
    )
    return LichTongOut(lich=[_lich_out(r) for r in rows], gioiHan=gh)


async def put_schedules(pool: asyncpg.Pool, tenant: str, user_id: str, body: LichTongIn) -> LichTongOut:
    modes = [li.mode for li in body.lich]
    if len(set(modes)) != len(modes):
        raise _loi("LICH_TRUNG", 422, "Mỗi nhịp chỉ khai một lần")
    now = datetime.now(VN)
    async with tenant_conn(pool, tenant) as c:
        for li in body.lich:
            hh, mm = (int(x) for x in li.gio.split(":"))
            at = time(hh, mm)
            weekdays = sorted({d for d in li.ngayTrongTuan if 0 <= d <= 6}) if li.mode == MODE_WEEKLY else []
            if li.mode == MODE_WEEKLY and li.bat and not weekdays:
                raise _loi("LICH_THIEU_NGAY", 422, "Lịch mỗi tuần cần ít nhất một ngày trong tuần")
            months = li.soThang if li.mode == MODE_REBUILD else None
            rule = li.ngayTrongChuKy if li.mode == MODE_REBUILD else None
            if li.mode == MODE_REBUILD and (not months or not rule):
                raise _loi("LICH_THIEU_CHU_KY", 422, "Lịch viết lại cần chu kỳ và ngày trong chu kỳ")
            nxt = scheduler.next_run(
                li.mode, now, at=at, weekdays=weekdays, every_months=months or 0, day_rule=rule or ""
            )
            await admin_repo.upsert_schedule(
                c,
                mode=li.mode,
                enabled=li.bat,
                at_time=at,
                weekdays=weekdays,
                every_months=months,
                day_rule=rule,
                slices=li.latCat if li.mode == MODE_WEEKLY else 1,
                next_run_at=nxt,
            )
        await nhat_ky.ghi(c, tenant, "kb_web.lich_sua", user_id, {"lich": [li.model_dump() for li in body.lich]})
        if body.gioiHan is not None:
            await admin_repo.upsert_limits(
                c,
                grounding_monthly=body.gioiHan.groundingThang,
                browser_daily=body.gioiHan.trinhDuyetNgay,
                asked_days=body.gioiHan.ngayHoi,
            )
            await nhat_ky.ghi(c, tenant, "kb_web.gioi_han_sua", user_id, body.gioiHan.model_dump())
    return await get_schedules(pool, tenant)


async def run_now(pool: asyncpg.Pool, tenant: str, user_id: str, mode: str) -> JobOut:
    if mode not in SCHEDULE_MODES:
        raise _loi("MODE_KHONG_HOP_LE", 422, f"Nhịp phải là một trong {', '.join(SCHEDULE_MODES)}")
    async with tenant_conn(pool, tenant) as c:
        slices = 1
        if mode == MODE_WEEKLY:
            row = next((r for r in await admin_repo.list_schedules(c) if r["mode"] == MODE_WEEKLY), None)
            slices = int(row["slices"]) if row else 1
        job_id = await scheduler.enqueue_run(c, tenant_id=tenant, actor=user_id, mode=mode, slices=slices)
        if job_id is None:
            raise _loi("DANG_CHAY", 409, "Lượt này đang chờ hoặc đang chạy")
        await nhat_ky.ghi(c, tenant, "kb_web.chay", user_id, {"mode": mode, "job_id": job_id})
        r = await admin_repo.get_job(c, job_id)
    return job_out(r)


# ─── dự án ───────────────────────────────────────────────────────────────────


async def list_projects(pool: asyncpg.Pool, tenant: str) -> list[DuAnOut]:
    async with tenant_conn(pool, tenant) as c:
        projects = await load_projects(c)
        cfg = await config.load_for_tenant(c)
        hidden = await admin_repo.hidden_by_project(c)
        latest = {_payload(r).get("project_code"): r for r in await admin_repo.latest_project_jobs(c)}
    items = await _dossiers(tenant, projects, with_near=True)
    out = []
    for p in projects:
        muc = _sections(cfg, items.get(p.code, []), hidden.get(p.code, frozenset()))
        stamps = [m.capNhatLuc for m in muc if m.capNhatLuc]
        job = latest.get(p.code)
        out.append(
            DuAnOut(
                code=p.code,
                ten=p.name,
                soMuc=sum(1 for m in muc if m.noiDung and not m.an),
                soChuDe=len(muc),
                capNhatLuc=max(stamps) if stamps else None,
                dangChay=bool(job and job["state"] in ("queued", "running")),
                viecGanNhat=job_out(job) if job else None,
            )
        )
    return out


async def _project(c: asyncpg.Connection, code: str) -> ProjectRow:
    p = next((p for p in await load_projects(c) if p.code == code), None)
    if p is None:
        raise _loi("DU_AN_KHONG_TON_TAI", 404, "Không có dự án này hoặc dự án chưa công bố")
    return p


async def project_detail(pool: asyncpg.Pool, tenant: str, code: str) -> ChiTietDuAnOut:
    async with tenant_conn(pool, tenant) as c:
        p = await _project(c, code)
        cfg = await config.load_for_tenant(c)
        hidden = await repo.hidden_headings(c, code)
        excluded = await repo.excluded_urls(c, code)
        pages = await repo.pages_for(
            c,
            projects=list(project_names(p.name)),
            location=list(location_labels(p)),
            limit=MAX_PAGES_DETAIL,
            others=p.more_specific,
        )
        latest = {_payload(r).get("project_code"): r for r in await admin_repo.latest_project_jobs(c)}
    muc = _sections(cfg, (await _dossiers(tenant, [p], with_near=True))[p.code], hidden)
    job = latest.get(code)
    return ChiTietDuAnOut(
        code=code,
        ten=p.name,
        muc=muc,
        mucAn=sorted(hidden - set(HIDDEN_HEADINGS)),
        bai=[
            BaiOut(
                url=pg.url,
                tieuDe=pg.title,
                domain=pg.domain,
                ngayDang=pg.published_at,
                thuLuc=pg.fetched_at,
                loai=pg.url in excluded,
            )
            for pg in pages
        ],
        dangChay=bool(job and job["state"] in ("queued", "running")),
    )


async def refresh_project(pool: asyncpg.Pool, tenant: str, user_id: str, code: str, mode: str) -> JobOut:
    if mode not in (MODE_INIT, MODE_REBUILD):
        raise _loi("MODE_KHONG_HOP_LE", 422, "mode phải là init hoặc rebuild")
    async with tenant_conn(pool, tenant) as c:
        await _project(c, code)
        job_id = await enqueue_web_project(c, tenant_id=tenant, actor=user_id, project_code=code, mode=mode)
        if job_id is None:
            raise _loi("DANG_CHAY", 409, "Hồ sơ dự án này đang chờ được dựng")
        await nhat_ky.ghi(c, tenant, "kb_web.chay", user_id, {"mode": mode, "project_code": code, "job_id": job_id})
        r = await admin_repo.get_job(c, job_id)
    return job_out(r)


async def set_item_hidden(pool: asyncpg.Pool, tenant: str, user_id: str, code: str, heading: str, hidden: bool) -> None:
    async with tenant_conn(pool, tenant) as c:
        await _project(c, code)
        await admin_repo.set_hidden(c, code, heading.strip(), hidden, user_id)
        await nhat_ky.ghi(c, tenant, "kb_web.ho_so_sua", user_id, {"project_code": code, "muc": heading, "an": hidden})


async def set_page_excluded(pool: asyncpg.Pool, tenant: str, user_id: str, code: str, url: str, excluded: bool) -> None:
    async with tenant_conn(pool, tenant) as c:
        await _project(c, code)
        await admin_repo.set_excluded(c, code, url.strip(), excluded, user_id)
        await nhat_ky.ghi(c, tenant, "kb_web.ho_so_sua", user_id, {"project_code": code, "url": url, "loai": excluded})


# ─── nhật ký chạy ────────────────────────────────────────────────────────────


async def list_jobs(
    pool: asyncpg.Pool, tenant: str, limit: int, *, days: int | None = None, show_cost: bool = False
) -> list[JobOut]:
    async with tenant_conn(pool, tenant) as c:
        rows = await admin_repo.list_jobs(c, limit=limit, days=days)
    return [job_out(r, show_cost=show_cost) for r in rows]


async def get_job(pool: asyncpg.Pool, tenant: str, job_id: int, *, show_cost: bool = False) -> JobOut:
    async with tenant_conn(pool, tenant) as c:
        r = await admin_repo.get_job(c, job_id)
    if r is None or r["kind"] not in (KIND_RUN, KIND_PROJECT, KIND_PROBE):
        raise _loi("VIEC_KHONG_TON_TAI", 404, "Không có lượt chạy này")
    return job_out(r, show_cost=show_cost)
