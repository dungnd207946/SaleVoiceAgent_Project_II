"""Đọc control-plane Portal cho heartbeat, thẳng từ bảng gốc control.* (Portal
đã bỏ các view agent_api.* — 2026-08-10, agent_api sắp xoá khỏi DB). Gateway
auth không còn đọc control.* nữa — nó gọi Portal runtime-credentials API qua
gateway/credentials.py (xem gateway/auth.py). Contract:
docs/handoff/agent-postgres-read-contract.md."""
from __future__ import annotations

import logging

logger = logging.getLogger("noble_agent.storage.agent_control")

# `read_deployment_id` ĐÃ XOÁ (Portal `0941` DROP control.deployments). Nó đọc bằng
# role `agent_<tenant>` — role chưa bao giờ có SELECT trên bảng đó, nên hàm này CHƯA
# TỪNG chạy được ngoài test; nó chỉ ném rồi bị `beat()` nuốt. Nhịp tim giờ khoá theo
# `tenant_id`, không cần id nào.


async def _pool(pool):
    if pool is not None:
        return pool
    from noble_agent.storage.postgres_client import get_pool
    return await get_pool()
