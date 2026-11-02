#!/usr/bin/env python3
"""Interactive Chat Simulator — debug LLM pipeline + idle timer.

Run:
    cd voiceagentrag && python tests/interactive/test_chat_sim.py

Opens http://localhost:8899 with a chat UI.
- Type messages -> sends to real StreamingLLM pipeline
- Idle timer countdown visible in UI
- Each response labeled: source (user_msg / idle_prompt / idle_goodbye)
- Full timestamps in terminal log

No extra deps beyond what the project already uses (websockets).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Add src/ to path (same as app.py)
SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import websockets
import websockets.asyncio.server
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

# ── Logging with timestamps ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Enable DEBUG for LLM to see chunk-level streaming details
logging.getLogger("llm").setLevel(logging.DEBUG)
# Quiet down websockets internal "connection rejected" logs (triggered by browser asset probes)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logger = logging.getLogger("chat_sim")

# ── Settings ───────────────────────────────────────────────────────────────
IDLE_PROMPT_DELAY = 15.0
IDLE_GOODBYE_DELAY = 5.0
IDLE_DISCONNECT_DELAY = 5.0
PORT = 8899


# ── Chat Session ───────────────────────────────────────────────────────────


class ChatSession:
    """Text-only simulation of Session idle + LLM pipeline."""

    def __init__(self, ws: websockets.asyncio.server.ServerConnection):
        self.ws = ws
        self.session_id = uuid.uuid4().hex[:12]
        self._llm = None
        self._stopping = False
        self._idle_timer: asyncio.TimerHandle | None = None
        self._idle_state = 0
        self._agent_task: asyncio.Task | None = None
        self._msg_counter = 0
        self._t0 = time.monotonic()

    def _ts(self) -> str:
        elapsed = time.monotonic() - self._t0
        return f"+{elapsed:.3f}s"

    async def start(self):
        from noble_agent.agent.llm.streaming import StreamingLLM
        from noble_agent.agent.voice import VoiceAgent

        self._llm = await StreamingLLM.create(session_id=self.session_id)
        logger.info("[%s] %s Session started (agent=%s)", self.session_id, self._ts(), self._llm._current_agent)

        # Build greeting using actual VoiceAgent logic (matches 4-intent format)
        _dummy_agent = VoiceAgent(
            send_audio=lambda x: asyncio.sleep(0),
            send_json=lambda x: asyncio.sleep(0),
            session_id=self.session_id,
        )
        greeting = await _dummy_agent.build_greeting(self.session_id)
        self._llm._history.append({"role": "assistant", "content": greeting})

        await self._send(
            {
                "type": "system",
                "text": f"Session {self.session_id} started. Agent: {self._llm._current_agent}",
                "ts": self._ts(),
            }
        )
        await self._send(
            {
                "type": "agent_response",
                "text": greeting,
                "source": "auto_greeting",
                "ts": self._ts(),
            }
        )
        self._start_idle_timer(IDLE_PROMPT_DELAY)

    async def handle_message(self, text: str):
        # /reset command — reset session without reconnect
        if text.strip().lower() == "/reset":
            await self._llm.reset()
            self._idle_state = 0
            self._cancel_idle_timer()
            logger.info("[%s] %s Session RESET by user", self.session_id, self._ts())
            await self._send({"type": "system", "text": "Session reset. Agent reverted to router.", "ts": self._ts()})
            self._start_idle_timer(IDLE_PROMPT_DELAY)
            return

        self._msg_counter += 1
        msg_id = self._msg_counter
        self._reset_idle()
        logger.info("[%s] %s USER #%d: %r", self.session_id, self._ts(), msg_id, text)

        if self._agent_task and not self._agent_task.done():
            logger.info("[%s] %s Cancelling previous agent task", self.session_id, self._ts())
            self._agent_task.cancel()

        self._agent_task = asyncio.ensure_future(self._run_agent(text, msg_id))

    async def _run_agent(self, text: str, msg_id: int):
        source = f"user_msg#{msg_id}"
        t_start = time.monotonic()
        try:
            tokens = []

            def on_token(tok: str):
                tokens.append(tok)
                # Stream text chunks to UI in real-time (like voice.py → TTS)
                asyncio.ensure_future(
                    self._send(
                        {
                            "type": "text_chunk",
                            "text": tok,
                        }
                    )
                )

            def on_tool_start(name: str, args: dict):
                logger.info("[%s] %s TOOL_START %s(%s)", self.session_id, self._ts(), name, args)
                # Send tool event immediately (not buffered)
                asyncio.ensure_future(
                    self._send(
                        {
                            "type": "tool_event",
                            "action": "start",
                            "tool": name,
                            "detail": str(args)[:100],
                            "elapsed_ms": round((time.monotonic() - t_start) * 1000),
                            "ts": self._ts(),
                        }
                    )
                )

            def on_tool_done(name: str, result: str):
                logger.info("[%s] %s TOOL_DONE %s -> %s", self.session_id, self._ts(), name, result[:80])
                # Send tool event immediately (not buffered)
                asyncio.ensure_future(
                    self._send(
                        {
                            "type": "tool_event",
                            "action": "done",
                            "tool": name,
                            "detail": result[:100],
                            "elapsed_ms": round((time.monotonic() - t_start) * 1000),
                            "ts": self._ts(),
                        }
                    )
                )

            llm_t0 = time.monotonic()
            full_text = await self._llm.stream_response(
                text,
                on_token=on_token,
                on_tool_start=on_tool_start,
                on_tool_done=on_tool_done,
            )
            llm_ms = (time.monotonic() - llm_t0) * 1000

            # Check if agent switched during this turn
            current_agent = self._llm._current_agent
            logger.info(
                "[%s] %s RESPONSE [%s] (%.0fms, agent=%s): %r",
                self.session_id,
                self._ts(),
                source,
                llm_ms,
                current_agent,
                full_text[:120],
            )

            # Send final agent_response (finalizes streaming div in UI)
            await self._send(
                {
                    "type": "agent_response",
                    "text": full_text,
                    "source": source,
                    "llm_ms": round(llm_ms),
                    "agent": current_agent,
                    "prompt": self._llm._history[0]["content"] if self._llm._history else "",
                    "ts": self._ts(),
                }
            )

        except asyncio.CancelledError:
            logger.info("[%s] %s Agent task cancelled [%s]", self.session_id, self._ts(), source)
            await self._send(
                {
                    "type": "system",
                    "text": f"Agent task cancelled ({source})",
                    "ts": self._ts(),
                }
            )
        except Exception as exc:
            logger.error("[%s] %s Agent error [%s]: %s", self.session_id, self._ts(), source, exc, exc_info=True)
            await self._send(
                {
                    "type": "error",
                    "text": f"Agent error: {exc}",
                    "source": source,
                    "ts": self._ts(),
                }
            )
        finally:
            if not self._stopping:
                self._start_idle_timer(IDLE_PROMPT_DELAY)

    # ── Idle state machine ──────────────────────────────────────────────────

    def _start_idle_timer(self, delay: float):
        self._cancel_idle_timer()
        loop = asyncio.get_event_loop()
        self._idle_timer = loop.call_later(
            delay,
            lambda: asyncio.ensure_future(self._on_idle_timeout()),
        )
        asyncio.ensure_future(
            self._send(
                {
                    "type": "idle_start",
                    "delay_sec": delay,
                    "state": self._idle_state,
                    "ts": self._ts(),
                }
            )
        )
        logger.info(
            "[%s] %s IDLE timer started: %.1fs (state=%d)", self.session_id, self._ts(), delay, self._idle_state
        )

    def _cancel_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
            asyncio.ensure_future(self._send({"type": "idle_cancel", "ts": self._ts()}))

    def _reset_idle(self):
        self._cancel_idle_timer()
        self._idle_state = 0
        logger.info("[%s] %s IDLE reset (user spoke)", self.session_id, self._ts())

    async def _on_idle_timeout(self):
        if self._stopping:
            return

        if self._idle_state == 0:
            self._idle_state = 1
            text = "Dạ, Quý Khách còn muốn tìm hiểu thêm thông tin hoặc cần em hỗ trợ gì thêm không ạ?"
            logger.info("[%s] %s IDLE State 0->1: sending prompt", self.session_id, self._ts())
            self._llm._history.append({"role": "assistant", "content": text})
            await self._send(
                {
                    "type": "agent_response",
                    "text": text,
                    "source": "idle_prompt",
                    "ts": self._ts(),
                }
            )
            if self._idle_state == 1 and not self._stopping:
                self._start_idle_timer(IDLE_GOODBYE_DELAY)

        elif self._idle_state == 1:
            self._idle_state = 2
            text = "Dạ em xin phép ngắt máy ạ, chúc Quý Khách một ngày tốt lành ạ."
            logger.info("[%s] %s IDLE State 1->2: sending goodbye", self.session_id, self._ts())
            self._llm._history.append({"role": "assistant", "content": text})
            await self._send(
                {
                    "type": "agent_response",
                    "text": text,
                    "source": "idle_goodbye",
                    "ts": self._ts(),
                }
            )
            if self._idle_state == 2 and not self._stopping:
                self._start_idle_timer(IDLE_DISCONNECT_DELAY)

        elif self._idle_state == 2:
            logger.info("[%s] %s IDLE State 2->disconnect", self.session_id, self._ts())
            self._stopping = True
            await self._send(
                {
                    "type": "session_ended",
                    "reason": "idle_timeout",
                    "ts": self._ts(),
                }
            )

    async def stop(self):
        self._stopping = True
        self._cancel_idle_timer()
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()

    async def _send(self, msg: dict):
        try:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass


# ── HTML UI ────────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Chat Simulator</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; height: 100vh; display: flex; flex-direction: column; }

  #header { padding: 10px 20px; background: #161b22; border-bottom: 1px solid #30363d; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  #header h1 { font-size: 14px; color: #58a6ff; font-weight: 600; }
  #agent-badge { font-size: 11px; padding: 3px 10px; border-radius: 10px; font-weight: 600; letter-spacing: 0.3px; text-transform: uppercase; }
  #agent-badge.router { background: #8b5cf633; color: #a78bfa; }
  #agent-badge.consultant { background: #23883633; color: #56d364; }
  #agent-badge.support { background: #d2992233; color: #d29922; }
  #idle-display { font-size: 12px; padding: 3px 12px; border-radius: 6px; background: #21262d; min-width: 180px; text-align: center; font-variant-numeric: tabular-nums; }
  #idle-display.active { background: #f8514933; color: #f85149; font-weight: 600; }
  #idle-display.warning { background: #d2992233; color: #d29922; }

  #chat { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 6px; }

  .msg { padding: 10px 14px; border-radius: 10px; max-width: 85%; font-size: 13.5px; line-height: 1.6; }
  .msg .meta { font-size: 10.5px; color: #6e7681; margin-top: 6px; font-family: 'SF Mono', 'Fira Code', monospace; }
  .msg .source-tag { font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px; margin-right: 4px; display: inline-block; }
  .msg .markdown-body p { margin-bottom: 6px; }
  .msg .markdown-body p:last-child { margin-bottom: 0; }

  .msg.user { align-self: flex-end; background: #1f6feb22; border: 1px solid #1f6feb44; }
  .msg.agent { align-self: flex-start; background: #161b22; border: 1px solid #30363d; }
  .msg.idle { align-self: flex-start; background: #f8514912; border: 1px solid #f8514933; }
  .msg.system { align-self: center; background: #161b22; border: 1px solid #21262d; color: #6e7681; font-size: 11px; max-width: 100%; padding: 6px 14px; }
  .msg.error { align-self: center; background: #f8514922; border: 1px solid #f85149; color: #f85149; }
  .msg.streaming { border-color: #58a6ff66; animation: streamPulse 1.8s ease-in-out infinite; }
  .msg.streaming .markdown-body::after { content: '\u258c'; animation: blink 1s step-end infinite; color: #58a6ff; }
  @keyframes streamPulse { 0%,100% { border-color: #58a6ff33; } 50% { border-color: #58a6ff88; } }
  @keyframes blink { 50% { opacity: 0; } }

  /* ── Tool events: compact inline design ── */
  .tool-group { align-self: flex-start; max-width: 85%; display: flex; flex-direction: column; gap: 2px; margin: 2px 0; }
  .tool-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-family: 'SF Mono', 'Fira Code', monospace; background: #161b22; border: 1px solid #21262d; color: #8b949e; cursor: pointer; transition: background 0.15s; }
  .tool-badge:hover { background: #21262d; }
  .tool-badge .tool-icon { font-size: 12px; }
  .tool-badge .tool-name { color: #56d364; font-weight: 600; }
  .tool-badge .tool-time { color: #6e7681; margin-left: auto; }
  .tool-badge.done .tool-name { color: #3fb950; }
  .tool-badge.error .tool-name { color: #f85149; }
  .tool-detail { display: none; padding: 4px 10px; font-size: 10px; color: #6e7681; font-family: 'SF Mono', 'Fira Code', monospace; background: #010409; border-radius: 0 0 6px 6px; margin-top: -3px; border: 1px solid #21262d; border-top: none; word-break: break-all; max-height: 80px; overflow-y: auto; }
  .tool-detail.open { display: block; }

  .source-tag.auto_greeting { background: #8b5cf633; color: #a78bfa; }
  .source-tag.user_msg { background: #1f6feb33; color: #58a6ff; }
  .source-tag.idle_prompt { background: #d2992233; color: #d29922; }
  .source-tag.idle_goodbye { background: #f8514933; color: #f85149; }

  #input-bar { padding: 10px 20px; background: #161b22; border-top: 1px solid #30363d; display: flex; gap: 8px; }
  #input-bar input { flex: 1; padding: 10px 14px; border-radius: 10px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; font-size: 14px; font-family: inherit; outline: none; transition: border-color 0.2s; }
  #input-bar input:focus { border-color: #58a6ff; box-shadow: 0 0 0 2px #58a6ff22; }
  #input-bar button { padding: 10px 20px; border-radius: 10px; border: none; background: #238636; color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; min-width: 80px; transition: background 0.15s; }
  #input-bar button:hover { background: #2ea043; }
  #input-bar button:disabled { background: #21262d; color: #484f58; cursor: not-allowed; }

  #log-toggle { padding: 4px 20px; background: #010409; border-top: 1px solid #30363d; font-size: 11px; color: #484f58; cursor: pointer; text-align: center; }
  #log-toggle:hover { color: #8b949e; }
  #log { max-height: 180px; overflow-y: auto; padding: 8px 20px; background: #010409; font-size: 11px; color: #6e7681; display: none; font-family: 'SF Mono', 'Fira Code', monospace; }
  #log.open { display: block; }
  #log .log-line { padding: 1px 0; white-space: pre-wrap; word-break: break-all; }
  #log .log-ts { color: #58a6ff; }
</style>
</head>
<body>

<div id="header">
  <h1>Chat Simulator — 3-Agent Pipeline</h1>
  <div id="agent-badge" class="router">router</div>
  <div id="idle-display">IDLE: --</div>
</div>

<div id="chat"></div>

<div id="input-bar">
  <input id="msg-input" type="text" placeholder="Nhập tin nhắn... (/reset để reset session)" autofocus />
  <button id="send-btn" onclick="sendMsg()">Gửi</button>
</div>

<div id="log-toggle" onclick="toggleLog()">--- Log (click to toggle) ---</div>
<div id="log"></div>

<script>
const chat = document.getElementById('chat');
const logEl = document.getElementById('log');
const input = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');
const idleEl = document.getElementById('idle-display');
const agentBadge = document.getElementById('agent-badge');

let ws = null;
let idleInterval = null;
let idleEnd = 0;
let idleState = 0;
let msgCount = 0;
let connected = false;
let sessionStartTime = Date.now();

// ── Streaming + tool tracking state ──────────────────────────────────────
let streamingEl = null;
let streamingRawText = '';
let toolGroupEl = null;    // groups consecutive tool events together
let toolBadges = {};       // track tool badges by name for START→DONE updates

function wallTs() {
  const d = new Date();
  return d.toLocaleTimeString('en-GB',{hour12:false}) + '.' + String(d.getMilliseconds()).padStart(3,'0');
}

function relTs() {
  return '+' + ((Date.now() - sessionStartTime)/1000).toFixed(3) + 's';
}

function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    connected = true;
    sendBtn.disabled = false;
    sessionStartTime = Date.now();
    addLog('WebSocket connected');
  };
  ws.onmessage = (e) => handleMsg(JSON.parse(e.data));
  ws.onclose = () => {
    connected = false;
    sendBtn.disabled = true;
    addLog('WebSocket disconnected');
    clearIdleTimer();
  };
}

function handleMsg(msg) {
  const ts = msg.ts || '';
  const wall = wallTs();

  if (msg.type === 'text_chunk') {
    // Real-time text streaming
    if (!streamingEl) {
      streamingEl = document.createElement('div');
      streamingEl.className = 'msg agent streaming';
      streamingEl.innerHTML = '<div class="markdown-body"></div>';
      chat.appendChild(streamingEl);
      streamingRawText = '';
    }
    streamingRawText += msg.text;
    streamingEl.querySelector('.markdown-body').innerHTML = marked.parse(streamingRawText);
    chat.scrollTop = chat.scrollHeight;
  }
  else if (msg.type === 'agent_response') {
    const src = msg.source || 'unknown';
    const isIdle = src.startsWith('idle_');
    const cls = isIdle ? 'idle' : 'agent';
    const srcCls = src.replace(/#\\d+/,'').replace(/user_msg.*/,'user_msg');

    let metaParts = ['<span class="source-tag '+srcCls+'">'+src+'</span>'];
    if (msg.agent) metaParts.push('agent: '+msg.agent);
    if (msg.llm_ms) metaParts.push('LLM: '+msg.llm_ms+'ms');
    metaParts.push(wall);
    metaParts.push(ts);

    if (msg.agent) {
      agentBadge.textContent = msg.agent;
      agentBadge.className = msg.agent;
    }

    // Finalize streaming div or create new
    if (streamingEl) {
      streamingEl.className = 'msg '+cls;
      let html = '<div class="markdown-body">'+marked.parse(msg.text)+'</div><div class="meta">'+metaParts.join(' | ')+'</div>';
      if (msg.prompt) {
          html += '<details style="margin-top:8px;font-size:10.5px;color:#6e7681;cursor:pointer;">' +
                  '<summary style="padding:2px 0;">\u25b6 Prompt ('+ msg.prompt.length +' chars)</summary>' +
                  '<pre style="background:#010409;padding:8px;border-radius:6px;white-space:pre-wrap;max-height:250px;overflow-y:auto;margin-top:4px;border:1px solid #21262d;font-family:inherit;font-size:10px;line-height:1.4;">'+escHtml(msg.prompt)+'</pre></details>';
      }
      streamingEl.innerHTML = html;
      streamingEl = null;
      streamingRawText = '';
    } else {
      addChat(cls, msg.text, metaParts.join(' | '), msg.prompt);
    }
    // Reset tool tracking
    toolGroupEl = null;
    toolBadges = {};
    addLog('['+wall+'] ['+ts+'] RESPONSE ('+src+'): '+msg.text.substring(0,100));
    chat.scrollTop = chat.scrollHeight;
  }
  else if (msg.type === 'tool_event') {
    const name = msg.tool;
    const action = msg.action;
    const detail = msg.detail || '';
    const elapsed = msg.elapsed_ms;

    // Create tool group container if needed
    if (!toolGroupEl) {
      toolGroupEl = document.createElement('div');
      toolGroupEl.className = 'tool-group';
      if (streamingEl) {
        chat.insertBefore(toolGroupEl, streamingEl);
      } else {
        chat.appendChild(toolGroupEl);
      }
    }

    if (action === 'start') {
      // Create compact badge for tool start
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;flex-direction:column;';
      const badge = document.createElement('div');
      badge.className = 'tool-badge';
      badge.innerHTML = '<span class="tool-icon">\u23f3</span>' +
        '<span class="tool-name">'+escHtml(name)+'</span>' +
        '<span class="tool-time">+'+elapsed+'ms</span>';
      const detailEl = document.createElement('div');
      detailEl.className = 'tool-detail';
      detailEl.textContent = detail;
      badge.onclick = () => detailEl.classList.toggle('open');
      row.appendChild(badge);
      row.appendChild(detailEl);
      toolGroupEl.appendChild(row);
      toolBadges[name] = { badge, detailEl, row };
    }
    else if (action === 'done') {
      // Update existing badge to done state
      if (toolBadges[name]) {
        const b = toolBadges[name];
        b.badge.className = 'tool-badge done';
        b.badge.querySelector('.tool-icon').textContent = '\u2705';
        b.badge.querySelector('.tool-time').textContent = '+'+elapsed+'ms';
        b.detailEl.textContent = detail.substring(0, 200) + (detail.length > 200 ? '...' : '');
      } else {
        // Standalone done (no matching start)
        const badge = document.createElement('div');
        badge.className = 'tool-badge done';
        badge.innerHTML = '<span class="tool-icon">\u2705</span>' +
          '<span class="tool-name">'+escHtml(name)+'</span>' +
          '<span class="tool-time">+'+elapsed+'ms</span>';
        toolGroupEl.appendChild(badge);
      }
    }
    addLog('['+wall+'] ['+ts+'] TOOL '+action.toUpperCase()+' '+name+' '+detail.substring(0,60));
    chat.scrollTop = chat.scrollHeight;
  }
  else if (msg.type === 'system') {
    addChat('system', msg.text, wall);
    addLog('['+wall+'] SYSTEM: '+msg.text);
  }
  else if (msg.type === 'error') {
    addChat('error', msg.text, wall);
    addLog('['+wall+'] ERROR: '+msg.text);
  }
  else if (msg.type === 'idle_start') {
    idleState = msg.state;
    startIdleCountdown(msg.delay_sec);
    addLog('['+wall+'] IDLE timer: '+msg.delay_sec+'s (state='+msg.state+')');
  }
  else if (msg.type === 'idle_cancel') {
    clearIdleTimer();
    addLog('['+wall+'] IDLE cancelled');
  }
  else if (msg.type === 'session_ended') {
    addChat('system', 'Session ended: '+msg.reason, wall);
    clearIdleTimer();
    idleEl.textContent = 'DISCONNECTED';
    idleEl.className = 'active';
  }
}

function sendMsg() {
  const text = input.value.trim();
  if (!text || !connected) return;
  msgCount++;
  addChat('user', text, 'msg#'+msgCount+' | '+wallTs());
  addLog('['+wallTs()+'] USER #'+msgCount+': '+text);
  ws.send(JSON.stringify({type:'message',text:text}));
  input.value = '';
  input.focus();
}

input.addEventListener('keydown', (e) => { if(e.key==='Enter') sendMsg(); });

function addChat(cls, text, meta, promptText) {
  const d = document.createElement('div');
  d.className = 'msg '+cls;
  let html = '<div class="markdown-body">'+marked.parse(text)+'</div><div class="meta">'+(meta||'')+'</div>';
  if (promptText) {
      html += '<details style="margin-top:8px;font-size:10.5px;color:#6e7681;cursor:pointer;">' + 
              '<summary style="padding:2px 0;">\\u25B6 Prompt ('+ promptText.length +' chars)</summary>' + 
              '<pre style="background:#010409;padding:8px;border-radius:6px;white-space:pre-wrap;max-height:250px;overflow-y:auto;margin-top:4px;border:1px solid #21262d;font-family:inherit;font-size:10px;line-height:1.4;">'+escHtml(promptText)+'</pre></details>';
  }
  d.innerHTML = html;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

function addLog(text) {
  const d = document.createElement('div');
  d.className = 'log-line';
  d.textContent = text;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

function toggleLog() {
  logEl.classList.toggle('open');
}

function startIdleCountdown(sec) {
  clearIdleTimer();
  idleEnd = Date.now() + sec*1000;
  updateIdle();
  idleInterval = setInterval(updateIdle, 100);
}

function updateIdle() {
  const rem = Math.max(0, (idleEnd - Date.now())/1000);
  const labels = ['Waiting...','Prompted','Goodbye'];
  idleEl.textContent = 'IDLE ['+labels[idleState]+']: '+rem.toFixed(1)+'s';
  if (rem<=3) idleEl.className='active';
  else if (rem<=8) idleEl.className='warning';
  else idleEl.className='';
  if (rem<=0) { clearInterval(idleInterval); idleInterval=null; }
}

function clearIdleTimer() {
  if(idleInterval){clearInterval(idleInterval);idleInterval=null;}
  idleEl.textContent='IDLE: --';
  idleEl.className='';
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

connect();
</script>
</body>
</html>"""


