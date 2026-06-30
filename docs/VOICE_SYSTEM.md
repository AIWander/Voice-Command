# Voice System — Operating Guide (for AI agents)

> **If you are an AI pointed at this repo, this is your manual.** It tells you everything you need
> to give a user a real two-way voice conversation with the **Voice App** — speak, listen, and let
> them pause / interrupt / stop you. Standalone: assumes only this cloned repo. Last verified
> against **Voice App v3.0**.

---

## 0. AI agent quickstart (60 seconds to a voice loop)

1. **Install deps** into a Python 3.11 venv (x64 — `ctranslate2`/faster-whisper has no ARM64
   wheels; on ARM64 Windows it runs fine under emulation):
   ```bash
   py -3.11 -m venv .venv
   .venv\Scripts\python -m pip install -U pip
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
   Also need `ffmpeg` on PATH (or set `VOICE_FFMPEG_PATH`). On macOS use `START_VOICE_SERVER.sh`
   (the windowed app is Windows-only today — see §4 Backends).
2. **Configure:** copy `voice.config.example.toml` to `voice.config.toml` (same folder as
   `voice_app.py`) and tweak if you like. Defaults are sane.
3. **Launch the app:** `START_VOICE_APP.bat` (or `.venv\Scripts\pythonw voice_app.py`). It serves
   `http://localhost:5123` and shows a small window.
4. **Confirm it's the unified app:** `GET /status` → expect `"app": "voice_app"` and
   `"model": "ready"`. (The legacy `voice_server.py` answers `/status` too but has **no** playback
   controls.)
5. **Drive the loop** — speak, then listen, then reply to what you heard:
   ```bash
   curl -s -XPOST localhost:5123/say -H 'Content-Type: application/json' -d '{"text":"Hi! What can I do for you?"}'
   curl -s -XPOST 'localhost:5123/listen?timeout=60&silence_timeout=3'   # blocks, beeps, records, returns {text}
   # → read the text, COMPOSE A NEW REPLY to it, /say that, /listen again … until they Stop.
   ```
   Prefer MCP? Wire the `voice-mcp` server (see README "Config snippets per client") and call the
   `speak` and `listen_for_speech` tools instead of curl — same behavior.

That's it. The rest of this doc is the *why* and the rules that keep it feeling human.

---

## 1. The control model (the part that matters most)

The loop is **speak → listen → speak → listen …**. The user has three controls, and the golden
rule is: **the mic only opens when it's the user's turn.**

| Control | What it does | Mic opens? |
|---|---|---|
| **Pause** (headset play/pause button, the Pause button, or `POST /pause`) | **HOLD** — freezes playback in place; Resume to keep hearing. | **No** — pausing never opens the mic. |
| **Interrupt** (the Interrupt button, or `POST /interrupt`) | **"My turn."** Ends the current speech + drops the queue so the waiting listen opens the mic. The conversation continues. | **Yes** |
| **Stop** (the Stop button, or `POST /stop`) | **Ends the exchange.** Drops all audio; a waiting `/listen` returns `{"stopped": true}`. | No — the loop ends. |
| *(natural finish)* | Speech plays to the end and the file closes. | **Yes** — listen begins. |

- The **ready-beep lives inside `/listen`**, so it fires whenever the mic actually opens — after a
  natural finish *or* an Interrupt. It is **not** tied to "end of speaking" (a pause/interrupt
  never reaches a natural end).
- Once the mic opens it records a **5-second minimum** so a short config can't clip the start of a
  reply.

**Design note — why pause is reliable:** pause works *because it doesn't depend on you (the AI)
noticing it.* You keep generating, oblivious; the app holds the mic shut at the playback layer
until you finish or the user interrupts. Don't try to track or react to pause — the app owns it.

---

## 2. HTTP API (`localhost:5123`)

