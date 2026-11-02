# NobleX × Luna — Design Handoff Brief (bubble → chat/voice, rich media)

**Purpose:** context pack for prototyping the in-app Luna experience with Claude design.
**Date:** 2026-07-11 · **Source of truth:** `src/noble_agent/` (backend already built for chat + voice provisioning; rich-media push is greenfield).

---

## 1. The concept (as requested)

A floating **Luna bubble** lives on the NobleX real-estate app. Tapping it opens a chooser:

- **Chat** — text conversation with Luna.
- **Voice call** — real-time voice conversation with Luna.

In **both** channels Luna can, when useful, push **rich media into the conversation**: images (renders, floorplans, maps, brochures) and **YouTube videos** (project tour clips). The user views/plays them inline without leaving the conversation.

Luna is a real, shipping agent (persona **Luna**, Vietnamese, pre-sale real-estate consultant). The prototype should feel like a front-end for *this* agent, not a generic chatbot.

---

## 2. Who Luna is (drives tone & copy)

- **Language:** Vietnamese, warm/proactive hotline-consultant register ("Dạ…", "anh/chị", "quý khách"). All UI copy and mock messages should be Vietnamese.
- **Scope: pre-sale only** — project consulting (tư vấn dự án) + booking a site visit (đặt lịch tham quan). She answers about 12–15 Noble/Sunshine projects.
- **Handoff:** post-sale topics (contract / payment / sổ hồng / warranty) and private pricing are **escalated to a human specialist (CVTV)** — Luna says she'll connect a specialist, she does not answer them. Design should have a graceful "connecting you to a specialist" state.
- **Working hours:** 8:00–21:00 (Asia/Ho_Chi_Minh). Outside hours the escalate copy changes to "chuyên viên sẽ liên hệ vào ngày làm việc tiếp theo". A prototype could show an off-hours hint.
- **Two happy endings** she steers toward: (a) đặt lịch tham quan, or (b) leaving a phone number for a specialist to call back.

---

## 3. Session start — how the app gets a live Luna (already built)

Server-to-server provisioning endpoint: `POST /api/v1/app/session` (header `X-Noble-App-Key`). The NobleX backend authenticates the user, then calls this. Identity is **server-authoritative** — the client never sets who it is.

Request body:
```json
{
  "noble_user_id": "…",           // required → stable session_id "app-xxxxxxxxxxxx"
  "channel": "chat" | "voice",
  "identity": {
    "full_name": "…", "phone": "09…", "gender": "nam|nữ|m|f",
    "is_noble_customer": true, "email": "…", "birthday": "…", "noble_info": "…"
  }
}
```

Response — **chat**:
```json
{ "session_id": "app-…", "channel": "chat",
  "ws_url": "wss://…/chat?session=app-…&token=…",   // open this WS directly
  "connect_token": "…", "expires_in": 120 }
```
Response — **voice**:
```json
{ "session_id": "app-…", "channel": "voice",
  "livekit_url": "wss://…livekit.cloud",
  "livekit_token": "…",   // join room=session_id; agent auto-dispatched into the room
  "room": "app-…" }
```

**UX implications:**
- The chooser's two buttons map to `channel: "chat"` vs `"voice"`.
- The session is **resumable & identity-aware**: Luna already knows the user's name (and whether they're an existing customer) *before the first message*. The greeting can be personalized ("Dạ chào anh Thế…").
- Voice call: Luna **speaks first** (auto-greeting on connect). Design the connecting → Luna-greeting moment.

---

## 4. Live event contracts the UI must render (already emitted by backend)

Both channels stream structured events the UI turns into bubbles/indicators. **A prototype's mock layer should emit these exact shapes** so it drops onto the real backend later.

### Chat (`/chat` WebSocket, JSON frames)
| Event | Shape | UI meaning |
|---|---|---|
| `session_id` | `{type, session_id}` | connected |
| `user_text` | `{type, text}` | echo the user's sent message |
| `metrics` (first_token) | `{type, stage:"first_token", ttft_ms}` | Luna is about to reply (typing→streaming) |
| `token` | `{type, text}` | **stream** Luna's reply token-by-token |
| `tool_start` | `{type, tool, args}` | Luna is doing something (e.g. searching, sending media) — show a subtle activity chip |
| `tool_done` | `{type, tool, result}` | tool finished (result is JSON string) — **this is where a media card arrives** (see §5) |
| `done` | `{type, ttft_ms, tokens, total_ms, …}` | turn complete |
| `error` | `{type, message}` | error bubble |

