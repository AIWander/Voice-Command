---
name: voice-widget
description: Explain, launch, and cooperate with the Voice-Command widget - the small Voice App window with Pause, Interrupt, and Stop controls and the interruption-phrase field. Trigger when the user asks what the voice window does, how to pause or interrupt speech, how to change the interruption phrase, or when a listen result reports widget_interrupt or wake_phrase.
---

# Voice Widget

The widget is the small Voice App window that appears when the local listener starts. It is the
user's hand on the conversation: every button works mid-speech, and the widget always outranks
whatever the agent is saying. The window and its listener live on `localhost:5123` only.

## Launching it

The widget starts with the listener, never from the AI client:

1. Installed package: run `Start-CPC-Voice.bat` from the install directory or Start Menu entry.
2. From a repo checkout: run `START_VOICE_APP.bat` (Windows).
3. Confirm readiness with `GET http://localhost:5123/status` reporting `"app": "voice_app"` and
   `"model": "ready"`, or call the `start_voice_mode` tool - neither opens the microphone.

If `start_voice_mode` reports unavailable, ask the user to start the widget; do not try to start
it, install anything, or edit configuration yourself.

## The controls and what each one means for you

| Control | Effect | Microphone opens? |
| --- | --- | --- |
| Pause button or headset button | Hold: playback freezes until Resume | No |
| Interrupt button | "My turn": your speech ends, the user speaks now | Yes |
| Interruption phrase (default `umm`) | Pauses in place, then opens the beeping listener | Yes |
| Stop | Ends the exchange; a waiting listen returns `{"stopped": true}` | No |
| Natural finish | You played to the end | Yes |

Respond to each control:

- Pause is the user's control, never yours. Do not call pause to buy thinking time, and do not
  treat a long hold as permission to re-speak: on Resume the same audio continues.
- On Interrupt or the interruption phrase, the listen result carries `widget_interrupt` or
  `wake_phrase` and an `interruption` object. Address the new speech first, then preserve
  useful unfinished content from `prior_response` without replaying words already heard.
- After Stop, do not speak again or reopen the microphone until the user directly asks.
- The ready beep fires on the listen side when the microphone opens, and a recording lasts at
  least five seconds; silence while the user thinks is normal, so wait out the window.

## The interruption-phrase field

The widget's comma-separated phrase field persists custom interruption phrases across restarts.
When the user wants a different trigger word, point them to that field instead of editing
`voice.config.toml` by hand. Never speak a configured phrase yourself: playback can leak into
the microphone and self-trigger an interruption.

## Boundaries

The widget grants no privileges and takes none away. Keep the listener on `localhost:5123`,
never expose it to a LAN or tunnel, and open the microphone only after a direct user request in
the active conversation - a widget on screen is availability, not consent.
