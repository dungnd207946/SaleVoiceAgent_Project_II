#!/usr/bin/env python3
"""Interactive Voice Simulator — Test STT + LLM pipeline with WebRTC + Gender Detection.

Run:
    python tests/interactive/test_voice_sim.py

Opens http://localhost:8905 with a WebRTC UI.
- Record audio via Mic.
- Watch Gender Detection run in background.
- See STT Transcript + Agent Reponses in UI UI.
- Colored logs in Terminal!
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

# Add src/ to path
SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import websockets
import websockets.asyncio.server
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

# Mặc định phải có config và session thật của hệ thống
from noble_agent.server.session import Session


# ── Logging Setup (Colored) ──────────────────────────────────────────────────
class ColoredFormatter(logging.Formatter):
    COLORS = {
        "WARNING": "\033[93m",
        "INFO": "\033[92m",
        "DEBUG": "\033[94m",
        "CRITICAL": "\033[91m",
        "ERROR": "\033[91m",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        reset = "\033[0m"
        record.msg = f"{color}{record.msg}{reset}"
        return super().format(record)


logger = logging.getLogger()
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setFormatter(ColoredFormatter("%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
logger.handlers = [ch]

# Tắt bớt log không cần thiết
logging.getLogger("websockets.server").setLevel(logging.WARNING)

PORT = 8905


# ── Handler ──────────────────────────────────────────────────────────────────
async def ws_handler(ws: websockets.asyncio.server.ServerConnection):
    client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
    session_id = uuid.uuid4().hex[:12]

    logger.info("=" * 50)
    logger.info(f"Khởi tạo Test Session Mới: {session_id} - IP: {client_ip}")

    session = Session(ws, session_id=session_id)

    # Init LLM, STT
    try:
        await session.start()
        logger.info("Các Services STT/LLM đã Boot xong cho Test Session!")
        await ws.send(
            json.dumps(
                {
                    "type": "system",
                    "text": f"Gắn kết Test Voice Session (ID: {session_id}) thành công. Sẵn sàng STT & LLM!",
                }
            )
        )

        async for message in ws:
            if not isinstance(message, str):
                continue
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                # WebRTC Signaling y hệt hệ thống chính
                if msg_type == "rtc_offer":
                    logger.info("Nhận WebRTC Offer, đang đàm phán âm thanh...")
                    answer = await session.negotiate(
                        offer_sdp=data["sdp"],
                        offer_type=data.get("offer_type", "offer"),
                    )
                    await ws.send(json.dumps(answer))
                    logger.info("WebRTC Connected - Đã bắt đầu nhận luồng Audio Mic!")

                elif msg_type == "interrupt":
                    logger.warning("[UI] Nhận cờ Interrupt từ phím tắt")
                    session.agent.interrupt()
                    session.audio_track.clear()
                    session.vad.set_idle()

            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as exc:
        logger.error(f"UI Handler error: {exc}", exc_info=True)
    finally:
        await session.stop()
        logger.info(f"Test Session {session_id} đã tắt an toàn.")


# ── HTML UI ────────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Voice Simulator UI</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; height: 100vh; display: flex; flex-direction: column; }
  #header { padding: 15px 20px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; }
  #header h1 { font-size: 16px; color: #58a6ff; font-weight: 600; }
  
  #main { flex: 1; display: flex; overflow: hidden; padding: 20px; gap: 20px; }
  .col { flex: 1; display: flex; flex-direction: column; background: #161b22; border-radius: 8px; border: 1px solid #30363d; overflow: hidden; }
  .col-header { padding: 10px; font-weight: bold; border-bottom: 1px solid #30363d; background: #21262d; font-size: 14px; text-transform: uppercase; }
  .col-body { flex: 1; overflow-y: auto; padding: 15px; font-size: 14px; line-height: 1.5; }
  
  .msg { padding: 10px; border-radius: 6px; margin-bottom: 10px; }
  .msg-partial { color: #8892b0; font-style: italic; }
  .msg-final { background: #1f6feb33; border-left: 3px solid #58a6ff; }
  .agent-msg { background: #8b5cf633; border-left: 3px solid #a78bfa; margin-bottom: 10px; }
  .tool-msg { font-family: monospace; background: #010409; color: #56d364; font-size: 12px; }
  .system-msg { color: #f85149; font-weight: bold;}
  
  #controls { padding: 20px; background: #161b22; border-top: 1px solid #30363d; text-align: center; }
  button { padding: 12px 24px; border-radius: 6px; border: none; font-size: 14px; font-weight: bold; cursor: pointer; background: #238636; color: white; transition: 0.2s;}
  button:hover { background: #2ea043; }
  button.active { background: #da3633; }
  button:disabled { background: #484f58; cursor: not-allowed; }
</style>
</head>
<body>
<div id="header">
  <h1>🎙️ Standalone Voice Simulator (STT + LLM + Gender)</h1>
  <div style="font-size: 12px; color: #8892b0;" id="status">Chờ kết nối WebRTC...</div>
</div>

<div id="main">
  <div class="col">
    <div class="col-header">Nhận Diện STT (Khách nói)</div>
    <div class="col-body" id="stt-box"></div>
  </div>
  <div class="col">
    <div class="col-header">LLM Response (Bot nói) & Tools</div>
    <div class="col-body" id="llm-box"></div>
  </div>
</div>

<div id="controls">
  <button id="mic-btn">🎙️ Bật Mic (Connect WebRTC)</button>
  <div style="font-size: 11px; margin-top:10px; color:#6e7681;">Chú ý xem Log ở Terminal của IDE để thấy Gender Detection tiêm dữ liệu nhé.</div>
</div>

<script>
let ws;
let pc;
let micStream;

const sysStatus = document.getElementById('status');
const sttBox = document.getElementById('stt-box');
const llmBox = document.getElementById('llm-box');
const micBtn = document.getElementById('mic-btn');

function logUI(box, type, text) {
    const el = document.createElement('div');
    if(type === 'partial') {
        const p = document.getElementById('partial-stt');
        if (p) p.innerText = text;
        else {
            el.id = 'partial-stt';
            el.className = 'msg msg-partial';
            el.innerText = text;
            box.appendChild(el);
        }
    } else {
        const p = document.getElementById('partial-stt');
        if (p) p.remove();
        el.className = 'msg ' + type;
        
        let header = '';
        if(type === 'msg-final') header = '👤 [Bạn]: ';
        if(type === 'agent-msg') header = '🤖 [Luna]: ';
        if(type === 'tool-msg') header = '🔧 [Tools]: ';
        
        el.innerHTML = `<strong>${header}</strong>${text}`;
        box.appendChild(el);
    }
    box.scrollTop = box.scrollHeight;
}

micBtn.onclick = async () => {
    if(pc) return; // Đã connect
    
    sysStatus.innerText = "Đang khởi tạo WebRTC...";
    micBtn.disabled = true;
    
    ws = new WebSocket('ws://' + location.host + '/ws');
    
    ws.onopen = async () => {
        pc = new RTCPeerConnection();
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micStream.getTracks().forEach(t => pc.addTrack(t, micStream));
        
        // Nhận Voice Audio phản hồi từ Server (LLM TTS)
        pc.ontrack = (event) => {
            const audio = new Audio();
            audio.srcObject = event.streams[0];
            audio.play();
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        ws.send(JSON.stringify({ type: "rtc_offer", sdp: offer.sdp, offer_type: offer.type }));
    };
    
    ws.onmessage = async (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "rtc_answer") {
            await pc.setRemoteDescription(new RTCSessionDescription({ type: msg.answer_type, sdp: msg.sdp }));
            sysStatus.innerText = "🎤 Kết nối âm thanh Online. Đang truyền Mic.";
            micBtn.innerText = "🟢 Đang Ghi Âm Trực Tiếp";
            micBtn.classList.add('active');
        }
        else if (msg.type === "partial_transcript") {
            logUI(sttBox, 'partial', msg.text);
        }
        else if (msg.type === "transcript") {
            logUI(sttBox, 'msg-final', msg.text);
        }
        else if (msg.type === "agent_speaking") {
            logUI(llmBox, 'agent-msg', msg.text);
        }
        else if (msg.type === "tool_start") {
            logUI(llmBox, 'tool-msg', `(Start) ${msg.tool} -> Params: ${JSON.stringify(msg.args)}`);
        }
        else if (msg.type === "tool_done") {
            logUI(llmBox, 'tool-msg', `(Done) ${msg.tool}`);
        }
        else if (msg.type === "system") {
            logUI(sttBox, 'system-msg', msg.text);
        }
        else if (msg.type === "error") {
            logUI(sttBox, 'system-msg', 'LỖI: ' + msg.message);
        }
    };
};
</script>
</body>
</html>
"""


def process_request(connection, request: Request):
    if request.path == "/":
        return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), HTML_PAGE.encode("utf-8"))
    if request.path != "/ws":
        return Response(404, "Not Found", Headers(), b"")
    return None


async def main():
    from noble_agent.storage.connection import get_connection_manager

    cm = get_connection_manager()
    await cm.initialize()

    # Pre-load Models
    from noble_agent.voice.gender_detector import GenderDetector

    GenderDetector.get_instance()

    logger.info("=" * 60)
    logger.info(f"🎤 Trình Giả Lập STT + LLM + Voice (Port: {PORT})")
    logger.info("=" * 60)
    logger.info(f"1. Mở Trình duyệt: http://localhost:{PORT}")
    logger.info("2. Bấm nút Bật Mic để Test")

    async with websockets.asyncio.server.serve(ws_handler, "0.0.0.0", PORT, process_request=process_request) as server:
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
