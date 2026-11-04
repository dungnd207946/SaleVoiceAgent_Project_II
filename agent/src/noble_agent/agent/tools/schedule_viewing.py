"""Booking tools — schedule / list / modify viewing appointments.

Standalone (no legacy noble_agent imports). Persists to:

* Postgres ``tenant_data.appointments`` — best-effort, for the Portal read side,
  via ``storage/pg_data_plane.py::persist_appointment``. An unreachable DB doesn't
  fail the booking; the in-session view (Redis SessionState) is the source of truth
  for the conversation. The row carries ``customer_name`` and ``phone`` read from
  the Customer profile (name defaults to "No Name" when the profile has no name;
  phone is the session's real or simulated caller number).
* SessionState.scratchpad["bookings"] — JSON-encoded list of bookings for this
  session, so list_bookings/modify_booking work without the DB.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date as dt_date
from datetime import datetime

logger = logging.getLogger("noble_agent.agent.tools.schedule_viewing")

_PHONE_REGEX = re.compile(r"^(0[35789])\d{8}$")

_BOOKINGS_KEY = "bookings"
# Per-session counter for the schedule name/phone guard. Reset to 0 on a
# successful schedule; caps the number of "ask the caller" rounds at 2.
_GUARD_KEY = "booking_guard_attempts"
_GUARD_MAX_ASKS = 2


def _load_bookings(state) -> list[dict]:
    raw = state.scratchpad.get(_BOOKINGS_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.warning("bookings scratchpad corrupt; resetting")
        return []


def _save_bookings(state, bookings: list[dict]) -> None:
    state.scratchpad[_BOOKINGS_KEY] = json.dumps(bookings, ensure_ascii=False, default=str)


async def _persist_flat(booking: dict, session_id: str) -> None:
    """Best-effort appointment write to Postgres (SP-E2, keyed on appointment_id).

    Redis SessionState is the in-session source of truth; this row is for the
    Portal read side. PG unconfigured/unreachable → no-op (never fails the call).
    """
    try:
        from noble_agent.storage.pg_data_plane import persist_appointment

        await persist_appointment(booking, session_id)
    except Exception as exc:
        logger.warning("schedule_viewing: appointment write failed (%s) — continuing", exc)


def _normalize_and_validate(project: str, preferred_date: str) -> tuple[str, list[str]]:
    from noble_agent.agent import catalog

    errors: list[str] = []
    norm_project = catalog.normalize(project)
    if not norm_project:
        errors.append(f"Dự án '{project}' không hợp lệ hoặc chưa được cung cấp")
    try:
        d = datetime.strptime((preferred_date or "").strip(), "%d/%m/%Y").date()
        if d < dt_date.today():
            errors.append("Ngày tham quan không được là ngày trong quá khứ")
    except ValueError:
        errors.append("Định dạng ngày không hợp lệ (dùng DD/MM/YYYY)")
    return norm_project, errors


async def schedule_viewing(state, customer, args: dict, session_id: str) -> str:
    project = args.get("project") or customer.project_interest or ""
    preferred_date = args.get("preferred_date", "")
    preferred_time = args.get("preferred_time", "")
    notes = args.get("notes", "")
    confirmed = bool(args.get("confirmed", False))

    if not confirmed:
        return json.dumps(
            {
                "ok": False,
                "success": False,
                "error": "Chưa có xác nhận từ khách hàng. Vui lòng xác nhận thông tin trước.",
            },
            ensure_ascii=False,
        )

    norm_project, errors = _normalize_and_validate(project, preferred_date)
    if errors:
        return json.dumps(
            {"ok": False, "success": False, "errors": errors, "message": "; ".join(errors)},
            ensure_ascii=False,
        )

    given_phone = re.sub(r"[\s.\-]", "", str(args.get("phone") or ""))
    if given_phone and not _PHONE_REGEX.match(given_phone):
        return json.dumps(
            {
                "ok": False,
                "success": False,
                "error": (
                    "Số điện thoại không hợp lệ (cần 10 số, đầu 03/05/07/08/09). Hỏi lại khách số dùng để đặt lịch."
                ),
            },
            ensure_ascii=False,
        )

    # Guard: schedule needs a name AND a confirmed booking phone, both supplied
    # per-booking (decoupled from the session profile — a name read for this
    # booking never mutates the Customer). Name mirrors phone exactly:
    #   name="..."           → a name read out for this booking
    #   use_profile_name=True → caller confirmed using the profile name
    #   phone="..." / use_calling_phone=True → the phone equivalents
    # The agent must ASK, never auto-take the profile name/number. Drive the LLM
    # with a specific instruction each turn (code-driven, not prompt-only). Ask
    # at most twice; the 3rd attempt auto-proceeds with the profile name (or
    # "No Name") + the calling number so an uncooperative caller isn't stuck.
    given_name = str(args.get("name") or "").strip()
    profile_name = (customer.full_name or customer.name or "").strip()
    # use_profile_name / use_calling_phone only count as confirmation when the
    # profile ACTUALLY holds that value. If the agent sets a flag prematurely with
    # no profile name (or no calling number), don't short-circuit — keep asking up
    # to the cap so "No Name"/empty phone is only chosen after the caller is really
    # asked twice.
    has_name = bool(given_name) or (bool(args.get("use_profile_name")) and bool(profile_name))
    phone_confirmed = bool(given_phone) or (bool(args.get("use_calling_phone")) and bool(customer.phone))
    attempts = int(state.scratchpad.get(_GUARD_KEY, 0))
    if not (has_name and phone_confirmed) and attempts < _GUARD_MAX_ASKS:
        state.scratchpad[_GUARD_KEY] = attempts + 1
        if not has_name and not phone_confirmed:
            msg = (
                "Chưa có tên đặt lịch và chưa xác nhận số điện thoại. Hãy hỏi tên người đặt lịch "
                "(có thể dùng tên trong hồ sơ), và hỏi khách có dùng số đang gọi để đặt lịch không "
                "(hoặc cho số điện thoại khác)."
            )
        elif has_name:
            msg = (
                "Chưa xác nhận số điện thoại đặt lịch. Hãy hỏi khách có dùng số đang gọi này "
                "để đặt lịch không (hoặc cho số điện thoại khác)."
            )
        else:  # phone confirmed but no name
            msg = (
                "Chưa có tên đặt lịch. Hãy hỏi tên người đặt lịch, hoặc hỏi khách có dùng "
                "tên trong hồ sơ để đặt lịch không."
            )
        return json.dumps({"ok": False, "success": False, "needs_info": True, "message": msg}, ensure_ascii=False)

    booking_phone = given_phone or customer.phone or ""
    # full_name-first — matches the CUSTOMER_PROFILE block the agent reads
    # ("Tên: full_name or name"), so what the agent verbalises == what is stored.
    customer_name = given_name or customer.full_name or customer.name or "No Name"

    bookings = _load_bookings(state)
    for b in bookings:
        if (
            b.get("project", "").upper() == norm_project.upper()
            and b.get("preferred_date") == preferred_date
            and b.get("preferred_time") == preferred_time
        ):
            return json.dumps(
                {
                    "ok": False,
                    "success": False,
                    "duplicate": True,
                    "error": (
                        f"Đã có lịch xem {norm_project} vào {preferred_time} "
                        f"ngày {preferred_date}. Vui lòng chọn thời gian khác."
                    ),
                },
                ensure_ascii=False,
            )

    appt_id = f"APT{random.randint(10000, 99999)}"
    booking = {
        "appointment_id": appt_id,
        "session_id": session_id,
        "phone": booking_phone,
        "customer_name": customer_name,
        "project": norm_project,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
        "status": "confirmed",
    }
    bookings.append(booking)
    _save_bookings(state, bookings)
    state.scratchpad[_GUARD_KEY] = 0  # sequence complete — reset the ask counter

    # Best-effort appointment row for the Portal read side — a DB outage never
    # fails the booking (the scratchpad is the truth).
    await _persist_flat(booking, session_id)

    customer.project_interest = norm_project

    return json.dumps(
        {
            "ok": True,
            "success": True,
            "appointment_id": appt_id,
            "project": norm_project,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "notes": notes,
            "message": "Đặt lịch thành công.",
        },
        ensure_ascii=False,
        default=str,
    )


async def list_bookings(state) -> str:
    bookings = _load_bookings(state)
    if not bookings:
        return json.dumps(
            {
                "bookings": [],
                "count": 0,
                "message": "Chưa có lịch tham quan nào được đặt trong phiên này.",
            },
            ensure_ascii=False,
        )
    return json.dumps({"bookings": bookings, "count": len(bookings)}, ensure_ascii=False)


async def modify_booking(state, customer, args: dict) -> str:
    """Change ONLY the fields supplied; everything else keeps its current value.

    Supports date/time AND name/phone edits (e.g. "đổi số đặt lịch",
    "đặt hộ vợ tên Linh"). No confirmation flags here — modify operates on an
    existing booking that already carries a name/phone, so any explicit `name`/
    `phone` is applied as-is and omitted fields are left untouched (never wiped).
    """
    booking_id = args.get("booking_id", "")
    new_date = args.get("new_preferred_date", "")
    new_time = args.get("new_preferred_time", "")
    new_name = str(args.get("name") or "").strip()
    new_phone = re.sub(r"[\s.\-]", "", str(args.get("phone") or ""))
    if new_phone and not _PHONE_REGEX.match(new_phone):
        return json.dumps(
            {
                "ok": False,
                "success": False,
                "error": (
                    "Số điện thoại không hợp lệ (cần 10 số, đầu 03/05/07/08/09). Hỏi lại khách số dùng để đặt lịch."
                ),
            },
            ensure_ascii=False,
        )

    bookings = _load_bookings(state)
    for b in bookings:
        if b.get("appointment_id") != booking_id:
            continue
        # Effective slot after the edit (new value if given, else the current one).
        target_date = new_date or b.get("preferred_date", "")
        target_time = new_time or b.get("preferred_time", "")
        if (new_date or new_time) and any(
            other.get("appointment_id") != booking_id
            and other.get("project", "").lower() == b.get("project", "").lower()
            and other.get("preferred_date") == target_date
            and other.get("preferred_time") == target_time
            for other in bookings
        ):
            return json.dumps(
                {
                    "ok": False,
                    "success": False,
                    "error": (f"Đã có lịch xem {b['project']} vào {target_time} ngày {target_date}."),
                },
                ensure_ascii=False,
            )
        old_date = b.get("preferred_date")
        old_time = b.get("preferred_time")
        # Apply only the supplied fields; leave the rest as-is.
        if new_date:
            b["preferred_date"] = new_date
        if new_time:
            b["preferred_time"] = new_time
        if new_name:
            b["customer_name"] = new_name
        if new_phone:
            b["phone"] = new_phone
        # Safety for legacy rows that predate name/phone (full_name-first, matches schedule).
        b.setdefault("phone", customer.phone or "")
        b.setdefault("customer_name", customer.full_name or customer.name or "No Name")
        _save_bookings(state, bookings)

        await _persist_flat(b, b.get("session_id", ""))

        return json.dumps(
            {
                "ok": True,
                "success": True,
                "appointment_id": booking_id,
                "project": b.get("project"),
                "old_date": old_date,
                "old_time": old_time,
                "new_date": b.get("preferred_date"),
                "new_time": b.get("preferred_time"),
                # Echo stored name/phone so the agent's spoken confirmation can't drift.
                "customer_name": b.get("customer_name"),
                "phone": b.get("phone"),
                "message": "Đổi lịch thành công.",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"ok": False, "success": False, "error": f"Không tìm thấy lịch hẹn {booking_id}."},
        ensure_ascii=False,
    )
