import os
import sys
import tempfile
import types
import unittest
from unittest import mock

# Same import-only shims as the other voice_app tests: CI does not install the
# native audio/scientific stack, and these tests exercise no DSP.
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

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        pass

    def poll(self):
        return ("stopped", 0, 0, True, None)

    def close(self):
        pass


class AppGeneratedAudioTests(unittest.TestCase):
    def test_tts_file_in_tempdir_is_app_generated(self):
        path = os.path.join(tempfile.gettempdir(), "tts_abc123.mp3")
        self.assertTrue(voice_app._is_app_generated_audio(path))

    def test_arbitrary_user_file_is_not_app_generated(self):
        self.assertFalse(voice_app._is_app_generated_audio(r"C:\Users\someone\Documents\thesis.docx"))

    def test_tts_named_file_outside_tempdir_is_not_app_generated(self):
        with tempfile.TemporaryDirectory() as other:
            path = os.path.join(other, "nested", "tts_abc123.mp3")
            self.assertFalse(voice_app._is_app_generated_audio(path))

    def test_non_mp3_in_tempdir_is_not_app_generated(self):
        path = os.path.join(tempfile.gettempdir(), "tts_abc123.txt")
        self.assertFalse(voice_app._is_app_generated_audio(path))

    def test_non_string_input_is_rejected(self):
        for value in (None, "", 42, ["x"]):
            self.assertFalse(voice_app._is_app_generated_audio(value))


class CleanupNeverDeletesUserFilesTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(voice_app, "make_player", return_value=FakePlayer())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = voice_app.PlaybackManager("fake")

    def test_user_file_survives_cleanup_even_with_delete_after(self):
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "important.mp3")
            with open(victim, "wb") as f:
                f.write(b"not yours to delete")
            self.manager._cleanup({"path": victim, "delete_after": True})
            self.assertTrue(os.path.exists(victim))

    def test_app_generated_tts_file_is_still_cleaned_up(self):
        fd, path = tempfile.mkstemp(prefix="tts_", suffix=".mp3", dir=tempfile.gettempdir())
        os.close(fd)
        self.manager._cleanup({"path": path, "delete_after": True})
        self.assertFalse(os.path.exists(path))

    def test_delete_after_false_keeps_even_app_generated_file(self):
        fd, path = tempfile.mkstemp(prefix="tts_", suffix=".mp3", dir=tempfile.gettempdir())
        os.close(fd)
        try:
            self.manager._cleanup({"path": path, "delete_after": False})
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
