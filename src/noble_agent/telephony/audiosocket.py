"""AudioSocket TCP server for Asterisk — bidirectional audio streaming.

Protocol: Asterisk AudioSocket uses TLV (Type-Length-Value) frames:
  - Type:   1 byte  (0x01=UUID, 0x10=audio, 0x02=silence, 0x00=hangup, 0xFF=error)
  - Length: 2 bytes (big-endian, payload length)
  - Value:  N bytes (payload)

First message from Asterisk is always a UUID frame identifying the call.
Audio frames contain raw slin (signed linear 16-bit, 8kHz mono).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import uuid

from noble_agent.config import settings

logger = logging.getLogger("telephony.audiosocket")

# AudioSocket TLV frame types
TYPE_HANGUP = 0x00
TYPE_UUID = 0x01
TYPE_SILENCE = 0x02
TYPE_AUDIO = 0x10
TYPE_ERROR = 0xFF

# TLV header: 1 byte type + 2 bytes length
HEADER_SIZE = 3


class AudioSocketServer:
    """TCP server that accepts Asterisk AudioSocket connections.

    Each incoming TCP connection = one phone call.
    Audio is slin 16-bit @ 8kHz mono (Asterisk default).
    """

    def __init__(
        self,
        on_new_call,
        host: str = "",
        port: int = 8090,
    ):
        """
        Args:
            on_new_call: async callback(call_id, reader, writer) called for each new call.
            host: bind address (default from settings).
            port: bind port (default from settings).
        """
        self._on_new_call = on_new_call
        self._host = host or settings.audiosocket_host
        self._port = port or settings.audiosocket_port
        self._server: asyncio.Server | None = None
        self._active_connections: dict[str, asyncio.Task] = {}

    async def start(self):
        """Start listening for AudioSocket connections."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )
        addr = self._server.sockets[0].getsockname()
        logger.info("AudioSocket server listening on %s:%s", addr[0], addr[1])

    async def stop(self):
        """Stop the server and close all active connections."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for call_id, task in list(self._active_connections.items()):
            task.cancel()
        self._active_connections.clear()
        logger.info("AudioSocket server stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Handle a single AudioSocket connection (one phone call)."""
        peer = writer.get_extra_info("peername")
        logger.info("AudioSocket connection from %s", peer)

        call_id = None
        try:
            # First frame must be UUID
            frame_type, payload = await self._read_frame(reader)
            if frame_type != TYPE_UUID:
                logger.warning("Expected UUID frame, got type=0x%02x from %s", frame_type, peer)
                writer.close()
                return

            # Asterisk app_audiosocket sends UUID as 16-byte binary when AS_UUID is a
            # valid UUID string (hex-with-dashes) — not as ASCII. Try binary decode
            # first; fall back to UTF-8 for legacy call_id strings; last resort self-gen.
            call_id = ""
            if len(payload) == 16:
                try:
                    call_id = str(uuid.UUID(bytes=payload))
                except (ValueError, TypeError):
                    call_id = ""
            if not call_id:
                try:
                    decoded = payload.decode("utf-8").strip("\x00").strip()
                    # Reject if decode produced replacement chars (binary junk)
                    if decoded and "�" not in decoded:
                        call_id = decoded
                except UnicodeDecodeError:
                    call_id = ""
            if not call_id:
                call_id = str(uuid.uuid4())
            logger.info("AudioSocket call started: call_id=%s peer=%s", call_id, peer)

            # Delegate to session handler
            task = asyncio.current_task()
            self._active_connections[call_id] = task
            await self._on_new_call(call_id, reader, writer)

        except asyncio.CancelledError:
            logger.info("AudioSocket connection cancelled: call_id=%s", call_id)
        except asyncio.IncompleteReadError:
            logger.info("AudioSocket connection closed by Asterisk: call_id=%s", call_id)
        except Exception as exc:
            logger.error("AudioSocket error for call_id=%s: %s", call_id, exc, exc_info=True)
        finally:
            if call_id:
                self._active_connections.pop(call_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("AudioSocket connection ended: call_id=%s", call_id)

    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        """Read one TLV frame from the AudioSocket stream.

        Returns (frame_type, payload).
        Raises asyncio.IncompleteReadError on disconnect.
        """
        header = await reader.readexactly(HEADER_SIZE)
        frame_type = header[0]
        length = struct.unpack(">H", header[1:3])[0]
        payload = await reader.readexactly(length) if length > 0 else b""
        return frame_type, payload

    @staticmethod
    def write_audio_frame(writer: asyncio.StreamWriter, pcm_data: bytes) -> None:
        """Write an audio TLV frame back to Asterisk.

        Args:
            writer: the TCP stream writer for this call.
            pcm_data: raw slin 16-bit 8kHz mono PCM bytes.
        """
        header = struct.pack(">BH", TYPE_AUDIO, len(pcm_data))
        writer.write(header + pcm_data)
        # Don't await drain here — let the event loop batch writes

    @staticmethod
    def write_hangup_frame(writer: asyncio.StreamWriter) -> None:
        """Send a hangup frame to Asterisk."""
        header = struct.pack(">BH", TYPE_HANGUP, 0)
        writer.write(header)
