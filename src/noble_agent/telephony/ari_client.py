"""Asterisk REST Interface (ARI) client — call lifecycle via WebSocket + HTTP.

Connects to Asterisk ARI to receive Stasis events (call start/end) and
control channels (answer, hangup, transfer). Auto-reconnects on failure.

Usage:
    client = ARIClient(on_stasis_start=my_handler)
    await client.connect()  # blocks, listens for events
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
import websockets

from noble_agent.config import settings

logger = logging.getLogger("telephony.ari")

# Reconnect backoff
_INITIAL_DELAY = 1.0
_MAX_DELAY = 30.0
_BACKOFF_FACTOR = 2.0


class ARIClient:
    """Async ARI client — WebSocket event listener + HTTP channel control."""

    def __init__(
        self,
        on_stasis_start: Callable[[dict], Awaitable[None]] | None = None,
        on_stasis_end: Callable[[dict], Awaitable[None]] | None = None,
        on_channel_hangup: Callable[[dict], Awaitable[None]] | None = None,
    ):
        self._on_stasis_start = on_stasis_start
        self._on_stasis_end = on_stasis_end
        self._on_channel_hangup = on_channel_hangup
        self._ws = None
        self._running = False
        self._http = httpx.AsyncClient(timeout=10.0)

    # ── HTTP Channel Control ─────────────────────────────────────────────────

    async def continue_channel(self, channel_id: str) -> bool:
        """Release the channel from the Stasis app so it resumes the dialplan.

        Part 2: after StasisStart lets us grab the caller number, we must call
        this so Asterisk moves past `Stasis(...)` to the next dialplan line
        (AudioSocket). Without it the channel hangs in Stasis forever.
        """
        try:
            resp = await self._http.post(
                f"{self._http_base}/channels/{channel_id}/continue",
                auth=self._auth,
            )
            if resp.status_code in (200, 204):
                return True
            logger.warning("continue_channel failed %s: %s %s", channel_id, resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("continue_channel error %s: %s", channel_id, exc)
            return False

    @property
    def _ws_url(self) -> str:
        scheme = "wss" if settings.asterisk_ari_scheme == "https" else "ws"
        return (
            f"{scheme}://{settings.asterisk_host}:{settings.asterisk_ari_port}"
            f"/ari/events?api_key={settings.asterisk_ari_username}:{settings.asterisk_ari_password}"
            f"&app={settings.asterisk_ari_app}"
        )

    @property
    def _http_base(self) -> str:
        return f"{settings.asterisk_ari_scheme}://{settings.asterisk_host}:{settings.asterisk_ari_port}/ari"

    @property
    def _auth(self) -> tuple[str, str]:
        return (settings.asterisk_ari_username, settings.asterisk_ari_password)

    async def connect(self):
        """Connect to ARI WebSocket and listen for events. Auto-reconnects."""
        self._running = True
        delay = _INITIAL_DELAY

        while self._running:
            try:
                logger.info("Connecting to ARI at %s:%s...", settings.asterisk_host, settings.asterisk_ari_port)
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=1 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    delay = _INITIAL_DELAY  # reset backoff on success
                    logger.info("ARI connected — listening for Stasis events (app=%s)", settings.asterisk_ari_app)

                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                            await self._dispatch(event)
                        except json.JSONDecodeError:
                            logger.warning("ARI: invalid JSON: %s", raw[:200])
                        except Exception as exc:
                            logger.error("ARI event handler error: %s", exc, exc_info=True)

            except asyncio.CancelledError:
                logger.info("ARI client cancelled")
                break
            except Exception as exc:
                logger.warning("ARI connection lost: %s — reconnecting in %.0fs", exc, delay)

            if not self._running:
                break

            await asyncio.sleep(delay)
            delay = min(delay * _BACKOFF_FACTOR, _MAX_DELAY)

        self._ws = None

    async def stop(self):
        """Stop the ARI client."""
        self._running = False
        if self._ws:
            await self._ws.close()
        await self._http.aclose()
        logger.info("ARI client stopped")

    async def _dispatch(self, event: dict):
        """Route ARI event to the appropriate handler."""
        event_type = event.get("type", "")
        ch = event.get("channel", {})
        ch_id = ch.get("id", "?")

        if event_type == "StasisStart":
            logger.info(
                "StasisStart: channel=%s caller=%s",
                ch_id,
                ch.get("caller", {}).get("number", "unknown"),
            )
            if self._on_stasis_start:
                await self._on_stasis_start(event)

        elif event_type == "StasisEnd":
            logger.info("StasisEnd: channel=%s", ch_id)
            if self._on_stasis_end:
                await self._on_stasis_end(event)

        elif event_type == "ChannelDestroyed":
            logger.info(
                "ChannelDestroyed: channel=%s cause=%s (%s)",
                ch_id,
                event.get("cause"),
                event.get("cause_txt"),
            )
            if self._on_channel_hangup:
                await self._on_channel_hangup(event)

        elif event_type in ("ChannelStateChange", "ChannelHangupRequest", "Dial"):
            # Extra visibility for outbound diagnostics — log key lifecycle
            # events so operators can tell why a trunk call didn't connect.
            if event_type == "Dial":
                logger.info(
                    "Dial: peer=%s dial_status=%r",
                    event.get("peer", {}).get("name"),
                    event.get("dialstatus"),
                )
            elif event_type == "ChannelStateChange":
                logger.info("ChannelStateChange: channel=%s state=%s", ch_id, ch.get("state"))
            else:  # ChannelHangupRequest
                logger.info(
                    "ChannelHangupRequest: channel=%s cause=%s (%s)",
                    ch_id,
                    event.get("cause"),
                    event.get("cause_txt"),
                )

    async def answer_channel(self, channel_id: str) -> bool:
        """Answer an incoming call."""
        try:
            resp = await self._http.post(
                f"{self._http_base}/channels/{channel_id}/answer",
                auth=self._auth,
            )
            if resp.status_code == 204:
                logger.info("Answered channel %s", channel_id)
                return True
            logger.warning("Answer failed: %s %s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Answer error for %s: %s", channel_id, exc)
            return False

    async def hangup_channel(self, channel_id: str, reason: str = "normal") -> bool:
        """Hang up a call."""
        try:
            resp = await self._http.delete(
                f"{self._http_base}/channels/{channel_id}",
                params={"reason_code": reason},
                auth=self._auth,
            )
            if resp.status_code in (200, 204):
                logger.info("Hung up channel %s (reason=%s)", channel_id, reason)
                return True
            logger.warning("Hangup failed: %s %s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Hangup error for %s: %s", channel_id, exc)
            return False

    async def get_channel_var(self, channel_id: str, variable: str) -> str | None:
        """Read a channel variable (e.g., CALLERID(num))."""
        try:
            resp = await self._http.get(
                f"{self._http_base}/channels/{channel_id}/variable",
                params={"variable": variable},
                auth=self._auth,
            )
            if resp.status_code == 200:
                return resp.json().get("value")
            return None
        except Exception:
            return None

    async def check_connection(self) -> bool:
        """Health check — verify ARI is reachable."""
        try:
            resp = await self._http.get(
                f"{self._http_base}/asterisk/info",
                auth=self._auth,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ── Outbound call origination ────────────────────────────────────────────

    async def originate_channel(
        self,
        number: str,
        caller_id: str | None = None,
        context: str | None = None,
        timeout: int | None = None,
        variables: dict | None = None,
    ) -> dict | None:
        """Place an outbound call via FreePBX's `from-internal` context.

        Uses `Local/<number>@from-internal` (not `PJSIP/<number>@<trunk>`) so
        that FreePBX Outbound Routes handle number normalization, trunk
        selection, and — most importantly — CID substitution. Direct PJSIP
        dial with a 1800 hotline CID is rejected by VN mobile carriers
        (SIP 4xx → cause=21 Call Rejected); going through `from-internal`
        lets the configured Outbound Route replace the CID with a valid
        mobile-callable DID before hitting the trunk.

        When the far side answers, the Local channel routes into dialplan
        `context` / extension `s` / priority 1 — which should contain
        `AudioSocket(...)` so this agent bridges audio.

        Pre-populates TelephonyManager._caller_map with the destination
        number so TelephonySession knows who it's calling (the outbound
        dialplan doesn't emit StasisStart before AudioSocket unless it
        explicitly calls Stasis()).

        Returns the channel dict on success, else None.
        """
        # Pre-populate caller_map (matches voiceagentrag behavior).
        try:
            from noble_agent.telephony import session as _tel_session

            mgr = getattr(_tel_session, "_telephony_manager", None)
            if mgr is not None:
                mgr._caller_map[f"outbound-{number}"] = number
                logger.info("Pre-populated caller_map for outbound=%s", number)
        except Exception:
            pass  # telephony manager may not be initialized in CLI-only mode

        cid_num = caller_id or settings.asterisk_outbound_callerid
        # Display-name format recommended by voiceagentrag demo: some trunk
        # providers reject raw-number CID but accept a quoted display name.
        cid = f'"Noble Agent" <{cid_num}>'

        params = {
            "endpoint": f"Local/{number}@from-internal",
            "context": context or settings.asterisk_outbound_context,
            "extension": "s",
            "priority": 1,
            "callerId": cid,
            "timeout": timeout or settings.asterisk_outbound_timeout,
        }
        body = {"variables": variables} if variables else None
        try:
            resp = await self._http.post(
                f"{self._http_base}/channels",
                params=params,
                json=body,
                auth=self._auth,
            )
            if resp.status_code in (200, 204):
                data = resp.json() if resp.content else {}
                logger.info(
                    "Originate ok: channel=%s to=%s state=%s",
                    data.get("id"),
                    number,
                    data.get("state"),
                )
                return data
            logger.error(
                "Originate failed (%s) to=%s: %s",
                resp.status_code,
                number,
                resp.text,
            )
            return None
        except Exception as exc:
            logger.error("Originate error to=%s: %s", number, exc)
            return None

    # ── SMS via SIP MESSAGE (res_pjsip_messaging) ────────────────────────────

    async def send_sip_message(
        self,
        to_number: str,
        body: str,
        from_user: str | None = None,
    ) -> tuple[bool, str]:
        """Send a SIP MESSAGE through the PJSIP trunk.

        Returns (ok, detail). `ok=True` only means Asterisk accepted the request
        (HTTP 202); the trunk provider may still reject MESSAGE downstream.
        Check Asterisk logs to confirm delivery to the cellular SMS gateway.
        """
        from_uri = f"sip:{from_user or settings.sms_from}@{settings.asterisk_host}"
        to_uri = f"pjsip:{to_number}@{settings.asterisk_sip_trunk}"
        params = {"to": to_uri, "from": from_uri}
        try:
            resp = await self._http.put(
                f"{self._http_base}/endpoints/sendMessage",
                params=params,
                json={"body": body},
                auth=self._auth,
            )
            if resp.status_code == 202:
                return True, f"accepted (202) to={to_number}"
            return False, f"http {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            return False, f"exception: {exc}"
