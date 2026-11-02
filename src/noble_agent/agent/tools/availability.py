"""check_availability — stub returning next 10 working days + fixed slots.

Wired through the unified `booking` tool (action=check_availability).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


async def check_availability(args: dict) -> str:
    project = args.get("project_code", "") or ""
    now = datetime.now(tz=_VN_TZ)
    available_dates: list[str] = []
    for i in range(1, 15):
        d = now + timedelta(days=i)
        if d.weekday() < 5:
            available_dates.append(d.strftime("%d/%m/%Y"))
    return json.dumps(
        {
            "project": project,
            "available_dates": available_dates[:10],
            "slots": ["09:00 - 10:00", "10:00 - 11:00", "14:00 - 15:00", "15:00 - 16:00"],
            "note": "Các khung giờ khả dụng trong mười bốn ngày tới (ngày làm việc).",
        },
        ensure_ascii=False,
    )
