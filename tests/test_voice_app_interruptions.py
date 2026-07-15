import sys
import threading
import types
import unittest
from unittest import mock

# CI deliberately avoids installing the native audio/scientific stack.  The
# state-machine tests do not exercise DSP, so provide import-only shims when
# those modules are absent (or were already shimmed by test_imports.py).
if "numpy" not in sys.modules:
    try:
        import numpy  # noqa: F401
    except ModuleNotFoundError:
        sys.modules["numpy"] = types.ModuleType("numpy")

if "scipy" not in sys.modules:
    sys.modules["scipy"] = types.ModuleType("scipy")
if "scipy.fft" not in sys.modules:
    fft_module = types.ModuleType("scipy.fft")
    fft_module.fft = lambda value: value
    sys.modules["scipy.fft"] = fft_module
if "scipy.signal" not in sys.modules:
    sys.modules["scipy.signal"] = types.ModuleType("scipy.signal")
sys.modules["scipy.signal"].butter = lambda *args, **kwargs: ((), ())
sys.modules["scipy.signal"].lfilter = lambda _b, _a, value: value

import voice_app  # noqa: E402


class FakePlayer:
    name = "fake"

    def __init__(self):
        self.paused = False
        self.stopped = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True

    def poll(self):
        return ("paused" if self.paused else "playing", 0, 1000, False, None)

    def close(self):
        pass


class PlaybackManagerInterruptionTests(unittest.TestCase):
    def setUp(self):
        voice_app.STATE.set(
            state=voice_app.AppState.SPEAKING,
            current_text="the complete prior response",
            position_ms=250,
            duration_ms=1000,
        )
        patcher = mock.patch.object(voice_app, "make_player", return_value=FakePlayer())
        self.addCleanup(patcher.stop)
        patcher.start()
        self.manager = voice_app.PlaybackManager("fake")
        self.manager._active.set()

    def test_wake_handoff_pauses_and_preserves_context(self):
        self.assertTrue(self.manager.request_wake_handoff("umm"))
        self.assertTrue(self.manager.player.paused)
        self.assertTrue(self.manager.wake_handoff_pending())
        context = self.manager.wake_context()
        self.assertEqual(context["prior_response"], "the complete prior response")
        self.assertEqual(context["played_fraction"], 0.25)
        self.assertEqual(context["source"], "wake_phrase")

    def test_empty_wake_resumes_same_playback(self):
        self.manager.request_wake_handoff("umm")
        self.manager.resume_after_empty_wake()
        self.assertFalse(self.manager.player.paused)
        self.assertFalse(self.manager.wake_handoff_pending())

    def test_widget_interrupt_uses_regular_handoff_context(self):
        self.manager.interrupt()
        context = self.manager.consume_handoff_context()
        self.assertEqual(context["source"], "widget_interrupt")
        self.assertEqual(context["prior_response"], "the complete prior response")
        self.assertTrue(self.manager.player.stopped)


class FakeListener:
    def __init__(self):
        self.suspends = 0
        self.resumes = 0

    def suspend(self, wait=False, timeout=3.0):
        self.suspends += 1
        return True

    def resume_monitoring(self):
        self.resumes += 1


class FakeListenManager:
    def __init__(self, wake=False, context=None):
        self.wake = wake
        self.context = context
        self.resumed = 0
        self.completed = 0

    def gate_should_wait(self):
        return self.wake

    def exchange_stopped(self):
        return False

    def clear_stop(self):
        pass

    def wake_handoff_pending(self):
        return self.wake

    def wake_context(self):
        return dict(self.context) if self.context else None

    def resume_after_empty_wake(self):
        self.wake = False
        self.context = None
        self.resumed += 1

    def complete_wake_handoff(self):
        self.wake = False
        self.completed += 1
        return dict(self.context) if self.context else None

    def consume_handoff_context(self):
        context = self.context
        self.context = None
        return dict(context) if context else None


def run_handle_listen(manager, listener, capture_results):
    handler = voice_app.VoiceHandler.__new__(voice_app.VoiceHandler)
    sent = []
    handler.send_json = lambda data, code=200: sent.append((data, code))
    capture = mock.Mock(side_effect=capture_results)
    with (
        mock.patch.object(voice_app, "MANAGER", manager),
        mock.patch.object(voice_app, "INTERRUPTION_LISTENER", listener),
        mock.patch.object(voice_app, "capture_voice", capture),
        mock.patch.object(voice_app.time, "sleep", return_value=None),
    ):
        handler.handle_listen({})
    return sent, capture


class ListenHandoffTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "source": "wake_phrase",
            "trigger_phrase": "umm",
            "prior_response": "prior response",
            "position_ms": 100,
            "duration_ms": 1000,
            "played_fraction": 0.1,
            "queued_responses": [],
        }

    def test_new_wake_input_returns_revision_contract(self):
        manager = FakeListenManager(wake=True, context=self.context)
        listener = FakeListener()
        sent, capture = run_handle_listen(
            manager,
            listener,
            [{"success": True, "text": "new information"}],
        )
        result = sent[0][0]
        self.assertEqual(result["listen_reason"], "wake_phrase")
        self.assertEqual(result["interruption"]["prior_response"], "prior response")
        self.assertIn("preserve relevant unfinished content", result["response_instruction"])
        self.assertEqual(manager.completed, 1)
        self.assertEqual(capture.call_args.args[-1], 5.0)

    def test_empty_wake_resumes_then_natural_listener_continues(self):
        manager = FakeListenManager(wake=True, context=self.context)
        listener = FakeListener()
        sent, capture = run_handle_listen(
            manager,
            listener,
            [
                {"success": False, "error": "No speech detected"},
                {"success": True, "text": "answer after playback"},
            ],
        )
        self.assertEqual(manager.resumed, 1)
        self.assertEqual(sent[0][0]["listen_reason"], "natural_finish")
        self.assertEqual(sent[0][0]["text"], "answer after playback")
        self.assertEqual(capture.call_args_list[0].args[-1], 5.0)
        self.assertIsNone(capture.call_args_list[1].args[-1])

    def test_widget_interrupt_uses_regular_listener(self):
        context = dict(self.context, source="widget_interrupt", trigger_phrase=None)
        manager = FakeListenManager(wake=False, context=context)
        listener = FakeListener()
        sent, capture = run_handle_listen(
            manager,
            listener,
            [{"success": True, "text": "widget input"}],
        )
        self.assertEqual(sent[0][0]["listen_reason"], "widget_interrupt")
        self.assertEqual(sent[0][0]["text"], "widget input")
        self.assertIsNone(capture.call_args.args[-1])


class MonitorManager:
    def __init__(self):
        self.wake = False
        self.trigger = None

    def exchange_stopped(self):
        return False

    def wake_handoff_pending(self):
        return self.wake

    def busy(self):
        return True

    def is_paused(self):
        return False

    def request_wake_handoff(self, trigger):
        self.trigger = trigger
        self.wake = True
        return True


class FakeInputStream:
    def __init__(self):
        self.closed = False

    def read(self, count, exception_on_overflow=False):
        return b"\xf4\x01" * count

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class FakeAudioHost:
    def __init__(self):
        self.open_args = None
        self.stream = FakeInputStream()
        self.terminated = False

    def open(self, **kwargs):
        self.open_args = kwargs
        return self.stream

    def terminate(self):
        self.terminated = True


class InterruptionMonitorTests(unittest.TestCase):
    def test_phrase_monitor_uses_input_only_and_yields_mic_on_trigger(self):
        manager = MonitorManager()
        listener = voice_app.InterruptionListener.__new__(voice_app.InterruptionListener)
        listener.manager = manager
        listener.enabled = True
        listener.listen_while_paused = True
        listener.window_secs = 0.75
        listener.rms_threshold = 100.0
        listener.cooldown_secs = 0.25
        listener._phrases_lock = threading.RLock()
        listener._phrases = ["umm"]
        listener._suspend = threading.Event()
        listener._shutdown = threading.Event()
        listener._mic_idle = threading.Event()
        listener._mic_idle.set()
        listener._last_trigger_at = 0.0
        listener._transcribe_window = lambda frames: "Um."

        audio_host = FakeAudioHost()
        pyaudio_module = types.ModuleType("pyaudio")
        pyaudio_module.paInt16 = 8
        pyaudio_module.PyAudio = lambda: audio_host

        with (
            mock.patch.dict(sys.modules, {"pyaudio": pyaudio_module}),
            mock.patch.object(voice_app, "WHISPER_MODEL", object()),
        ):
            listener._monitor_playback()

        self.assertEqual(manager.trigger, "umm")
        self.assertTrue(listener._suspend.is_set())
        self.assertTrue(listener._mic_idle.is_set())
        self.assertFalse(voice_app._recording_lock.locked())
        self.assertTrue(audio_host.open_args["input"])
        self.assertNotIn("output", audio_host.open_args)
        self.assertTrue(audio_host.stream.closed)
        self.assertTrue(audio_host.terminated)


if __name__ == "__main__":
    unittest.main()
