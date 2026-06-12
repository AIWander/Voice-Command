#!/usr/bin/env python3
"""
CPC Voice App v3.0 — Unified voice window
==========================================
One app, one window: TTS playback + pause/resume + listening.

  • Playback queue with true pause/resume (headset media button works)
  • Listen handoff is gated on PLAYBACK END, not response end —
    pausing playback stalls the switch back to listening
  • /say generates TTS in-app via edge-tts (MCP server stays thin)
  • Back-compat: /listen and /status behave like voice_server.py v2.0
  • faster-whisper STT, noise filtering, emotion detection (ported from v2.0)

Playback backends (auto-selected):
  1. winsdk  — Windows.Media.Playback.MediaPlayer. Registers a System Media
               Transport Controls session, so the headset play/pause button
               is routed natively by Windows (with media overlay).
  2. subproc — persistent PowerShell child hosting a WPF MediaPlayer, plus a
               low-level keyboard hook for VK_MEDIA_PLAY_PAUSE. The hook only
               swallows the key while our audio is active; otherwise it
               passes through so other media apps keep working.

HTTP API on http://localhost:5123
  GET  /status            health + features
  GET  /playback          playback state {state, text, position_ms, duration_ms, queue}
  POST /say               JSON {text, voice?, speed?, pitch?, volume?} -> queue TTS
  POST /play              JSON {path, text?, volume?, delete_after?} -> queue audio file
  POST /pause /resume /toggle /skip /stop
  POST /listen?...        record + transcribe (waits for playback queue to drain first)
"""

import ctypes
import ctypes.wintypes
import json
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

APP_NAME = "CPC Voice"
APP_VERSION = "3.0"
PORT = 5123

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════
import tomllib

SAMPLE_RATE = 16000
CHUNK_SIZE = 8000  # ~500ms chunks
BEEP_FREQ = 880
BEEP_DURATION = 0.15
BEEP_GAP = 0.08

DEFAULT_SILENCE_TIMEOUT = 4.0
DEFAULT_RMS_THRESHOLD = 100
DEFAULT_MIN_SPEECH_DURATION = 3.0
LISTEN_GATE_MAX_SECS = 1800  # absolute cap on how long /listen waits for playback

END_PHRASES = [
    'send this', 'send it', 'done', "that's it", 'stop', 'exit',
    'over', 'end', 'finished', 'complete', 'go ahead', 'send'
]


