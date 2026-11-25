import http.client
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

TEMP = tempfile.gettempdir()


def make_app_audio():
    """Create a real tts_*.mp3 directly in the temp folder, like generate_tts does."""
    fd, path = tempfile.mkstemp(prefix="tts_", suffix=".mp3", dir=TEMP)
    os.write(fd, b"ID3 fake mp3")
    os.close(fd)
    return path


def remove_quietly(path):
    try:
        os.unlink(path)
    except OSError:
        pass


class ResolveAppGeneratedAudioTests(unittest.TestCase):
    def test_app_audio_resolves_to_its_real_path(self):
        path = make_app_audio()
        self.addCleanup(remove_quietly, path)
        self.assertEqual(voice_app._resolve_app_generated_audio(path), os.path.realpath(path))

    def test_dotdot_that_lands_back_in_temp_root_is_still_app_audio(self):
        path = make_app_audio()
        self.addCleanup(remove_quietly, path)
        with tempfile.TemporaryDirectory() as sub:
            detour = os.path.join(sub, "..", os.path.basename(path))
            self.assertEqual(voice_app._resolve_app_generated_audio(detour), os.path.realpath(path))

    def test_traversal_out_of_temp_root_is_refused(self):
        escaped = os.path.join(TEMP, "..", "tts_escape.mp3")
        self.assertIsNone(voice_app._resolve_app_generated_audio(escaped))

    def test_sibling_folder_sharing_the_temp_name_prefix_is_refused(self):
        # "<temp>_evil\tts_x.mp3" starts with the temp folder's string; the separator stops it.
        lookalike = os.path.realpath(TEMP) + "_evil" + os.sep + "tts_x.mp3"
        self.assertIsNone(voice_app._resolve_app_generated_audio(lookalike))

    def test_nested_tts_file_under_temp_is_refused(self):
        with tempfile.TemporaryDirectory() as sub:
            nested = os.path.join(sub, "tts_nested.mp3")
            with open(nested, "wb") as f:
                f.write(b"x")
            self.assertIsNone(voice_app._resolve_app_generated_audio(nested))

    def test_wrong_name_or_extension_in_temp_root_is_refused(self):
        for name in ("song.mp3", "tts_x.wav", "tts_x.mp3.exe", "xtts_y.mp3"):
            with self.subTest(name=name):
                self.assertIsNone(voice_app._resolve_app_generated_audio(os.path.join(TEMP, name)))

    def test_non_string_or_empty_input_is_refused(self):
        for value in (None, "", 42, ["x"], {"path": "x"}, "bad\x00path"):
            with self.subTest(value=value):
                self.assertIsNone(voice_app._resolve_app_generated_audio(value))

    def test_symlink_in_temp_root_pointing_outside_is_refused(self):
        with tempfile.TemporaryDirectory() as sub:
            target = os.path.join(sub, "music.mp3")
            with open(target, "wb") as f:
                f.write(b"x")
            link = os.path.join(TEMP, f"tts_link_{os.getpid()}.mp3")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError) as e:
                self.skipTest(f"symlinks unavailable here: {e}")
            self.addCleanup(remove_quietly, link)
            self.assertIsNone(voice_app._resolve_app_generated_audio(link))


