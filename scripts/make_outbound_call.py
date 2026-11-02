"""Place an outbound call via FreePBX ARI → agent bridges via AudioSocket.

Prereq:
  1. `TELEPHONY_ENABLED=true` and `ASTERISK_ARI_PASSWORD=...` in `.env`.
  2. Agent is running (`scripts/run.sh`) and its AudioSocket port (8090) is
     reachable at the IP configured in the `[noble-agent-outbound]` dialplan
     context on the FreePBX server.

Usage:
  python scripts/make_outbound_call.py 0912345678
  python scripts/make_outbound_call.py 0912345678 --caller-id 18006112
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as a standalone script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from noble_agent.config import settings  # noqa: E402
from noble_agent.telephony.ari_client import ARIClient  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Outbound call smoke test")
    parser.add_argument("number", help="Callee phone number (e.g. 0912345678)")
    parser.add_argument("--caller-id", default=None,
                        help=f"Override outbound callerID (default: {settings.asterisk_outbound_callerid})")
    parser.add_argument("--context", default=None,
                        help=f"Dialplan context (default: {settings.asterisk_outbound_context})")
    parser.add_argument("--timeout", type=int, default=None,
                        help=f"Ring timeout in seconds (default: {settings.asterisk_outbound_timeout})")
    args = parser.parse_args()

    if not settings.asterisk_ari_password:
        print("ERROR: ASTERISK_ARI_PASSWORD not set in .env", file=sys.stderr)
        return 1

    client = ARIClient()
    try:
        if not await client.check_connection():
            print(f"ERROR: ARI unreachable at "
                  f"{settings.asterisk_host}:{settings.asterisk_ari_port}",
                  file=sys.stderr)
            return 2

        print(f"Calling {args.number} via PJSIP/{settings.asterisk_sip_trunk} ...")
        print(f"  callerID : {args.caller_id or settings.asterisk_outbound_callerid}")
        print(f"  context  : {args.context or settings.asterisk_outbound_context}")
        print(f"  timeout  : {args.timeout or settings.asterisk_outbound_timeout}s")

        result = await client.originate_channel(
            number=args.number,
            caller_id=args.caller_id,
            context=args.context,
            timeout=args.timeout,
        )

        if not result:
            print("FAILED: originate rejected (see agent logs and FreePBX "
                  "Asterisk CLI output). Common causes: bad trunk name, "
                  "callerID not permitted by trunk, number formatting.",
                  file=sys.stderr)
            return 3

        print(f"OK  channel_id={result.get('id')}  state={result.get('state')}")
        print("Watch the agent log — when callee picks up, AudioSocket connects "
              "and the greeting plays.")
        return 0
    finally:
        await client.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