# ── WebSocket + HTTP server ────────────────────────────────────────────────


async def ws_handler(ws: websockets.asyncio.server.ServerConnection):
    logger.info("WebSocket client connected")
    session = ChatSession(ws)
    await session.start()

    try:
        async for raw in ws:
            data = json.loads(raw)
            if data.get("type") == "message":
                await session.handle_message(data["text"])
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        await session.stop()
        logger.info("WebSocket client disconnected")


def process_request(connection, request: Request):
    """Serve HTML on GET /, handle common assets, let /ws through to WebSocket handler."""
    # Quietly handle common browser asset probes
    if request.path in ("/favicon.ico", "/robots.txt", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        return Response(204, "No Content", Headers(), b"")

    if request.path == "/":
        logger.info("Serving Chat UI to %s", connection.remote_address[0])
        body = HTML_PAGE.encode("utf-8")
        return Response(
            200,
            "OK",
            Headers(
                {
                    "Content-Type": "text/html; charset=utf-8",
                    "Content-Length": str(len(body)),
                    "Connection": "close",
                }
            ),
            body,
        )

    if request.path != "/ws":
        logger.warning(
            "Rejected unknown HTTP request: %s %s from %s", request.method, request.path, connection.remote_address[0]
        )
        return Response(404, "Not Found", Headers(), b"Not found\n")

    return None


async def main():
    # Initialize Redis + MongoDB connections (required for tools to work)
    from noble_agent.storage.connection import get_connection_manager

    conn = get_connection_manager()
    await conn.initialize()

    logger.info("=" * 60)
    logger.info("Chat Simulator: http://localhost:%d", PORT)
    logger.info(
        "Idle: prompt=%.0fs, goodbye=%.0fs, disconnect=%.0fs",
        IDLE_PROMPT_DELAY,
        IDLE_GOODBYE_DELAY,
        IDLE_DISCONNECT_DELAY,
    )
    logger.info("Redis: %s | MongoDB: %s", conn.redis_status.value, conn.mongo_status.value)
    logger.info("=" * 60)

    async with websockets.asyncio.server.serve(
        ws_handler,
        "0.0.0.0",
        PORT,
        process_request=process_request,
    ) as server:
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    if "--reload" in sys.argv:
        try:
            import watchfiles

            watch_dir = Path(__file__).resolve().parents[2] / "src"
            cmd = f"{sys.executable} {__file__}"
            print(f"Starting in RELOAD mode. Watching: {watch_dir}")
            watchfiles.run_process(watch_dir, target=cmd)
        except ImportError:
            print("ERROR: watchfiles is required for --reload mode.")
            print("Run: pip install watchfiles")
            sys.exit(1)
    else:
        asyncio.run(main())
