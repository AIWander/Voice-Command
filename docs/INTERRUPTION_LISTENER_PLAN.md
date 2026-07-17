# Interruption Listener Plan

Status: implementation plan for Voice App v3.1 on Windows x64

Baseline: `AIWander/Voice-Command` `main` at `32ad9e0` after live GitHub alignment on 2026-07-14

## Goal

Add a second listening plane that is active while an assistant response is playing or held by Pause.
It listens only for user-selected interruption phrases, initially `umm`. When it recognizes one, it
pauses playback, yields the microphone to the existing beep-and-transcribe listener, and decides the
next action from that listener's result:

- no new speech: resume the same audio at the same position;
- new speech: discard the unheard remainder, return the new speech together with the interrupted
  response context, and let the AI compose a modified answer;
- Interrupt/Skip button: bypass phrase detection and open the normal listener immediately;
- natural playback finish: open the normal listener exactly as Voice App v3.0 does today;
- Stop: end the exchange.

The exchange repeats until the user stops or explicitly changes modes.

## Architecture decision

The second listener is a separate listener lifecycle and microphone mode inside `voice_app.py`, not a
second operating-system process.

This preserves the requested two-listener behavior while avoiding three failure modes caused by two
independent processes:

1. Windows microphone-device contention between two PyAudio owners.
2. Two copies of the Whisper model competing for memory and CPU.
3. Cross-process races between playback pause, microphone release, and the regular listener beep.

The packaged x64 Voice App still contains two independently controlled listening planes:

- interruption listener: no beep, phrase detection only, active during speaking and Pause;
- regular listener: triple beep, full transcription, active after a handoff or natural finish.

Only one plane may own the microphone or Whisper model at a time.

## State contract

| Playback state | Interruption listener | Regular listener | Transition |
|---|---|---|---|
| Speaking | Armed | Waiting at gate | Trigger phrase pauses playback and requests handoff |
| Paused by widget/headset | Armed by default | Waiting at gate | Trigger phrase requests handoff; Resume continues normally |
| Wake handoff | Suspended | Beeps and captures | Empty capture resumes; text capture replaces remainder |
| Widget Interrupt/Skip | Suspended | Beeps and captures | Current and queued audio are discarded |
| Natural finish | Suspended | Beeps and captures | Existing turn-taking behavior |
| Stop | Off | Cancelled | Exchange ends |

Pause remains a hold. It does not open the regular listener by itself. The interruption listener stays
armed while paused unless `listen_while_paused` is disabled.

## Wake flow

1. The AI calls `/say`, then immediately calls `/listen` as it does today.
2. Playback begins and the regular `/listen` request waits at its playback gate.
3. The interruption listener opens the mic without a beep and examines short rolling windows.
4. A configured phrase match pauses playback and records an interruption snapshot.
5. The interruption listener releases the mic and Whisper model.
6. The waiting regular listener bypasses the playback gate for this wake event, beeps, and captures a
   normal utterance.
7. If the result is empty or unintelligible, the wake event is cleared, playback resumes at the same
   position, and phrase monitoring is re-armed.
8. If the result contains text, the current response and queue are drained. `/listen` returns the new
   text plus the interruption snapshot and a response instruction.
9. The AI addresses the new input and preserves any still-relevant unfinished part of the prior
   response. It must not replay wording the user already heard.
10. The revised response is queued, phrase monitoring is re-armed, and the loop repeats.

## Interruption result contract

An interruption-driven `/listen` success returns fields in addition to the existing `text` and optional
`emotion`:

```json
{
  "success": true,
  "text": "the user's new input",
  "listen_reason": "wake_phrase",
  "interruption": {
    "source": "wake_phrase",
    "trigger_phrase": "umm",
    "prior_response": "the complete assistant response that was playing",
    "position_ms": 4200,
    "duration_ms": 11200,
    "played_fraction": 0.375,
    "queued_responses": []
  },
  "response_instruction": "Address the new input and preserve relevant unfinished content from the interrupted response without repeating wording already heard."
}
```