There's also an optional TTS-in-chat path (`tts_begin` → binary PCM16 → `tts_end`) — chat can *speak* replies. Probably out of scope for the first prototype, but worth knowing "chat with voice output" is possible.

### Voice (LiveKit data channel, topic `EVENT_TOPIC`, reliable)
Same idea over the call's data channel: `transcript` (live STT of what the user said + what Luna says), `agent_speaking` / `agent_done` (drives a talking indicator / waveform), `tool_start` / `tool_done`. The token already grants `can_publish_data` so **media cards push mid-call the same way**.

**Design primitive:** one **MediaCard component** rendered identically in chat and in the voice-call screen, fed by the same payload — so media is channel-agnostic.

---

## 5. Rich media (images + YouTube) — the greenfield part

**Current backend reality:** the tool that would send media, `send_via_app`, is a **stub** — it logs and returns a text ack with **no URLs**. There is **no media-asset registry** (project docs hold only a handful of YouTube *channel* URLs + websites, not per-topic image/video assets). So:

- **The media experience is designed here, in the prototype** — you're not constrained by an existing UI.
- The backend will later need (a) a media-source (per project: renders, floorplans, map image, brochure PDF, tour video IDs) and (b) an enriched tool result / dedicated event carrying media items.

**Proposed payload contract to mock now** (so prototype ↔ future backend line up). Emit as an enriched `send_via_app` `tool_done.result`, or better, a dedicated event `{type:"media", …}`:
```json
{
  "type": "media",
  "caption": "Dạ em gửi anh/chị vài hình ảnh và video dự án Noble Palace ạ.",
  "items": [
    { "kind": "image", "url": "https://…/render1.jpg", "thumb": "https://…/render1_t.jpg", "alt": "Phối cảnh tổng thể" },
    { "kind": "image", "url": "https://…/floorplan_2br.jpg", "alt": "Mặt bằng căn 2PN" },
    { "kind": "video", "provider": "youtube", "video_id": "dQw4w9WgXcQ",
      "thumb": "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg", "title": "Tour dự án Noble Palace" }
  ],
  "project_code": "NPTTL"
}
```

**Media UX to design:**
- **Image card:** 1 image (hero) or 2–4 (gallery/carousel), tap → full-screen zoom/swipe. Floorplans need pinch-zoom.
- **Video card:** YouTube thumbnail + play button + title; tap → inline player or full-screen. Consider a "1:24" duration chip.
- **In chat:** the card is a message bubble from Luna, in flow with text.
- **In a voice call:** the card slides onto the call screen while Luna narrates it. **Open decision:** does opening a video pause/duck the live call audio, or play video muted with Luna still talking? (See §9.)
- Caption text should read as *Luna's voice* ("Dạ em gửi anh/chị…"), not a system label.

---

## 6. Personalization data available (for a tailored UI)

From provisioning + Luna's state, the app knows: `full_name`, `phone`, `gender` (M/F → honorific anh/chị), `is_noble_customer` (existing vs. prospect), `email`, `birthday`, `noble_info`, and a live `project_interest` (the project Luna has inferred the user cares about). Use these for: personalized greeting, honorifics, an "existing customer" accent, and possibly surfacing the current project-of-interest in the header.

---

## 7. Screens / states to prototype

1. **Bubble** — floating Luna avatar over app content (idle; maybe a subtle attention pulse / unread dot).
2. **Chooser** — expand from bubble → "Nhắn tin với Luna" (chat) vs "Gọi cho Luna" (voice), Luna avatar + one-line value prop. Fast to dismiss.
3. **Chat screen — a standard/normal chat dialog** (keep it familiar, no novel chrome)
   - Header: small **Luna avatar (icon)** + name + status (online / đang trả lời…).
   - Message list: standard chat bubbles — user on one side, Luna's streaming replies on the other. Tool activity shows as a lightweight **chip** in-flow ("Luna đang tìm thông tin…"). **Media (images / YouTube) renders as inline card bubbles within this same normal flow** — not a separate surface. That's the whole point of "just a normal chat dialog": media is a message like any other.
   - Composer: text input + send. (Optional: mic-to-text, a "gọi Luna" shortcut to jump to voice.)
   - States: connecting, streaming, tool-working, media bubble received, error/retry, escalation ("đang kết nối chuyên viên").