| Method / path | Purpose |
|---|---|
| `GET /status` | `{version, backend, model, app:"voice_app", features[…]}` |
| `GET /playback` | `{state, text, position_ms, duration_ms, queue, recording}` — `state ∈ IDLE\|SPEAKING\|PAUSED\|LISTENING` |
| `POST /say` `{text, voice?, speed?, pitch?, volume?}` | Generate TTS (edge-tts) and **queue** it (returns immediately). |
| `POST /play` `{path, text?, volume?, delete_after?}` | Queue an existing audio file. |
| `POST /pause` · `/resume` · `/toggle` | Hold / continue / flip. |
| `POST /interrupt` (alias `/skip`) | End current speech + drain queue → the waiting `/listen` opens the mic. |
| `POST /stop` | End the exchange; a gating `/listen` returns `{stopped:true}`. |
| `POST /listen?timeout=&silence_timeout=&min_speech_duration=&rms_threshold=&skip_filter=&skip_emotion=` | Wait at the gate, beep, record, transcribe → `{success, text, emotion?}`, or `{success:false, stopped:true}`, or `{success:false, error:"No speech detected"}`. |

**The gate (inside `/listen`):** blocks while audio is **playing, PAUSED, or queued**. Releases on
natural finish, on **Interrupt** (queue drained), or bails on **Stop**. Capped at 30 min.

The server is threaded, so control calls (`/pause`, `/interrupt`, `/stop`) stay responsive while a
`/listen` is blocking.

---

## 3. Rules for driving a clean exchange (behavioral)

1. **One fresh response per turn.** After `/listen` returns, **read it and compose a NEW reply to
   what was actually said.** Never re-`/say` your previous line — a repeated sentence is far more
   jarring spoken than typed (no scrollback) and reads as "not listening." Silence while you think
   is fine; repetition is not.
2. **Speak short.** Tight turns are easy to interrupt and keep the point up front. Chunk long content.
3. **Loop until Stop.** Keep speak↔listen going until the user says a stop-phrase or `/listen`
   returns `{stopped:true}`. Don't end after one turn.
4. **Don't time the beep yourself.** `/say` is non-blocking and `/listen` waits for playback — just
   call `/say` then `/listen`.
5. **Mind the client timeout.** A `/listen` can block for `playback_remaining + record_window`; set
   your HTTP timeout to exceed both (e.g. 120s) or it returns empty mid-record.
6. **Pause is the user's, not yours.** Never `/pause` to buy time — stay silent and process.

---

## 4. Backends (playback)

- **winsdk (primary, Windows):** `Windows.Media.Playback.MediaPlayer` + a System Media Transport
  Controls (SMTC) session, so the headset/keyboard play-pause button is routed by the OS. The app
  reads the **real** player state, so it detects pauses from the headset, the in-app button, and
  the media-key hook uniformly. Requires the `winsdk` pip package (in `requirements.txt`).
- **subproc (fallback, Windows):** a persistent hidden PowerShell child hosting a WPF `MediaPlayer`
  + a low-level keyboard hook for the play/pause media key. Used when `winsdk` isn't installed.
- **macOS:** the windowed app is Windows-only for now; use `START_VOICE_SERVER.sh` (terminal
  listener) + the `afplay`-based playback in `server.py`/the Rust wrapper. A native Darwin app
  backend (PyObjC + AVAudioPlayer + MPRemoteCommandCenter) is tracked in the issues.
- Pick the backend in `voice.config.toml` → `[playback] backend = auto|winsdk|subproc`.

---

## 5. What's in this repo (everything you need)

| File | Role |
|---|---|
| `voice_app.py` | **The Voice App** (v3.0) — playback + listening + UI, serves `:5123`. |
| `START_VOICE_APP.bat` | Silent launcher (Windows). |
| `voice_server.py` | Legacy listen-only HTTP server (no playback controls). |
| `server.py` | Python MCP wrapper (fallback if you don't use the Rust binary). |
| `voice-mcp/` | Rust MCP server source (`speak`, `listen_for_speech`, `playback_control`, …). |
| `voice.config.example.toml` | Copy to `voice.config.toml`; `[listen]`, `[edge-tts]`, `[playback]`. |
| `requirements.txt` | Python deps (incl. `winsdk` on Windows, `faster-whisper`, `edge-tts`). |
| `README.md` | Human setup + MCP config snippets per client. |
| `AGENTS.md` / `CLAUDE.md` | Agent entry rules (repo root) — the short version of this guide. |

You do **not** need anything outside this repo to run a full voice exchange.

---

## 6. Known follow-ups
- The Rust `playback_control` tool still names the action `skip`; the app aliases `/skip → /interrupt`, so it works. `interrupt` will be added to the tool vocabulary on the next Rust build.
- Headset-only Interrupt gesture (mapping the Next-Track media key to `/interrupt`) is not yet built — the headset button is pause/hold only; use the app's Interrupt button to grab the floor.