`listen_reason` values are `natural_finish`, `widget_interrupt`, and `wake_phrase`. The Rust MCP wrapper
must pass these fields through instead of reducing the result to only `text` and `emotion`.

The Voice App does not run the language model. Its responsibility is to preserve and return enough
context for the connected AI to produce the modified verbal response.

## Phrase selection

Default configuration:

```toml
[interruption_listener]
enabled = true
trigger_phrases = ["umm"]
listen_while_paused = true
window_secs = 1.5
rms_threshold = 100.0
cooldown_secs = 1.5
empty_handoff_timeout_secs = 5.0
```

The widget exposes the phrases as a comma-separated field with `umm` prefilled. Apply validates,
deduplicates, and persists the selection in the user's local application-data directory. The TOML file
remains the distributable default; local widget choices override only the phrase list.

Phrase matching is case-insensitive, punctuation-insensitive, and word-boundary based. The app uses a
short cooldown and exact configured phrases to reduce self-triggering. Agent instructions also prohibit
speaking a configured trigger phrase as filler while the interruption listener is armed.

## Code changes

- `voice_app.py`
  - add interruption-listener configuration and status fields;
  - add a background rolling microphone listener with no beep;
  - coordinate exclusive mic/model ownership with the regular listener;
  - preserve playback context before wake or widget interruption;
  - implement empty-capture resume and text-capture replacement;
  - expose phrase configuration and listener state in the widget and HTTP status.
- `voice_interrupt.py`
  - pure phrase normalization/matching;
  - local phrase-settings load/save;
  - interruption-context and response-instruction helpers.
- `voice-mcp/src/main.rs`
  - pass interruption metadata through `listen_for_speech`;
  - accept `interrupt` as a playback-control synonym;
  - update tool descriptions with the response-revision contract.
- `voice.config.example.toml`
  - add the default interruption-listener section.
- `AGENTS.md`, `CLAUDE.md`, `docs/VOICE_SYSTEM.md`, and `README.md`
  - document the two listening planes and the context-preserving response rule.
- `tests/`
  - phrase matching and settings tests;
  - state-transition tests with fake playback and capture components;
  - response-contract and Rust pass-through checks.

## Windows x64 deliverables

1. Build `voice-mcp` for `x86_64-pc-windows-msvc` in an alternate target directory.
2. Verify the PE machine field is `0x8664` and run a JSON-RPC tool-list smoke test.
3. Stage the updated Python Voice App in a versioned v3.1 layout while reusing the verified x64 private
   Python runtime and offline model payload.
4. Build a new `CPC-Voice-Setup-v3.1.0-x64.exe` without replacing the currently published v3.0
   installer.
5. Verify installer and binary hashes and Authenticode state, then run the bundled x64 runtime on an
   isolated port and prove the `GET /status` feature list. A live install/uninstall remains a promotion
   boundary because it rewrites client MCP configuration.

Publishing a GitHub release or replacing a live shared runtime is a separate promotion boundary. The
build can be completed and staged without restarting a shared service.

## Acceptance tests

- `umm` during playback pauses at the current position and produces one regular-listener beep sequence.
- Silence after the beep resumes from the saved position and does not repeat from the beginning.
- New speech after the beep returns the prior response context and drains its unheard remainder.
- The revised reply can itself be interrupted repeatedly.
- Pause alone never opens the regular listener; phrase monitoring remains active while held.
- Interrupt/Skip opens the regular listener without requiring a phrase.
- Natural finish opens the regular listener once.
- Stop cancels playback, monitoring, and a waiting listen.
- A trigger cannot produce two handoffs during its cooldown.
- Mic and Whisper locks cannot be held by both listeners simultaneously.
- Existing v3 pause, resume, queue, status, and legacy-listener fallbacks remain green.
- The produced Windows binary is mechanically verified as x64.

## Rollback

The pre-alignment repository bundle and dirty `server.py` copy are stored under
`C:\CPC\backups\voice-command\`. Each existing file changed during implementation receives its own
timestamped pre-change backup before editing. The new installer is staged under a new name and does not
replace the v3.0 release asset automatically.