4. **Voice-call screen — three vertical zones** (this is the distinctive screen)

   ```
   ┌─────────────────────────────┐
   │                             │
   │   Luna half-body portrait   │  ← TOP: Luna's upper-body image;
   │   (speaking / listening)    │     animates/pulses with agent_speaking
   │                             │
   ├─────────────────────────────┤
   │                             │
   │   Stream text (live)        │  ← MIDDLE: scrollable conversation surface —
   │   ┌───────┐  ┌───────┐      │     Luna's streamed text (from transcript),
   │   │ image │  │ video │      │     plus images and YouTube video cards
   │   └───────┘  └───────┘      │     as Luna sends them mid-call
   │                             │
   ├─────────────────────────────┤
   │    🔇        ☎️        🔊     │  ← BOTTOM: 3 controls, left→right:
   │   Mute   End call   Speaker  │     Mute · Kết thúc cuộc gọi · Loa ngoài
   └─────────────────────────────┘
   ```

   - **Top zone:** Luna **half-body / upper-body portrait** (nửa người), fixed at the top, with a speaking/listening state driven by `agent_speaking`/`transcript` (subtle motion or glow while she talks).
   - **Middle zone:** a live surface that shows **streaming text** (Luna's words as `transcript`), plus **images and video cards** as she pushes them (same MediaCard as chat, but living here instead of in a message list). Newest content scrolls into view.
   - **Bottom zone:** exactly **3 buttons — Mute, End call (Kết thúc), Speaker/loa ngoài** (speaker toggles earpiece↔loudspeaker). Optional swipe-up for a full transcript / switch-to-chat, but the base state is these three.
   - States: connecting → Luna greeting (she speaks first) → conversation → media shown in middle zone → escalation → ended.
5. **Media full-screen** — image zoom/swipe gallery; YouTube player.
6. **Escalation / handoff** — "Dạ em kết nối anh/chị với chuyên viên tư vấn ạ" confirmation; off-hours variant.
7. **Booking confirmation** (nice-to-have) — when Luna schedules a site visit, a small confirmation card (project, date, time).

---

## 8. Interaction & latency notes that shape the UI

- **Streaming, not turn-blocking:** Luna's text arrives token-by-token; design for a live-typing feel, not a spinner-then-dump. First token target is fast (TTFT metric is emitted).
- **Tool activity is visible and can take ~1s+** (search / pricing / media). Show a lightweight "đang tìm…" chip, not a full-screen block — Luna often says a filler sentence ("Dạ em gửi qua app cho anh/chị nha, chờ em một chút ạ") *at the same time* the media is being fetched. The filler text and the card arrive close together.
- **Voice barge-in:** the user can interrupt Luna while she's speaking; the UI should reflect that Luna stops. (Backend supports it.)
- **Voice-first greeting:** on a voice call Luna speaks immediately on connect — the "connecting" state should transition straight into her greeting.

---

## 9. Open product/design decisions to resolve (flag for the user)

1. **Video during a live voice call:** pause/duck the call while a YouTube video plays, or play video while Luna keeps talking? (Recommend: tapping to full-screen the video ducks the call; small inline preview does not.)
2. **Persistent bubble vs. entry point** — does the bubble float over *all* app screens, or only certain ones? Does it remember an open conversation (resume) when reopened?
3. **One session, two channels** — can a user switch chat↔voice mid-conversation and keep context? (Backend session_id is shared/resumable, so this is feasible — worth designing the switch affordance.)
4. **Media source for the prototype** — use placeholder renders + a sample YouTube ID now; real per-project asset registry is a backend follow-up.
5. **Chat-with-spoken-replies** — do we want Luna's chat replies to also be spoken (TTS-in-chat exists)? Or keep chat silent?
6. **Proactivity** — does the bubble ever proactively prompt ("Dạ anh đang xem dự án Noble Palace, cần em tư vấn không ạ?"), or only respond when tapped?

---

## 10. Real vs. mock — so the prototype aligns with the backend

| Piece | Status | For the prototype |
|---|---|---|
| Provisioning (chat + voice), identity-aware session | **Built** | Mock the two response payloads (§3) |
| Chat streaming events (`token`/`tool_*`/`done`) | **Built** | Mock these exact shapes (§4) |
| Voice call + data-channel events + auto-greeting + barge-in | **Built** | Mock transcript/agent_speaking driving the avatar |
| Luna persona, pre-sale scope, escalate, working hours | **Built** | Drives copy/tone (§2) |
| `send_via_app` returning media, media-asset registry | **Stub / not built** | **Design freely**; mock the `media` payload (§5) |
| MediaCard rendering (image gallery / YouTube) | Not built (no real UI) | **Core of the prototype** |

**One-line summary for the designer:** the conversational engine (chat + voice, streaming, identity, tool activity, escalation) is real and has clean event contracts to mock against; the **rich-media card experience is the new surface to design**, and it should render identically in chat and in a voice call, fed by a single `media` payload.