def _find_config():
    candidates = [
        os.environ.get("VOICE_CONFIG_PATH"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice.config.toml"),
        "./voice.config.toml",
        os.path.join(os.path.expanduser("~"), ".config", "voice", "voice.config.toml"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


VOICE_CONFIG_PATH = _find_config()


def read_config():
    if VOICE_CONFIG_PATH is None:
        return {}
    try:
        with open(VOICE_CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def get_listen_defaults():
    config = read_config()
    listen = config.get("listen", {})
    return {
        "silence_timeout": listen.get("silence_timeout_secs", DEFAULT_SILENCE_TIMEOUT),
        "min_speech_duration": listen.get("min_speech_duration_secs", DEFAULT_MIN_SPEECH_DURATION),
        "rms_threshold": listen.get("rms_threshold", DEFAULT_RMS_THRESHOLD),
        "pre_record_enabled": listen.get("pre_record_enabled", True),
        "noise_filter_enabled": listen.get("noise_filter_enabled", True),
        "beam_size": listen.get("beam_size", 5),
    }


def get_tts_defaults():
    config = read_config()
    et = config.get("edge-tts", {})
    defaults = config.get("defaults", {})
    return {
        "voice": et.get("voice", "en-US-GuyNeural"),
        "speed": et.get("speed", defaults.get("speed", 1.0)),
        "pitch": et.get("pitch", defaults.get("pitch", "+0Hz")),
        "volume": et.get("volume", defaults.get("volume", 1.0)),
    }


def get_playback_config():
    config = read_config()
    pb = config.get("playback", {})
    return {
        "backend": pb.get("backend", "auto"),          # auto | winsdk | subproc
        "media_key_hook": pb.get("media_key_hook", True),  # subproc mode only
        "always_on_top": pb.get("always_on_top", False),
    }


# ═══════════════════════════════════════════════════════════════════
# SHARED STATE
# ═══════════════════════════════════════════════════════════════════
class AppState:
    IDLE = "IDLE"
    SPEAKING = "SPEAKING"
    PAUSED = "PAUSED"
    LISTENING = "LISTENING"

    def __init__(self):
        self.lock = threading.RLock()
        self.state = AppState.IDLE
        self.current_text = ""
        self.position_ms = 0
        self.duration_ms = 0
        self.queue_len = 0
        self.recording_active = False
        self.mic_level = 0.0
        self.backend_name = "none"
        self.model_status = "loading"
        self.transcript = deque(maxlen=50)   # (role, text, ts)
        self.last_error = ""

    def set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def log_transcript(self, role, text):
        with self.lock:
            self.transcript.append((role, text, time.strftime("%H:%M:%S")))

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state,
                "text": self.current_text,
                "position_ms": self.position_ms,
                "duration_ms": self.duration_ms,
                "queue": self.queue_len,
                "recording": self.recording_active,
                "backend": self.backend_name,
                "model": self.model_status,
                "error": self.last_error,
            }


STATE = AppState()


def log(msg):
    print(f"[VoiceApp] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════════════
# PLAYBACK BACKEND 1: winsdk (Windows.Media.Playback.MediaPlayer + SMTC)
# ═══════════════════════════════════════════════════════════════════
class WinsdkPlayer:
    """Native WinRT MediaPlayer. SMTC session = headset buttons route to us
    while we're the active media session; Windows shows the media overlay."""
    name = "winsdk"

    def __init__(self):
        from winsdk.windows.media.playback import MediaPlayer
        from winsdk.windows.media.core import MediaSource
        from winsdk.windows.foundation import Uri
        import winsdk.windows.media as wm
        self._MediaSource = MediaSource
        self._Uri = Uri
        self._wm = wm
        self._player = MediaPlayer()
        self._ended = threading.Event()
        self._failed_msg = None
        self._token_ended = self._player.add_media_ended(self._on_ended)
        self._token_failed = self._player.add_media_failed(self._on_failed)

    def _on_ended(self, sender, args):
        self._ended.set()

    def _on_failed(self, sender, args):
        try:
            self._failed_msg = str(args.error_message)
        except Exception:
            self._failed_msg = "media playback failed"
        self._ended.set()

    def _set_smtc_metadata(self, text):
        try:
            smtc = self._player.system_media_transport_controls
            updater = smtc.display_updater
            updater.type = self._wm.MediaPlaybackType.MUSIC
            snippet = (text or "Claude response")[:60]
            updater.music_properties.title = snippet
            updater.music_properties.artist = APP_NAME
            updater.update()
        except Exception as e:
            log(f"SMTC metadata skipped: {e}")

    def load_and_play(self, path, volume, text=""):
        self._ended.clear()
        self._failed_msg = None
        uri = self._Uri("file:///" + str(path).replace("\\", "/"))
        self._player.source = self._MediaSource.create_from_uri(uri)
        self._player.volume = max(0.0, min(1.0, float(volume)))
        self._set_smtc_metadata(text)
        self._player.play()

    def pause(self):
        self._player.pause()

    def resume(self):
        self._player.play()

    def stop(self):
        # MediaPlayer has no stop(); detach source ends playback
        try:
            self._player.pause()
            self._player.source = None
        except Exception:
            pass
        self._ended.set()

    def poll(self):
        """Returns (state_str, pos_ms, dur_ms, ended, error)."""
        if self._ended.is_set():
            return ("ended", 0, 0, True, self._failed_msg)
        try:
            session = self._player.playback_session
            ps = int(session.playback_state)  # 3=playing 4=paused
            pos = int(session.position.total_seconds() * 1000) if session.position else 0
            dur = int(session.natural_duration.total_seconds() * 1000) if session.natural_duration else 0
            state = "playing" if ps == 3 else ("paused" if ps == 4 else "opening")
            return (state, pos, dur, False, None)
        except Exception as e:
            return ("error", 0, 0, True, str(e))

    def close(self):
        try:
            self._player.remove_media_ended(self._token_ended)
            self._player.remove_media_failed(self._token_failed)
            self._player.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# PLAYBACK BACKEND 2: persistent PowerShell child (WPF MediaPlayer)
# ═══════════════════════════════════════════════════════════════════
PS_PLAYER_SCRIPT = r'''
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
[Console]::Out.WriteLine("READY")
[Console]::Out.Flush()
while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $parts = $line.Split(" ", 2)
    $cmd = $parts[0]
    try {
        switch ($cmd) {
            "LOAD" {
                $player.Close()
                $player.Open([Uri]::new($parts[1]))
                $t = 0
                while (-not $player.NaturalDuration.HasTimeSpan -and $t -lt 100) {
                    Start-Sleep -Milliseconds 100; $t++
                }
                $player.Play()
                if ($player.NaturalDuration.HasTimeSpan) {
                    $d = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds
                } else { $d = -1 }
                [Console]::Out.WriteLine("DUR $d")
            }
            "VOL"    { $player.Volume = [double]$parts[1]; [Console]::Out.WriteLine("OK") }
            "PAUSE"  { $player.Pause(); [Console]::Out.WriteLine("OK") }
            "RESUME" { $player.Play(); [Console]::Out.WriteLine("OK") }
            "STOP"   { $player.Stop(); $player.Close(); [Console]::Out.WriteLine("OK") }
            "POS"    {
                $p = [int]$player.Position.TotalMilliseconds
                if ($player.NaturalDuration.HasTimeSpan) {
                    $d = [int]$player.NaturalDuration.TimeSpan.TotalMilliseconds
                } else { $d = -1 }
                [Console]::Out.WriteLine("POS $p $d")
            }
            "QUIT"   { [Console]::Out.WriteLine("BYE"); exit }
            default  { [Console]::Out.WriteLine("ERR unknown") }
        }
    } catch {
        [Console]::Out.WriteLine("ERR $($_.Exception.Message)")
    }
    [Console]::Out.Flush()
}
'''


class SubprocPlayer:
    """WPF MediaPlayer hosted in a hidden persistent PowerShell child.
    Pause/resume/position via a line protocol over stdin/stdout."""
    name = "subproc"

    def __init__(self):
        self._lock = threading.Lock()
        self._paused = False
        self._dur = 0
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_PLAYER_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, startupinfo=si, bufsize=1,
        )
        ready = self._proc.stdout.readline().strip()
        if ready != "READY":
            raise RuntimeError(f"PS player failed to start: {ready!r}")

    def _cmd(self, line):
        with self._lock:
            if self._proc.poll() is not None:
                raise RuntimeError("PS player died")
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
            return self._proc.stdout.readline().strip()

    def load_and_play(self, path, volume, text=""):
        self._paused = False
        self._dur = 0
        self._cmd(f"VOL {max(0.0, min(1.0, float(volume)))}")
        resp = self._cmd(f"LOAD {path}")
        if resp.startswith("DUR"):
            self._dur = int(resp.split()[1])

    def pause(self):
        self._cmd("PAUSE")
        self._paused = True

    def resume(self):
        self._cmd("RESUME")
        self._paused = False

    def stop(self):
        try:
            self._cmd("STOP")
        except Exception:
            pass
        self._dur = 0

    def poll(self):
        try:
            resp = self._cmd("POS")
        except Exception as e:
            return ("error", 0, 0, True, str(e))
        if not resp.startswith("POS"):
            return ("error", 0, 0, True, resp)
        _, pos, dur = resp.split()
        pos, dur = int(pos), int(dur)
        if dur <= 0:
            dur = self._dur
        # ended: position reached duration (only counts while not paused)
        ended = (not self._paused) and dur > 0 and pos >= dur - 60
        state = "paused" if self._paused else ("playing" if not ended else "ended")
        return (state, pos, dur, ended, None)

    def close(self):
        try:
            self._cmd("QUIT")
        except Exception:
            pass
        try:
            self._proc.kill()
        except Exception:
            pass


def make_player(backend_pref):
    if backend_pref in ("auto", "winsdk"):
        try:
            p = WinsdkPlayer()
            log("Playback backend: winsdk (native SMTC — headset buttons routed by Windows)")
            return p
        except Exception as e:
            log(f"winsdk backend unavailable ({e}); falling back to PowerShell player")
            if backend_pref == "winsdk":
                raise
    p = SubprocPlayer()
    log("Playback backend: subproc (PowerShell WPF player + media-key hook)")
    return p


# ═══════════════════════════════════════════════════════════════════
# PLAYBACK MANAGER (queue + worker + listen gate)
# ═══════════════════════════════════════════════════════════════════
class PlaybackManager:
    def __init__(self, backend_pref):
        self.player = make_player(backend_pref)
        STATE.set(backend_name=self.player.name)
        self.queue = queue.Queue()
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._skip = threading.Event()
        self._stop_all = threading.Event()
        self._pause_requested = threading.Event()
        self._active = threading.Event()   # an item is loaded/playing/paused
        self.worker = threading.Thread(target=self._run, daemon=True, name="playback")
        self.worker.start()

    def enqueue(self, path, text, volume, delete_after=True):
        with self._id_lock:
            pid = self._next_id
            self._next_id += 1
        self.queue.put({"id": pid, "path": path, "text": text,
                        "volume": volume, "delete_after": delete_after})
        STATE.set(queue_len=self.queue.qsize())
        return pid

    # -- controls ----------------------------------------------------
    def pause(self):
        if self._active.is_set():
            self._pause_requested.set()
            self.player.pause()

    def resume(self):
        if self._active.is_set():
            self._pause_requested.clear()
            self.player.resume()

    def toggle(self):
        st, *_ = self.player.poll()
        if st == "paused":
            self.resume()
            return "resumed"
        elif st == "playing":
            self.pause()
            return "paused"
        return "idle"

    def skip(self):
        if self._active.is_set():
            self._skip.set()
            self.player.stop()

    def stop_all(self):
        self._stop_all.set()
        self.skip()

    def busy(self):
        """True while audio is queued, playing, or paused — the listen gate."""
        return self._active.is_set() or not self.queue.empty()

    # -- worker ------------------------------------------------------
    def _run(self):
        while True:
            item = self.queue.get()
            STATE.set(queue_len=self.queue.qsize())
            if self._stop_all.is_set():
                self._cleanup(item)
                if self.queue.empty():
                    self._stop_all.clear()
                continue
            # half-duplex: never start playback while the mic is recording
            while STATE.recording_active:
                time.sleep(0.1)
            self._skip.clear()
            self._active.set()
            try:
                self._play_item(item)
            except Exception as e:
                log(f"Playback error: {e}")
                STATE.set(last_error=str(e))
            finally:
                self._active.clear()
                self._cleanup(item)
                if self.queue.empty():
                    STATE.set(state=AppState.IDLE, current_text="",
                              position_ms=0, duration_ms=0)

    def _play_item(self, item):
        log(f"Playing #{item['id']}: {item['text'][:60]!r}")
        STATE.set(state=AppState.SPEAKING, current_text=item["text"] or "(audio)")
        self.player.load_and_play(item["path"], item["volume"], item["text"])
        while True:
            if self._skip.is_set() or self._stop_all.is_set():
                log(f"Skipped #{item['id']}")
                break
            st, pos, dur, ended, err = self.player.poll()
            if err:
                STATE.set(last_error=err)
            if ended:
                break
            STATE.set(position_ms=pos, duration_ms=dur,
                      state=AppState.PAUSED if st == "paused" else AppState.SPEAKING)
            time.sleep(0.15)

    def _cleanup(self, item):
        if item.get("delete_after"):
            try:
                os.unlink(item["path"])
            except Exception:
                pass

    def close(self):
        self.player.close()


# ═══════════════════════════════════════════════════════════════════
# MEDIA KEY HOOK (subproc backend only — winsdk gets buttons via SMTC)
# ═══════════════════════════════════════════════════════════════════
class MediaKeyHook:
    """Low-level keyboard hook for VK_MEDIA_PLAY_PAUSE. Toggles our playback
    and swallows the key ONLY while our audio is active; passes through when
    idle so other media apps keep working."""
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    VK_MEDIA_PLAY_PAUSE = 0xB3

    def __init__(self, manager):
        self.manager = manager
        self._hook = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="mediakeys")
        self.thread.start()

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, ctypes.c_int,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", ctypes.wintypes.DWORD),
                        ("scanCode", ctypes.wintypes.DWORD),
                        ("flags", ctypes.wintypes.DWORD),
                        ("time", ctypes.wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG))]

        def proc(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == self.VK_MEDIA_PLAY_PAUSE and self.manager._active.is_set():
                    result = self.manager.toggle()
                    log(f"Media key: {result}")
                    return 1  # swallow — we consumed it
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = HOOKPROC(proc)  # keep a ref or it gets GC'd
        self._hook = user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self._proc,
            kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            log("Media key hook failed to install")
            return
        log("Media key hook installed (VK_MEDIA_PLAY_PAUSE)")
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# ═══════════════════════════════════════════════════════════════════
# TTS GENERATION (edge-tts, in-process)
# ═══════════════════════════════════════════════════════════════════
def generate_tts(text, voice, speed, pitch):
    """Generate mp3 via edge-tts. Returns temp file path. Raises on failure."""
    import asyncio
    import edge_tts

    uid = int(time.time() * 1000)
    out_path = os.path.join(tempfile.gettempdir(), f"tts_{uid}.mp3")
    rate = f"{(speed - 1.0) * 100:+.0f}%"
    kwargs = {"rate": rate}
    if pitch and pitch != "+0Hz":
        kwargs["pitch"] = pitch

    async def _gen():
        comm = edge_tts.Communicate(text, voice, **kwargs)
        await comm.save(out_path)

    asyncio.run(_gen())
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("edge-tts produced no audio")
    return out_path


# ═══════════════════════════════════════════════════════════════════
# LISTENING ENGINE (ported from voice_server.py v2.0 — feature parity)
# ═══════════════════════════════════════════════════════════════════
from scipy.fft import fft
from scipy.signal import butter, lfilter

WHISPER_MODEL = None
_model_lock = threading.Lock()
_recording_lock = threading.Lock()


def load_whisper_async():
    def _load():
        global WHISPER_MODEL
        from faster_whisper import WhisperModel
        log("Loading Whisper model (base, int8)...")
        try:
            with _model_lock:
                WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
            STATE.set(model_status="ready")
            log("Whisper model loaded")
        except Exception as e:
            STATE.set(model_status=f"error: {e}")
            log(f"Whisper load FAILED: {e}")
    threading.Thread(target=_load, daemon=True, name="whisper-load").start()


def butter_highpass(cutoff, fs, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff / nyq, btype='high', analog=False)
    return b, a


def butter_lowpass(cutoff, fs, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, cutoff / nyq, btype='low', analog=False)
    return b, a


def apply_noise_filter(samples, sample_rate=16000):
    b_hp, a_hp = butter_highpass(80, sample_rate)
    filtered = lfilter(b_hp, a_hp, samples)
    b_lp, a_lp = butter_lowpass(7500, sample_rate)
    filtered = lfilter(b_lp, a_lp, filtered)
    return filtered.astype(np.int16)


def extract_audio_features(samples, sample_rate=16000):
    samples = samples.astype(np.float32) / 32768.0
    n = len(samples)
    if n == 0:
        return None
    energy = np.sqrt(np.mean(samples ** 2))
    zero_crossings = np.sum(np.abs(np.diff(np.sign(samples)))) / 2
    zcr = zero_crossings / n
    fft_size = 2048
    spectral_centroids = []
    for i in range(0, n - fft_size, fft_size):
        chunk = samples[i:i + fft_size]
        spectrum = np.abs(fft(chunk)[:fft_size // 2])
        freqs = np.arange(fft_size // 2)
        if np.sum(spectrum) > 0:
            spectral_centroids.append(np.sum(freqs * spectrum) / np.sum(spectrum))
    spectral_centroid = np.mean(spectral_centroids) if spectral_centroids else 0
    frame_size = 1024
    pitches = []
    for i in range(0, n - frame_size * 2, frame_size):
        chunk = samples[i:i + frame_size]
        corr = np.correlate(chunk, chunk, mode='full')
        corr = corr[len(corr) // 2:]
        min_lag = sample_rate // 500
        max_lag = sample_rate // 50
        if max_lag < len(corr):
            peak_idx = np.argmax(corr[min_lag:max_lag]) + min_lag
            if corr[peak_idx] > 0.1:
                pitches.append(sample_rate / peak_idx)
    pitch_variance = np.std(pitches) if len(pitches) > 1 else 0
    frame_ms = 20
    frame_samples = sample_rate * frame_ms // 1000
    energy_threshold = energy * 0.3
    voiced_frames = 0
    for i in range(0, n, frame_samples):
        chunk = samples[i:i + frame_samples]
        if len(chunk) > 0 and np.sqrt(np.mean(chunk ** 2)) > energy_threshold:
            voiced_frames += 1
    duration_secs = n / sample_rate
    speech_rate = (voiced_frames * 0.15) / duration_secs if duration_secs > 0 else 0
    return {
        'energy': float(energy),
        'zero_crossing_rate': float(zcr),
        'spectral_centroid': float(spectral_centroid),
        'pitch_variance': float(pitch_variance),
        'speech_rate': float(speech_rate),
    }


def detect_emotion(features):
    if not features:
        return {'primary': 'neutral', 'confidence': 0.5, 'features': {}}
    norm_energy = min(features['energy'] * 180, 1.0)
    norm_pitch_var = min(features['pitch_variance'] / 40, 1.0)
    norm_rate = min(features['speech_rate'] / 6, 1.0)
    norm_centroid = min(features['spectral_centroid'] / 400, 1.0)
    norm_zcr = min(features['zero_crossing_rate'] * 4, 1.0)
    arousal = (norm_energy + norm_rate + norm_zcr) / 3
    valence = norm_pitch_var - norm_zcr * 0.5
    if arousal > 0.7:
        emotion, confidence = ('excited', 0.6 + arousal * 0.3) if valence > 0.3 else ('angry', 0.5 + arousal * 0.3)
    elif arousal < 0.3:
        if norm_pitch_var < 0.2 and norm_rate < 0.3:
            emotion, confidence = 'sad', 0.5 + (1 - arousal) * 0.3
        else:
            emotion, confidence = 'calm', 0.5 + (1 - arousal) * 0.2
    else:
        if norm_pitch_var > 0.5 and norm_centroid > 0.4:
            emotion, confidence = 'happy', 0.4 + norm_pitch_var * 0.3
        else:
            emotion, confidence = 'neutral', 0.6
    return {'primary': emotion, 'confidence': min(confidence, 0.95), 'features': features}


def capture_voice(max_duration, skip_emotion=False, skip_filter=False,
                  silence_timeout=None, min_speech_duration=None, rms_threshold=None):
    import pyaudio
    cfg = get_listen_defaults()
    silence_timeout = silence_timeout if silence_timeout is not None else cfg["silence_timeout"]
    min_speech_duration = min_speech_duration if min_speech_duration is not None else cfg["min_speech_duration"]
    rms_threshold = rms_threshold if rms_threshold is not None else cfg["rms_threshold"]

    if WHISPER_MODEL is None:
        return {'success': False, 'error': f'Whisper model not ready ({STATE.model_status})'}

    if not _recording_lock.acquire(blocking=False):
        return {'success': False, 'error': 'Already recording'}

    p = None
    try:
        STATE.set(recording_active=True, state=AppState.LISTENING)
        p = pyaudio.PyAudio()

        # Triple beep — the audible "your turn" cue
        log(f"Recording... (max {max_duration}s, silence={silence_timeout}s, rms={rms_threshold})")
        t = np.linspace(0, BEEP_DURATION, int(SAMPLE_RATE * BEEP_DURATION), False)
        beep_tone = (np.sin(2 * np.pi * BEEP_FREQ * t) * 16000).astype(np.int16)
        gap = np.zeros(int(SAMPLE_RATE * BEEP_GAP), dtype=np.int16)
        triple_beep = np.concatenate([beep_tone, gap, beep_tone, gap, beep_tone])
        beep_stream = p.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True)
        beep_stream.write(triple_beep.tobytes())
        beep_stream.stop_stream()
        beep_stream.close()
        time.sleep(0.3)

        stream = p.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                        input=True, frames_per_buffer=CHUNK_SIZE)
        all_frames = []
        has_speech = False
        silent_chunks = 0
        max_silent_chunks = int(silence_timeout * SAMPLE_RATE / CHUNK_SIZE)
        max_chunks = int(max_duration * SAMPLE_RATE / CHUNK_SIZE)
        min_chunks = int(min_speech_duration * SAMPLE_RATE / CHUNK_SIZE)

        for i in range(max_chunks):
            data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            all_frames.append(data)
            samples = struct.unpack(f'{CHUNK_SIZE}h', data)
            rms = (sum(s * s for s in samples) / CHUNK_SIZE) ** 0.5
            STATE.set(mic_level=min(rms / 1000.0, 1.0))
            if rms >= rms_threshold:
                has_speech = True
                silent_chunks = 0
            elif has_speech and i >= min_chunks:
                silent_chunks += 1
                if silent_chunks >= max_silent_chunks:
                    log("Silence detected, stopping")
                    break

        stream.stop_stream()
        stream.close()

        if not has_speech:
            return {'success': False, 'error': 'No speech detected'}

        audio_data = b''.join(all_frames)
        samples_array = np.frombuffer(audio_data, dtype=np.int16)
        if not skip_filter:
            samples_array = apply_noise_filter(samples_array, SAMPLE_RATE)

        emotion_result = None
        if not skip_emotion:
            features = extract_audio_features(samples_array, SAMPLE_RATE)
            emotion_result = detect_emotion(features)
            log(f"Emotion: {emotion_result['primary']} ({emotion_result['confidence']:.0%})")

        temp_path = os.path.join(tempfile.gettempdir(), 'voice_whisper.wav')
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(samples_array.tobytes())

        log("Transcribing with Whisper...")
        with _model_lock:
            segments, info = WHISPER_MODEL.transcribe(temp_path, beam_size=cfg["beam_size"])
            text = " ".join([seg.text for seg in segments]).strip()
        os.unlink(temp_path)

        if not text:
            return {'success': False, 'error': 'Could not understand audio', 'emotion': emotion_result}

        log(f"Transcribed: {text}")
        text_lower = text.lower()
        for phrase in END_PHRASES:
            if text_lower.endswith(phrase):
                text = text[:-(len(phrase))].strip().rstrip('.,!?')
                break

        STATE.log_transcript("user", text)
        result = {'success': True, 'text': text}
        if emotion_result:
            result['emotion'] = emotion_result
        return result

    except Exception as e:
        log(f"Listen error: {e}")
        traceback.print_exc()
        return {'success': False, 'error': str(e)}
    finally:
        STATE.set(recording_active=False, mic_level=0.0)
        if STATE.state == AppState.LISTENING:
            STATE.set(state=AppState.IDLE)
        if p is not None:
            p.terminate()
        _recording_lock.release()


# ═══════════════════════════════════════════════════════════════════
# HTTP API
# ═══════════════════════════════════════════════════════════════════
MANAGER = None  # set in main()


class VoiceHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # UI + stdout logging handled elsewhere

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/status':
            self.send_json({
                'success': True,
                'status': 'running',
                'version': APP_VERSION,
                'app': 'voice_app',
                'backend': STATE.backend_name,
                'model': STATE.model_status,
                'features': [
                    'faster-whisper', 'noise-filtering', 'emotion-detection',
                    'triple-beep', 'level-monitoring',
                    'playback', 'playback-queue', 'pause-resume',
                    'media-keys', 'listen-gate', 'say',
                ],
            })
        elif parsed.path == '/playback':
            self.send_json({'success': True, **STATE.snapshot()})
        else:
            self.send_json({'success': False, 'error': 'Unknown endpoint'})

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path

        if path == '/listen':
            self.handle_listen(params)
        elif path == '/say':
            self.handle_say()
        elif path == '/play':
            self.handle_play()
        elif path == '/pause':
            MANAGER.pause()
            self.send_json({'success': True, 'action': 'pause', **STATE.snapshot()})
        elif path == '/resume':
            MANAGER.resume()
            self.send_json({'success': True, 'action': 'resume', **STATE.snapshot()})
        elif path == '/toggle':
            result = MANAGER.toggle()
            self.send_json({'success': True, 'action': result, **STATE.snapshot()})
        elif path == '/skip':
            MANAGER.skip()
            self.send_json({'success': True, 'action': 'skip', **STATE.snapshot()})
        elif path == '/stop':
            MANAGER.stop_all()
            self.send_json({'success': True, 'action': 'stop', **STATE.snapshot()})
        else:
            self.send_json({'success': False, 'error': 'Unknown endpoint'})

    def handle_say(self):
        body = self.read_body_json()
        text = (body.get('text') or '').strip()
        if not text:
            self.send_json({'success': False, 'error': 'text required'})
            return
        d = get_tts_defaults()
        voice = body.get('voice') or d['voice']
        speed = float(body.get('speed') or d['speed'])
        pitch = body.get('pitch') or d['pitch']
        volume = float(body.get('volume') or d['volume'])
        try:
            mp3 = generate_tts(text, voice, speed, pitch)
        except Exception as e:
            self.send_json({'success': False, 'error': f'TTS generation failed: {e}'})
            return
        pid = MANAGER.enqueue(mp3, text, volume, delete_after=True)
        STATE.log_transcript("assistant", text)
        self.send_json({'success': True, 'id': pid, 'queued': True})

    def handle_play(self):
        body = self.read_body_json()
        path = body.get('path')
        if not path or not os.path.exists(path):
            self.send_json({'success': False, 'error': 'path missing or not found'})
            return
        volume = float(body.get('volume') or get_tts_defaults()['volume'])
        text = body.get('text') or os.path.basename(path)
        delete_after = bool(body.get('delete_after', True))
        pid = MANAGER.enqueue(path, text, volume, delete_after=delete_after)
        self.send_json({'success': True, 'id': pid, 'queued': True})

    def handle_listen(self, params):
        # THE GATE: wait for the playback queue to fully drain (pause stalls
        # this indefinitely) before beeping and recording. This is what makes
        # "switch back to listening" trigger on playback end, not output end.
        gate_start = time.time()
        gated = False
        while MANAGER.busy():
            gated = True
            if time.time() - gate_start > LISTEN_GATE_MAX_SECS:
                self.send_json({'success': False,
                                'error': 'listen gate timeout: playback still active/paused'})
                return
            time.sleep(0.1)
        if gated:
            log(f"Listen gate held {time.time() - gate_start:.1f}s for playback to finish")
            time.sleep(0.25)  # small breath between Claude's audio and the beep

        cfg = get_listen_defaults()
        timeout = int(params.get('timeout', [60])[0])
        skip_emotion = params.get('skip_emotion', ['true'])[0].lower() == 'true'
        skip_filter = params.get('skip_filter', [str(not cfg["noise_filter_enabled"]).lower()])[0].lower() == 'true'
        silence_timeout = float(params.get('silence_timeout', [cfg["silence_timeout"]])[0])
        min_speech_duration = float(params.get('min_speech_duration', [cfg["min_speech_duration"]])[0])
        rms_threshold = float(params.get('rms_threshold', [cfg["rms_threshold"]])[0])
        result = capture_voice(timeout, skip_emotion, skip_filter,
                               silence_timeout, min_speech_duration, rms_threshold)
        self.send_json(result)


# ═══════════════════════════════════════════════════════════════════
# UI (tkinter — dark, single window)
# ═══════════════════════════════════════════════════════════════════
COLORS = {
    "bg": "#16171c", "panel": "#1f2128", "text": "#e8e8ee", "dim": "#8b8d98",
    "speaking": "#3b82f6", "paused": "#f59e0b", "listening": "#22c55e",
    "idle": "#4b4d57", "accent": "#7c5cff", "error": "#ef4444",
}

STATE_LABELS = {
    AppState.SPEAKING: ("● SPEAKING", "speaking"),
    AppState.PAUSED: ("⏸ PAUSED — listening on hold", "paused"),
    AppState.LISTENING: ("🎤 LISTENING", "listening"),
    AppState.IDLE: ("○ IDLE", "idle"),
}


def run_ui(always_on_top):
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title(f"{APP_NAME} v{APP_VERSION}")
    root.geometry("420x600")
    root.minsize(360, 480)
    root.configure(bg=COLORS["bg"])
    if always_on_top:
        root.attributes("-topmost", True)

    title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
    state_font = tkfont.Font(family="Segoe UI", size=15, weight="bold")
    body_font = tkfont.Font(family="Segoe UI", size=10)
    small_font = tkfont.Font(family="Segoe UI", size=9)
    btn_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

    # Header
    header = tk.Frame(root, bg=COLORS["bg"])
    header.pack(fill="x", padx=16, pady=(14, 6))
    tk.Label(header, text=APP_NAME, font=title_font,
             bg=COLORS["bg"], fg=COLORS["text"]).pack(side="left")
    backend_lbl = tk.Label(header, text="", font=small_font,
                           bg=COLORS["bg"], fg=COLORS["dim"])
    backend_lbl.pack(side="right")

    # State banner
    state_lbl = tk.Label(root, text="○ IDLE", font=state_font,
                         bg=COLORS["idle"], fg="#ffffff", pady=10)
    state_lbl.pack(fill="x", padx=16, pady=(4, 8))

    # Now playing text
    now_frame = tk.Frame(root, bg=COLORS["panel"])
    now_frame.pack(fill="x", padx=16, pady=(0, 8))
    now_lbl = tk.Label(now_frame, text="", font=body_font, bg=COLORS["panel"],
                       fg=COLORS["text"], wraplength=370, justify="left",
                       anchor="w", padx=10, pady=8)
    now_lbl.pack(fill="x")

    # Progress bar (canvas)
    prog_canvas = tk.Canvas(root, height=6, bg=COLORS["panel"],
                            highlightthickness=0)
    prog_canvas.pack(fill="x", padx=16, pady=(0, 10))

    # Controls
    ctrl = tk.Frame(root, bg=COLORS["bg"])
    ctrl.pack(fill="x", padx=16, pady=(0, 8))

    def styled_btn(parent, text, cmd, primary=False):
        b = tk.Button(parent, text=text, command=cmd, font=btn_font,
                      bg=COLORS["accent"] if primary else COLORS["panel"],
                      fg="#ffffff", activebackground=COLORS["accent"],
                      activeforeground="#ffffff", relief="flat",
                      padx=14, pady=6, bd=0, cursor="hand2")
        return b

    toggle_btn = styled_btn(ctrl, "⏯  Pause", lambda: MANAGER.toggle(), primary=True)
    toggle_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
    skip_btn = styled_btn(ctrl, "⏭  Skip", lambda: MANAGER.skip())
    skip_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
    stop_btn = styled_btn(ctrl, "⏹  Stop", lambda: MANAGER.stop_all())
    stop_btn.pack(side="left", expand=True, fill="x")

    # Mic level
    mic_frame = tk.Frame(root, bg=COLORS["bg"])
    mic_frame.pack(fill="x", padx=16, pady=(0, 8))
    tk.Label(mic_frame, text="MIC", font=small_font, bg=COLORS["bg"],
             fg=COLORS["dim"]).pack(side="left", padx=(0, 8))
    mic_canvas = tk.Canvas(mic_frame, height=8, bg=COLORS["panel"],
                           highlightthickness=0)
    mic_canvas.pack(side="left", expand=True, fill="x")

    # Transcript
    tk.Label(root, text="TRANSCRIPT", font=small_font, bg=COLORS["bg"],
             fg=COLORS["dim"], anchor="w").pack(fill="x", padx=16)
    txt = tk.Text(root, bg=COLORS["panel"], fg=COLORS["text"], font=body_font,
                  relief="flat", wrap="word", state="disabled", padx=10, pady=8)
    txt.pack(fill="both", expand=True, padx=16, pady=(4, 8))
    txt.tag_configure("user", foreground=COLORS["listening"])
    txt.tag_configure("assistant", foreground=COLORS["speaking"])
    txt.tag_configure("time", foreground=COLORS["dim"])

    # Footer
    footer = tk.Label(root, text="", font=small_font, bg=COLORS["bg"],
                      fg=COLORS["dim"], anchor="w")
    footer.pack(fill="x", padx=16, pady=(0, 10))

    last_transcript_len = [0]

    def refresh_body():
        snap = STATE.snapshot()
        label, color_key = STATE_LABELS.get(snap["state"], ("○ IDLE", "idle"))
        state_lbl.config(text=label, bg=COLORS[color_key])
        now_lbl.config(text=snap["text"][:280] if snap["text"] else "—")
        backend_lbl.config(text=f"{snap['backend']} · whisper: {snap['model']}")

        # Pause button reflects engaged state: amber + Resume while paused
        if snap["state"] == AppState.PAUSED:
            toggle_btn.config(text="▶  Resume", bg=COLORS["paused"],
                              activebackground=COLORS["paused"])
        else:
            toggle_btn.config(text="⏯  Pause", bg=COLORS["accent"],
                              activebackground=COLORS["accent"])

        # progress
        prog_canvas.delete("all")
        w = prog_canvas.winfo_width()
        if snap["duration_ms"] > 0 and w > 1:
            frac = min(snap["position_ms"] / snap["duration_ms"], 1.0)
            prog_canvas.create_rectangle(0, 0, w * frac, 8,
                                         fill=COLORS[color_key], width=0)
        # mic level
        mic_canvas.delete("all")
        mw = mic_canvas.winfo_width()
        if mw > 1 and snap["recording"]:
            mic_canvas.create_rectangle(0, 0, mw * STATE.mic_level, 8,
                                        fill=COLORS["listening"], width=0)

        q = f"queue: {snap['queue']}" if snap["queue"] else "queue: empty"
        err = f"  ·  ⚠ {snap['error'][:60]}" if snap["error"] else ""
        footer.config(text=f"{q}  ·  port {PORT}{err}")

        # transcript tail
        with STATE.lock:
            entries = list(STATE.transcript)
        if len(entries) != last_transcript_len[0]:
            last_transcript_len[0] = len(entries)
            txt.config(state="normal")
            txt.delete("1.0", "end")
            for role, text_, ts in entries[-12:]:
                who = "You" if role == "user" else "Claude"
                txt.insert("end", f"{ts} ", "time")
                txt.insert("end", f"{who}: ", role)
                txt.insert("end", f"{text_}\n")
            txt.see("end")
            txt.config(state="disabled")

    def refresh():
        # Never let a transient error kill the refresh chain — a dead
        # after-loop means the UI silently freezes on stale state.
        try:
            refresh_body()
        except Exception as e:
            log(f"UI refresh error (continuing): {e}")
        finally:
            root.after(150, refresh)

    root.after(150, refresh)

    def on_close():
        log("Window closed — shutting down")
        try:
            MANAGER.stop_all()
            MANAGER.close()
        except Exception:
            pass
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.bind("<space>", lambda e: MANAGER.toggle())
    root.mainloop()


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    global MANAGER
    if sys.platform != "win32":
        print(
            "The Voice App window is currently Windows-only — it uses Windows\n"
            "media sessions (SMTC) for native headset pause/resume.\n"
            "On macOS, run ./START_VOICE_SERVER.sh for the terminal listening\n"
            "server instead (see README → Platform support)."
        )
        sys.exit(1)
    log(f"{APP_NAME} v{APP_VERSION} starting (config: {VOICE_CONFIG_PATH})")

    pb_cfg = get_playback_config()
    MANAGER = PlaybackManager(pb_cfg["backend"])

    # Media-key hook only for the subproc backend — winsdk gets the headset
    # button natively through its SMTC session (hook would double-toggle).
    if MANAGER.player.name == "subproc" and pb_cfg["media_key_hook"]:
        MediaKeyHook(MANAGER)

    load_whisper_async()

    try:
        server = ThreadingHTTPServer(('localhost', PORT), VoiceHandler)
    except OSError as e:
        log(f"FATAL: cannot bind port {PORT} ({e}).")
        log("Another voice server is probably running — close the old "
            "voice_server.py terminal and restart this app.")
        try:
            import tkinter.messagebox as mb
            import tkinter as tk
            r = tk.Tk(); r.withdraw()
            mb.showerror(APP_NAME, f"Port {PORT} is already in use.\n\n"
                         "Close the old voice server terminal, then restart this app.")
        except Exception:
            pass
        sys.exit(1)

    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    log(f"HTTP API on http://localhost:{PORT}  (POST /say /play /pause /resume /toggle /skip /stop /listen)")

    if "--no-ui" in sys.argv:
        log("Headless mode (--no-ui). Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        run_ui(pb_cfg["always_on_top"])


if __name__ == "__main__":
    main()
