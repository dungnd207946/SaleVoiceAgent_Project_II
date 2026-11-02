"""Grounding qua Gemini 2.5 Flash (Google Search tool) + trần lượt gọi mỗi ngày.

Trần dùng Redis `INCRBY` khi có Redis (an toàn dưới nhiều tiến trình gọi đồng thời,
cùng khuôn `ingest/nhip.py::cho_qua`), hoặc một bộ đếm cục bộ khi không (một tiến
trình, không cần atomic). Ngày tính theo GIỜ VN — khớp lịch chạy job thật, không phải
giờ UTC của host.

Link Gemini grounding trả về là một REDIRECT
(`vertexaisearch.cloud.google.com/grounding-api-redirect/...`), không phải URL bài
viết gốc. Đọc header `Location` của lượt redirect (KHÔNG follow) mới ra URL gốc —
theo hẳn redirect là tải luôn trang đích, tốn một lượt mạng không cần thiết ở bước
chỉ cần biết URL.
"""

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from redis.asyncio import Redis

from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.netguard import Resolve, is_public_url
from portal.modules.kb.web.usage import GOOGLE, meter

log = logging.getLogger(__name__)

VN = ZoneInfo("Asia/Ho_Chi_Minh")
_API = "https://generativelanguage.googleapis.com/v1beta/models"
_REDIRECT_MARK = "grounding-api-redirect"
_KEY_PREFIX = "kbweb:grounding:"
_TTL_SEC = 2 * 86400  # sống qua nửa đêm, key sau tự đổi theo ngày mới
_TTL_MONTH_SEC = 40 * 86400


class TemporaryGroundingError(TemporaryError):
    """429/5xx/timeout khi gọi Gemini: job phải thử lại."""


class GroundingUnreachable(TemporaryGroundingError):
    """Không tới được Gemini (DNS, kết nối, quá giờ): lỗi mạng phía mình, cả lượt chạy lại sau."""


def _key_for(day: date) -> str:
    return f"{_KEY_PREFIX}{day:%Y%m%d}"


def _month_key(tenant: str, day: date) -> str:
    return f"{_KEY_PREFIX}{tenant}:{day:%Y-%m}"


class GroundingBudget:
    """Trần lượt gọi Gemini grounding mỗi ngày (giờ VN).

    Nhánh Redis: `INCRBY` rồi mới kiểm — atomic dưới nhiều tiến trình, cùng khuôn
    `nhip.cho_qua`. Hệ quả: một lượt bị TỪ CHỐI vẫn làm bộ đếm tăng (không lùi lại) —
    chấp nhận được vì kết quả (từ chối) không đổi cho các lượt sau trong cùng ngày,
    và tránh được race kiểu "kiểm rồi mới tăng" giữa nhiều tiến trình.

    Nhánh cục bộ (không Redis): một tiến trình, không có ai để giành — lượt bị từ
    chối KHÔNG tăng bộ đếm.

    TTL vá lại kiểu "mồ côi" giống `nhip.cho_qua`: nếu tiến trình chết đúng giữa
    `incrby` và `expire` lần trước, `ttl(key) < 0` phát hiện ra và đặt lại hạn ở lượt
    gọi kế tiếp — không có vế này thì bộ đếm sống vĩnh viễn dù key đã qua ngày cũ.
    """

    def __init__(self, redis: Redis | None = None, *, cap: int, tenant: str = "", monthly_cap: int = 0) -> None:
        """`cap` = trần NGÀY toàn hệ (lưới an toàn); `tenant` + `monthly_cap` = trần THÁNG của một tenant
        (`kbweb_limits.grounding_monthly`), kiểm sau trần ngày."""
        self._redis = redis
        self._cap = cap
        self._tenant = tenant
        self._monthly_cap = monthly_cap
        self._local = 0
        self._local_month = 0
        self.exhausted = False
        """Kết quả `take()` gần nhất bị từ chối."""

    async def take(self, n: int = 1) -> bool:
        ok = await self._take(n)
        self.exhausted = not ok
        return ok

    async def _take(self, n: int) -> bool:
        today = datetime.now(VN).date()
        if self._redis is None:
            if self._local + n > self._cap or (self._monthly_cap and self._local_month + n > self._monthly_cap):
                return False
            self._local += n
            self._local_month += n
            return True

        if not await self._incr(_key_for(today), n, self._cap, _TTL_SEC):
            return False
        if self._tenant and self._monthly_cap:
            return await self._incr(_month_key(self._tenant, today), n, self._monthly_cap, _TTL_MONTH_SEC)
        return True

    async def _incr(self, key: str, n: int, cap: int, ttl: int) -> bool:
        used = await self._redis.incrby(key, n)
        if used == n or await self._redis.ttl(key) < 0:
            await self._redis.expire(key, ttl)
        return used <= cap


class Grounding:
    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        budget: GroundingBudget,
        model: str,
        resolve: Resolve | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("thiếu KB_GEMINI_API_KEY")
        self._key = api_key
        self._http = http
        self._budget = budget
        self._model = model
        self._resolve_host = resolve

    @property
    def exhausted(self) -> bool:
        """`search()` vừa trả `[]` vì hết trần ngày, không phải vì Gemini không tìm ra gì."""
        return self._budget.exhausted

    async def search(self, query: str) -> list[str]:
        """Trả URL bài viết GỐC (đã resolve khỏi redirect), bỏ link không lấy được.

        Kiểm trần TRƯỚC khi gọi mạng — hết trần thì trả `[]` mà không chạm HTTP.
        """
        if not await self._budget.take():
            return []
        try:
            r = await self._http.post(
                f"{_API}/{self._model}:generateContent",
                headers={"x-goog-api-key": self._key},
                json={"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise GroundingUnreachable(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise TemporaryGroundingError(f"Gemini {r.status_code}: {r.text[:200]}")
        r.raise_for_status()

        data = r.json()
        if (m := meter()) is not None:
            m.search(self._model)
            used = data.get("usageMetadata") or {}
            m.llm(
                GOOGLE,
                self._model,
                int(used.get("promptTokenCount") or 0),
                int(used.get("candidatesTokenCount") or 0) + int(used.get("thoughtsTokenCount") or 0),
            )
        candidates = data.get("candidates") or [{}]
        chunks = (candidates[0].get("groundingMetadata") or {}).get("groundingChunks") or []
        uris = [c["web"]["uri"] for c in chunks if (c.get("web") or {}).get("uri")]

        resolved = await asyncio.gather(*(self._resolve(u) for u in uris))
        seen: set[str] = set()
        out: list[str] = []
        for u in resolved:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    async def _resolve(self, uri: str) -> str:
        """Link grounding-redirect thì đọc header `Location`, KHÔNG follow. Link khác
        (không mang dấu redirect) giữ nguyên, coi như đã là URL gốc — `Fetcher` kiểm nó khi tải.
        Link redirect và đích của nó phải là URL công khai, không thì bỏ."""
        if _REDIRECT_MARK not in uri:
            return uri
        if not await is_public_url(uri, self._resolve_host):
            log.debug("bỏ link grounding không công khai: %s", uri)
            return ""
        try:
            r = await self._http.get(uri, follow_redirects=False)
        except httpx.HTTPError:
            return ""
        location = r.headers.get("location", "")
        if not await is_public_url(location, self._resolve_host):
            log.debug("bỏ đích redirect grounding không công khai: %r", location)
            return ""
        return location
