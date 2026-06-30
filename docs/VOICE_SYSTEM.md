# CPC Voice System — Operating Guide

> Canonical reference for the unified Voice App (playback + listening in one window).
> Any AI driving voice — Claude Code, Cowork, Codex, Grok — read this first.
> Keep it updated when the behavior changes. Last verified: 2026-06-29 (v3.0, winsdk).

---

## TL;DR — the control model

The voice loop is **speak → listen → speak → listen …**, and the user controls it with three
actions. The single most important rule: **the mic only opens when the user is meant to talk.**

| Control | What it does | Mic opens? |
|---|---|---|
| **Pause** (headset button / Pause button / `/pause`) | **HOLD.** Freezes playback in place. Resume to continue hearing. | **No** — pausing never opens the mic. |
| **Interrupt** (the "Interrupt" button / `/interrupt`) | **"My turn."** Ends the current speech + drops the queue so the pending listen opens the mic. The exchange continues. | **Yes** |
| **Stop** (Stop button / `/stop`) | **End the exchange.** Drops all audio; a waiting `/listen` returns `{stopped: true}`. | No — the loop ends. |
| *(natural finish)* | Speech plays to the end and the file closes. | **Yes** — listen begins. |

The **ready-beep lives on the listen side** (it's the first thing `/listen` does once the gate
opens), so it always fires when the mic actually opens — whether we got there by a natural
finish or an Interrupt. It is **not** tied to "end of speaking," because a pause/interrupt never
reaches a natural end.

Once the mic opens it records a **5-second minimum** (`MIN_LISTEN_FLOOR_SECS`) so a short config
can't clip the start of a reply.

### Why pause is reliable (design principle)
Pause works **because it does not depend on the AI noticing it.** The assistant keeps generating,
oblivious; the app simply holds the mic shut until playback finishes or the user interrupts. The
hold is enforced at the deterministic playback layer, not by AI awareness — if it required the
model to "know" it was paused, it would be fragile. Keep that separation: **controls that gate the
AI belong in the app/OS layer, never in the model's attention.**

---

## What it is

One windowed app (`voice_app.py`, tkinter) that owns **both** halves of a voice conversation:
TTS playback (queue + pause/resume + headset media-button) **and** listening (faster-whisper STT,
noise filter, emotion, triple-beep). It replaces the old listen-only terminal.

| Thing | Where |
|---|---|
| App source | `C:\CPC\voice\2voice\voice_app.py` |
| Launchers | `START_VOICE_APP.bat` (silent, pythonw) · `START_VOICE_APP_DEBUG.bat` (console logs) |
| Runtime | the repo's x64 Python 3.11 venv (`.venv`) — x64 required (ctranslate2 has no ARM64 wheels); runs under emulation on ARM64 Windows |
| Config | `C:\CPC\voice\voice.config.toml` (canonical) → falls back to repo-local `voice.config.toml` |
| HTTP server | `http://localhost:5123` (ThreadingHTTPServer — threaded so controls respond while `/listen` blocks) |
| Public mirror | `AIWander/Voice-Command` (repo `voice_app.py` = this file + a non-Windows guard) |
| Rust MCP wrapper | `voice.exe` (source `C:\rust-mcp\voice-mcp`) — exposes `speak`, `listen_for_speech`, `playback_control`, etc. Auto-detects this app via `app == "voice_app"` in `/status`. |

---

## HTTP API (port 5123)

`GET /status` → health: `{version, backend, model, app:"voice_app", features[…]}`
`GET /playback` → live state: `{state, text, position_ms, duration_ms, queue, recording, backend, model}`
  - `state` ∈ `IDLE | SPEAKING | PAUSED | LISTENING`

`POST /say` `{text, voice?, speed?, pitch?, volume?}` → generates TTS (edge-tts) and **queues** it (non-blocking). Returns `{id, queued:true}`.
`POST /play` `{path, text?, volume?, delete_after?}` → queue an existing audio file.
`POST /pause` · `/resume` · `/toggle` → hold / continue / flip.
`POST /interrupt` (alias `/skip`) → end current speech + drain queue → the pending `/listen` opens the mic.
`POST /stop` → end the exchange; a gating `/listen` returns `{stopped:true}`.
`POST /listen?timeout=&silence_timeout=&min_speech_duration=&rms_threshold=&skip_filter=&skip_emotion=`
  → waits at the gate (see below), beeps, records, transcribes. Returns `{success, text, emotion?}` or `{success:false, stopped:true}` or `{success:false, error:"No speech detected"}`.

