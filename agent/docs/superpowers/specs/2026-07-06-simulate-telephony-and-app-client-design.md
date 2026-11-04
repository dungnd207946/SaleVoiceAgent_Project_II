# Simulate telephony & app-client for testing — Design

**Date:** 2026-07-06
**Branch:** `feat/refactor2`
**Status:** Approved (design)

## Problem

`chat` (`/chat`) and `voice LiveKit` both establish their caller identity via
`facade.ensure_session_started` → a **random** VN mobile (when
`NOBLE_SIMULATE_PHONE=true`, the default). A random number always 0-hits the DB,
so neither path can exercise the real customer-profile feature:

- **Telephony scenario** (case 2): a phone that maps to a *known* DB customer,
  so the first-turn bootstrap (`customers` + `bookings_flat` by phone) returns a
  real profile into the frozen block.
- **App-client scenario** (case 1): a phone **plus** pushed profile fields
  (name/gender/…) — mirroring the browser `set_customer` push — so the bootstrap
  merges DB on top (DB wins) exactly as the real app-client path does.

We want the simulated-phone mechanism to reproduce **both** scenarios so the
feature can be tested end-to-end from chat / LiveKit without a real PSTN call or
app client.

## Approach

Global env config read in `ensure_session_started` (the single choke point that
feeds both chat and LiveKit). No per-transport wiring. Both scenarios run through
the **real** first-turn bootstrap — this is faithful simulation, not a fixture.

### Config (config.py)

| Env | Default | Meaning |
|---|---|---|
| `NOBLE_SIMULATE_PHONE` | `true` | Master switch (existing). |
| `NOBLE_SIMULATE_PHONE_NUMBER` | `""` | Fixed caller phone. `""` → random (current behaviour). Set a number present in `customers`/`bookings_flat` to exercise the DB lookup. |
| `NOBLE_SIMULATE_CUSTOMER` | `""` | JSON object of `Customer` fields to seed (simulates the app-client `set_customer` push). `""` → telephony-sim (phone only). |

### Behaviour in `ensure_session_started` (only when `NOBLE_SIMULATE_PHONE=true` and `customer.phone` empty)

1. **Phone** = `NOBLE_SIMULATE_PHONE_NUMBER` if set, else the `"phone"` key inside
   `NOBLE_SIMULATE_CUSTOMER` if present, else `_random_vn_mobile()`.
2. **Profile seed** (app-client-sim): parse `NOBLE_SIMULATE_CUSTOMER` as JSON;
   keep only keys that are valid `Customer` model fields **and** have a non-empty
   value (`isinstance(v, bool) or v`); drop `phone` (owned by step 1); merge into
   the customer and validate via `Customer.model_validate`. Faithful to
   `set_customer_fields` semantics.
3. Persist as today (`meta.phone` mirror + `repo.save_all` + `call_started`).

Then the **existing** first-turn bootstrap runs unchanged: phone → DB
(`customers` + latest `bookings_flat`), **DB wins** over seeded values. Result:

- **telephony-sim** (`NOBLE_SIMULATE_CUSTOMER` empty): block = phone + whatever DB
  has for that phone.
- **app-client-sim** (`NOBLE_SIMULATE_CUSTOMER` set): block = seeded fields merged
  with DB (DB overrides where it has data) — exactly the real app-client merge.

### Robustness

- Invalid JSON, non-object JSON, unknown fields, empty values, or a
  `ValidationError` (e.g. `gender:"X"`) → **log a warning and ignore the seed**;
  the phone is still set so the session never fails to start.
- `ensure_session_started` already runs under a broad `try/except`
  (`facade.py`), so a seed problem can never wedge session start.

## Example `.env`

```bash
# Telephony-sim, unknown caller → block has only the phone
NOBLE_SIMULATE_PHONE_NUMBER=0912000000

# Telephony-sim, returning customer → block shows the DB profile
NOBLE_SIMULATE_PHONE_NUMBER=<a phone present in customers/bookings_flat>

# App-client-sim → seeded name/gender + DB merge (DB wins)
NOBLE_SIMULATE_PHONE_NUMBER=<phone>
NOBLE_SIMULATE_CUSTOMER={"name":"Hùng","gender":"M","project_interest":"NPTTL"}
```

## Files touched

| File | Change |
|---|---|
| `config.py` | add `simulate_phone_number`, `simulate_customer` fields |
| `agent/facade.py` | `ensure_session_started` reads the two envs; new `_apply_sim_customer` helper |
| `.env.example` | document the two envs + the two scenarios |
| CLAUDE.md | change-log row |

## Testing

- `ensure_session_started` with `NOBLE_SIMULATE_PHONE_NUMBER` set → `customer.phone`
  is exactly that number (not random).
- With `NOBLE_SIMULATE_CUSTOMER` valid JSON → non-empty `Customer` fields seeded;
  `phone` key inside it ignored in favour of `NOBLE_SIMULATE_PHONE_NUMBER`.
- Invalid JSON / invalid `gender` / empty values → ignored, phone still set, no raise.
- `NOBLE_SIMULATE_PHONE=false` → no phone, no seed (unchanged).
- `_apply_sim_customer` unit-tested in isolation (parse/filter/validate) with a
  fake customer.

## Scope / non-goals

- Covers chat + LiveKit uniformly (shared `ensure_session_started`). Real
  telephony / browser transports are untouched (they set their own phone).
- No per-session override (query param) — global env only, per the chosen approach.
- DB precedence in the bootstrap is unchanged; this only seeds the pre-bootstrap
  customer, so seeded values behave like app-pushed ones.
