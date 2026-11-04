"""Nạp credential Postgres per-tenant cho lượt `evals run`.

Harness drive agent IN-PROCESS nên không có hop gateway — mà gateway chính là chỗ
duy nhất trong production đổi API key thành PG role/password per-tenant rồi đăng ký
vào `storage.tenant_credentials`. Không có entry đó, `pool_for_tenant` rơi về shared
`POSTGRES_DSN`; với tenant dùng per-tenant role thì RLS trả **0 row chứ không lỗi** và
agent chết bằng `RuntimeError: no published config for tenant '<id>'` ở CẢ 100 case.

Đặt `EVAL_TENANT_API_KEY` = API key gateway của tenant để harness tự làm việc đó.
Không đặt → no-op (tenant chạy trên shared DSN như `noble`/`du_test` không cần gì).

Lazy import `noble_agent` để `list`/`score`/selftest vẫn chạy được mà không cần agent.
"""

from __future__ import annotations

import os

ENV_KEY = "EVAL_TENANT_API_KEY"


class CredentialError(RuntimeError):
    """Có key nhưng không đổi được thành credential — fail loud, đừng để 100 case cùng chết."""


def configured() -> bool:
    return bool(os.environ.get(ENV_KEY, "").strip())


async def ensure(tenant_id: str) -> bool:
    """Bảo đảm registry có credential CÒN HẠN cho `tenant_id`.

    Trả `True` nếu vừa fetch mới, `False` nếu không cần (đã còn hạn, hoặc chưa cấu hình
    `EVAL_TENANT_API_KEY`). Raise `CredentialError` khi có key mà lấy không được.

    Gọi được nhiều lần: credential per-tenant chỉ sống ~1 giờ, còn một lượt 100 case
    chạy tuần tự có thể lâu hơn thế — nên driver gọi hàm này TRƯỚC MỖI CASE và nó tự
    fetch lại đúng lúc hết hạn (`tenant_credentials.get` trả None khi quá `expires_at`).
    Không gọi lại khi còn hạn vì auth API có rate-limit (429).
    """
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        return False

    from noble_agent.storage import tenant_credentials

    if tenant_credentials.get(tenant_id) is not None:
        return False

    from noble_agent.config import get_settings
    from noble_agent.gateway.credentials import CredentialsClient, CredentialsError

    settings = get_settings()
    if not settings.gateway_credentials_api_url:
        raise CredentialError(
            f"{ENV_KEY} đã đặt nhưng GATEWAY_CREDENTIALS_API_URL trống — không có chỗ đổi key"
        )
    client = CredentialsClient(settings.gateway_credentials_api_url, settings.gateway_cred_cache_ttl_sec)
    try:
        creds = await client.authorize(key)
    except CredentialsError as exc:
        raise CredentialError(
            f"{ENV_KEY} không đổi được credential ({exc.reason}). "
            "bad_credential = key sai/đã revoke; auth_api_unavailable = API không trả lời "
            "hoặc đang rate-limit (429) — chờ rồi thử lại."
        ) from exc
    finally:
        await client.aclose()

    # Key gắn nhãn "aina…" có thể thuộc `aina_prod`: đăng ký sai tenant thì pool đúng
    # role nhưng `app.current_tenant` là tenant khác ⇒ lại 0 row, lại im lặng.
    if creds.tenant_id != tenant_id:
        raise CredentialError(
            f"{ENV_KEY} thuộc tenant {creds.tenant_id!r}, không phải {tenant_id!r} đang eval"
        )
    if not settings.postgres_server_dsn:
        raise CredentialError(
            "POSTGRES_SERVER_DSN trống — có credential per-tenant nhưng không lắp được vào DSN "
            "(pool_for_tenant sẽ rơi về shared pool)"
        )
    tenant_credentials.register(
        creds.tenant_id,
        role=creds.postgres_role,
        password=creds.postgres_password,
        expires_at=creds.expires_at,
        agent_key_id=creds.agent_key_id,
    )
    return True
