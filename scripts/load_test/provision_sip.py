"""Provision the LiveKit SIP inbound trunk + dispatch rule for the load test.

Why this exists: the `lk` CLI's JSON parser rejects valid
`CreateSIPDispatchRuleRequest` payloads ("missing rule") — and its
flag-based shortcut has no `--agent-name`, so explicit agent dispatch
can't be wired from the CLI. We talk to the Twirp API directly via the
`livekit.api` Python client where the proto schema is correct.

Idempotent: re-running wipes trunks/rules named `loadtest-*` and
recreates them. Safe to run at the start of every load-test session.

Usage:
    uv run python scripts/load_test/provision_sip.py
    uv run python scripts/load_test/provision_sip.py --delete-only
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from livekit import api


TRUNK_NAME = "loadtest-trunk"
RULE_NAME = "loadtest-dispatch"
TRUNK_NUMBER = "+84999000001"
AGENT_NAME = "noble-hotline-agent"


def _creds() -> tuple[str, str, str]:
    url = os.environ.get("LIVEKIT_URL", "http://localhost:7880")
    key = os.environ.get("LIVEKIT_API_KEY", "devkey")
    secret = os.environ.get(
        "LIVEKIT_API_SECRET",
        "devsecret_change_me_for_prod_1234567890abcdef",
    )
    return url, key, secret


async def _purge_existing(client: api.LiveKitAPI) -> None:
    rules = await client.sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
    for r in rules.items:
        if r.name.startswith("loadtest"):
            await client.sip.delete_sip_dispatch_rule(
                api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=r.sip_dispatch_rule_id)
            )
            print(f"deleted dispatch rule {r.sip_dispatch_rule_id} ({r.name!r})")

    trunks = await client.sip.list_sip_inbound_trunk(api.ListSIPInboundTrunkRequest())
    for t in trunks.items:
        if t.name.startswith("loadtest"):
            await client.sip.delete_sip_trunk(
                api.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id)
            )
            print(f"deleted trunk {t.sip_trunk_id} ({t.name!r})")


async def _provision(client: api.LiveKitAPI) -> tuple[str, str]:
    trunk_req = api.CreateSIPInboundTrunkRequest(
        trunk=api.SIPInboundTrunkInfo(
            name=TRUNK_NAME,
            numbers=[TRUNK_NUMBER],
            # macOS Docker Desktop NATs the source IP to an opaque public
            # address, so a tight CIDR never matches. 0.0.0.0/0 is safe
            # for local load-testing only.
            allowed_addresses=["0.0.0.0/0"],
        )
    )
    trunk = await client.sip.create_sip_inbound_trunk(trunk_req)
    print(f"created trunk {trunk.sip_trunk_id} ({trunk.name!r})")

    rule_req = api.CreateSIPDispatchRuleRequest(
        dispatch_rule=api.SIPDispatchRuleInfo(
            name=RULE_NAME,
            trunk_ids=[trunk.sip_trunk_id],
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                    room_prefix="loadtest",
                ),
            ),
            room_config=api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)],
            ),
        )
    )
    rule = await client.sip.create_sip_dispatch_rule(rule_req)
    print(f"created dispatch rule {rule.sip_dispatch_rule_id} ({rule.name!r}) -> agent={AGENT_NAME}")
    return trunk.sip_trunk_id, rule.sip_dispatch_rule_id


async def _amain(args: argparse.Namespace) -> int:
    url, key, secret = _creds()
    print(f"target: {url}")
    async with api.LiveKitAPI(url=url, api_key=key, api_secret=secret) as client:
        await _purge_existing(client)
        if args.delete_only:
            print("done (delete-only).")
            return 0
        await _provision(client)
        print("done.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--delete-only", action="store_true",
                    help="Only wipe loadtest-* trunks and rules; don't recreate.")
    args = ap.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
