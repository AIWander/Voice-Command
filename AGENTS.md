# AGENTS.md — you are an AI pointed at the Voice-Command repo

This repo gives you (an AI agent) a **real two-way voice conversation** with your user: you speak,
they talk back, and they can **pause / interrupt / stop** you with a headset button or the app
window. This file is your entry point. Full manual: **[docs/VOICE_SYSTEM.md](docs/VOICE_SYSTEM.md)**.
Human setup + per-client MCP config: **[README.md](README.md)**.

## Get running (Windows; for macOS see README → Platform support)
```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -U pip -r requirements.txt   # needs ffmpeg on PATH
copy voice.config.example.toml voice.config.toml
START_VOICE_APP.bat                                              # serves http://localhost:5123
```
Confirm it's live and the *unified app* (not the legacy listener): `GET /status` → `"app":"voice_app"`, `"model":"ready"`.

## Drive a turn
```bash
curl -s -XPOST localhost:5123/say -H 'Content-Type: application/json' -d '{"text":"Hi — what can I do for you?"}'
curl -s -XPOST 'localhost:5123/listen?timeout=60&silence_timeout=3'   # blocks, beeps, records, returns {"text": "..."}
```
…then **read what they said, compose a NEW reply to it, `/say` that, `/listen` again** — loop until
they stop. (Or wire the `voice-mcp` MCP server and call `speak` / `listen_for_speech` as tools —
same thing. See README.)

## The control model — the user's three controls
| Control | Effect | Mic opens? |
|---|---|---|
| **Pause** (headset button / Pause / `/pause`) | **HOLD** — freezes you; Resume continues. | **No** |
| **Interrupt** (Interrupt button / `/interrupt`) | **"My turn"** — ends your speech, opens the mic, conversation continues. | **Yes** |
| **Stop** (`/stop`) | Ends the exchange — a waiting `/listen` returns `{"stopped":true}`. | No |
| *natural finish* | You played to the end. | **Yes** |

The ready-**beep is on the listen side** (fires when the mic opens). The mic records a **5s minimum**.

## Non-negotiable rules
1. **One fresh response per turn.** After `/listen`, reply to what was *actually said* — **never
   re-speak your previous line.** Silence-while-you-think is fine; repetition reads as "not listening."
2. **Speak short. Loop until Stop.** Don't end after one turn.
3. **Pause is the user's, not yours.** Never `/pause` to buy time — stay silent and process.
4. **Don't time the beep.** `/say` is non-blocking and `/listen` waits for playback; just call `/say` then `/listen`. Give the HTTP call a generous timeout (≥120s).

Everything else — the full HTTP API, playback backends (winsdk/SMTC headset routing), and the
file map — is in [docs/VOICE_SYSTEM.md](docs/VOICE_SYSTEM.md). You need nothing outside this repo.