### The gate (inside `/listen`)
`/listen` blocks while `gate_should_wait()` is true — i.e., while audio is **playing, PAUSED, or
queued**. It releases only when:
- playback **finishes naturally** (queue empty, nothing active), or
- the user hits **Interrupt** (drains the queue → gate releases), then beep + record; or
- the user hits **Stop** → returns `{stopped:true}` (consumed via `clear_stop()`, so it can't leak
  into the next listen).

`LISTEN_GATE_MAX_SECS = 1800` caps the wait.

---

## How to DRIVE a conversation (orchestration rules for the AI)

These are behavioral, not code — they're how you should *use* the app:

1. **One fresh response per turn.** After `/listen` returns the user's words, **read them and
   compose a NEW reply to what they actually said.** Never re-`/say` your previous line. A repeated
   sentence is far more jarring spoken than typed (no scrollback) and reads as "not listening."
   Silence-while-you-think is fine; repetition is not. *(Joseph, 2026-06-29.)*
2. **Speak short.** Keep each spoken turn tight. Long monologues are hard to interrupt and bury the
   point. Break long content into chunks.
3. **Loop until Stop.** The exchange is meant to continue — keep the speak↔listen loop going until
   the user says a stop-phrase or `/listen` returns `{stopped:true}`. Don't end after one turn.
4. **Stop before listen is automatic.** Don't try to time the beep yourself — `/say` is non-blocking
   and `/listen` waits for playback. Just call `/say` then `/listen`.
5. **Curl/HTTP timeout math.** A `/listen` call can block for `playback_remaining + record_window`.
   Set the client timeout to comfortably exceed both (e.g. `-m 120`) or it returns empty mid-record.
6. **Don't reuse canned text for testing.** When proving mechanics, vary the spoken text — identical
   lines across calls are indistinguishable from a repeat bug to the listener.
7. **Pause is the user's, not yours.** Never call `/pause` to "buy time." If you need a beat, stay
   silent and process.

---

## Backends (playback)

- **winsdk (primary):** `Windows.Media.Playback.MediaPlayer` + a System Media Transport Controls
  (SMTC) session. The headset/keyboard play-pause button is routed by Windows to this session →
  native pause/resume. The app reads the **real** player state via poll, so it detects pauses from
  the headset (SMTC), the in-app button, AND the media-key hook uniformly (`is_paused()` reads
  `_play_state`, not just our own flag).
- **subproc (fallback):** a persistent hidden PowerShell child hosting a WPF `MediaPlayer`, driven
  by a stdin/stdout line protocol, plus a `WH_KEYBOARD_LL` hook for `VK_MEDIA_PLAY_PAUSE`. Used when
  winsdk isn't available. **Never** combine the LL hook with SMTC (double-toggle) — the hook is
  fallback-only.
- Backend is chosen by `[playback] backend = auto|winsdk|subproc` in the config.

---

## Where the knowledge lives / how it's referenced

- **This file** — the operating runbook (folder-scoped; `AGENTS.md` in this folder points here).
- **Volumes `Operating_voice_sessions.md`** — the CPC knowledge base layer. The control model, the
  corrections (pause=hold supersedes the earlier barge-in idea), and the "fresh response per turn"
  rule are extracted there. Recall via `autonomous:content_search("voice pause interrupt listen
  gate beep")` or `vol_read("voice_sessions/Operating_voice_sessions.md")`.
- **`AIWander/Voice-Command`** repo — public, versioned copy of `voice_app.py` + README + this doc
  under `docs/`.

---

## Cross-AI quickstart (Codex / Grok / any MCP client)

- The voice MCP tool prefix is **`voice:*`** (server `voice`, binary `voice.exe`). Tools: `speak`,
  `listen_for_speech`, `playback_control`, `start_voice_mode`, transcript/checkpoint helpers.
- Or talk to the app directly over HTTP on `:5123` (endpoints above) — the same surface the Rust
  wrapper uses.
- The control model and the orchestration rules above apply regardless of which surface you use.
- To know whether the **unified app** (vs the legacy listen-only server) is running, check
  `/status` → `app == "voice_app"`. Only the app supports playback controls.

---

## Known follow-ups (as of 2026-06-29)

- **Rust `voice.exe` `playback_control`** still lists action `skip`, not `interrupt`. The app aliases
  `/skip → interrupt`, so it works today; add `interrupt` to the tool's vocabulary on the next
  Rust rebuild.
- **Headset-only interrupt:** the headset button is pause/hold only. To give headset-only users an
  Interrupt gesture, map the media **Next-Track** key to `/interrupt`. (Not built.)
- **README turn-model:** the repo README "How a turn works" predates this model — update it to
  describe pause(hold) / Interrupt / Stop.