class HandlePlayTests(unittest.TestCase):
    def setUp(self):
        self.manager = mock.Mock()
        self.manager.enqueue.return_value = 7
        for patcher in (
            mock.patch.object(voice_app, "MANAGER", self.manager),
            mock.patch.object(voice_app, "get_tts_defaults", return_value={"volume": 0.8}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def play(self, body):
        handler = voice_app.VoiceHandler.__new__(voice_app.VoiceHandler)
        handler.read_body_json = mock.Mock(return_value=body)
        handler.send_json = mock.Mock()
        handler.handle_play()
        handler.send_json.assert_called_once()
        call = handler.send_json.call_args
        return call.kwargs.get("code", 200), call.args[0]

    # -- allowed ------------------------------------------------------
    def test_app_generated_audio_is_queued_without_deletion_by_default(self):
        path = make_app_audio()
        self.addCleanup(remove_quietly, path)
        code, data = self.play({"path": path})
        self.assertEqual((code, data["success"], data["id"]), (200, True, 7))
        self.manager.enqueue.assert_called_once_with(
            os.path.realpath(path), os.path.basename(os.path.realpath(path)), 0.8, delete_after=False)

    def test_delete_after_is_still_honoured_for_app_audio(self):
        path = make_app_audio()
        self.addCleanup(remove_quietly, path)
        code, data = self.play({"path": path, "text": "hello", "volume": 0.5, "delete_after": True})
        self.assertEqual((code, data["success"]), (200, True))
        self.manager.enqueue.assert_called_once_with(os.path.realpath(path), "hello", 0.5, delete_after=True)

    # -- refused ------------------------------------------------------
    def assert_refused(self, body, expected_code):
        code, data = self.play(body)
        self.assertEqual(code, expected_code)
        self.assertFalse(data["success"])
        self.assertTrue(data["error"])
        self.manager.enqueue.assert_not_called()

    def test_existing_music_file_outside_app_audio_is_refused(self):
        with tempfile.TemporaryDirectory() as sub:
            music = os.path.join(sub, "favourite_song.mp3")
            with open(music, "wb") as f:
                f.write(b"ID3 music")
            self.assert_refused({"path": music, "delete_after": True}, 403)
            self.assertTrue(os.path.exists(music))

    def test_existing_non_tts_audio_in_temp_root_is_refused(self):
        fd, other = tempfile.mkstemp(prefix="song_", suffix=".mp3", dir=TEMP)
        os.close(fd)
        self.addCleanup(remove_quietly, other)
        self.assert_refused({"path": other}, 403)

    def test_traversal_and_system_paths_are_refused(self):
        for path in (os.path.join(TEMP, "..", "tts_escape.mp3"),
                     os.path.abspath(voice_app.__file__),
                     os.path.join(os.path.expanduser("~"), "tts_home.mp3")):
            with self.subTest(path=path):
                self.manager.reset_mock()
                self.assert_refused({"path": path}, 403)

    def test_refusal_does_not_reveal_whether_an_outside_file_exists(self):
        with tempfile.TemporaryDirectory() as sub:
            exists = os.path.join(sub, "real.mp3")
            with open(exists, "wb") as f:
                f.write(b"x")
            missing = os.path.join(sub, "missing.mp3")
            self.assertEqual(self.play({"path": exists}), self.play({"path": missing}))
        self.manager.enqueue.assert_not_called()

    def test_missing_app_audio_file_is_not_found(self):
        self.assert_refused({"path": os.path.join(TEMP, "tts_does_not_exist_0.mp3")}, 404)

    def test_missing_or_non_string_path_is_a_bad_request(self):
        for body in ({}, {"path": ""}, {"path": None}, {"path": 5}, {"path": ["a"]}):
            with self.subTest(body=body):
                self.manager.reset_mock()
                self.assert_refused(body, 400)


class PlayRouteTests(unittest.TestCase):
    """POST /play through do_POST, as a local client sends it."""

    def post_play(self, body, manager):
        headers = http.client.HTTPMessage()
        headers["Host"] = f"localhost:{voice_app.PORT}"
        handler = voice_app.VoiceHandler.__new__(voice_app.VoiceHandler)
        handler.command = "POST"
        handler.path = "/play"
        handler.headers = headers
        handler.read_body_json = mock.Mock(return_value=body)
        handler.send_json = mock.Mock()
        with mock.patch.object(voice_app, "MANAGER", manager), \
                mock.patch.object(voice_app, "get_tts_defaults", return_value={"volume": 1.0}):
            handler.do_POST()
        return handler.send_json.call_args

    def test_local_client_can_play_app_audio(self):
        path = make_app_audio()
        self.addCleanup(remove_quietly, path)
        manager = mock.Mock()
        manager.enqueue.return_value = 1
        call = self.post_play({"path": path}, manager)
        self.assertTrue(call.args[0]["success"])
        manager.enqueue.assert_called_once()

    def test_local_client_cannot_play_other_files(self):
        manager = mock.Mock()
        call = self.post_play({"path": os.path.abspath(voice_app.__file__)}, manager)
        self.assertEqual(call.kwargs.get("code"), 403)
        manager.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
