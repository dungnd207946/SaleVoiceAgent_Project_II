"""Job `kbweb_probe`: chạy `Prober` trong crawl-worker (nơi có trình duyệt), ghi kết quả JSON vào Redis
để API trả cho màn hình đang poll (`GET /kb-web/sources/probe/{token}`)."""

import json
import logging
from dataclasses import asdict
from datetime import datetime

from portal.core.jobs import JobResult
from portal.modules.kb.web import pipeline
from portal.modules.kb.web.contracts import PROBE_RESULT_TTL_SEC
from portal.modules.kb.web.discover import VN
from portal.modules.kb.web.probe import Prober, ProbeResult

log = logging.getLogger(__name__)


def result_key(tenant: str, token: str) -> str:
    return f"kbweb:probe:{tenant}:{token}"


def to_json(r: ProbeResult) -> str:
    d = asdict(r)
    d["site"] = asdict(r.site) if r.site else None
    return json.dumps(d, ensure_ascii=False)


async def run(rt: pipeline.Runtime, deps: pipeline.Deps, url: str, token: str) -> JobResult:
    if not url or not token:
        raise ValueError("kbweb_probe cần url và token")
    prober = Prober(http=rt.http, discover=rt.discover, fetcher=deps.fetcher, browser=rt.browser)
    r = await prober.probe(url, today=datetime.now(VN).date())
    if rt.redis is None:
        raise RuntimeError("kbweb_probe cần Redis để trả kết quả cho màn hình")
    await rt.redis.set(result_key(deps.tenant, token), to_json(r), ex=PROBE_RESULT_TTL_SEC)
    return JobResult(count=r.articles, message=f"{r.url}: {r.status}")
