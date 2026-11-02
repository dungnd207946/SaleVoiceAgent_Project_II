"""Unified booking tool — dispatches by `action` field.

Router mỏng: check_availability / schedule / list / modify. Impl nằm ở
availability.py (ngày+giờ trống) và schedule_viewing.py (chốt/liệt kê/đổi lịch).
Khách chỉ cần cung cấp dự án + ngày + giờ; tên khách KHÔNG hỏi trong tool này
(mặc định "No Name" từ hồ sơ Customer). Action `schedule` có thể nhận `phone`
tường minh (số khách xác nhận dùng để đặt lịch) và forward xuống
schedule_viewing; nếu không có, schedule_viewing tự fallback về số của
phiên/cuộc gọi mô phỏng trong hồ sơ Customer.
"""

from __future__ import annotations

import json

from noble_agent.agent.tools import availability, schedule_viewing


async def run(state, customer, args: dict, session_id: str) -> str:
    action = (args.get("action") or "").strip()

    if action == "check_availability":
        project = args.get("project_code") or customer.project_interest or ""
        return await availability.check_availability(
            {
                "project_code": project,
                "preferred_date": args.get("preferred_date", ""),
                "preferred_time": args.get("preferred_time", ""),
            }
        )
    if action == "schedule":
        forward = {
            "preferred_date": args.get("preferred_date", ""),
            "preferred_time": args.get("preferred_time", ""),
            "notes": args.get("notes", ""),
            "confirmed": args.get("confirmed", False),
            "project": args.get("project_code", ""),
            "phone": args.get("phone", ""),
            "use_calling_phone": args.get("use_calling_phone", False),
            "name": args.get("name", ""),
            "use_profile_name": args.get("use_profile_name", False),
        }
        return await schedule_viewing.schedule_viewing(state, customer, forward, session_id=session_id)
    if action == "list":
        return await schedule_viewing.list_bookings(state)
    if action == "modify":
        return await schedule_viewing.modify_booking(state, customer, args)

    return json.dumps(
        {"ok": False, "error": f"Unknown booking action: {action!r}"},
        ensure_ascii=False,
    )
