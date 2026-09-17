import http.client
import sys
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

PORT = voice_app.PORT


def make_headers(**fields):
    """Build the case-insensitive header object BaseHTTPRequestHandler really uses."""
    headers = http.client.HTTPMessage()
    for name, value in fields.items():
        headers[name.replace("_", "-")] = value
    return headers


class RequestRefusalTests(unittest.TestCase):
    def test_local_clients_without_origin_are_allowed(self):
        # voice-mcp (reqwest), curl and the hooks all look like this.
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host):
                self.assertIsNone(voice_app._request_refusal(make_headers(Host=f"{host}:{PORT}")))

    def test_host_match_ignores_case(self):
        self.assertIsNone(voice_app._request_refusal(make_headers(Host=f"LocalHost:{PORT}")))

    def test_dns_rebinding_host_is_refused(self):
        refusal = voice_app._request_refusal(make_headers(Host=f"attacker.example:{PORT}"))
        self.assertEqual(refusal, "host not allowed")

    def test_missing_or_wrong_port_host_is_refused(self):
        for host in (None, "localhost", "localhost:80", f"0.0.0.0:{PORT}"):
            with self.subTest(host=host):
                headers = make_headers() if host is None else make_headers(Host=host)
                self.assertEqual(voice_app._request_refusal(headers), "host not allowed")

    def test_cross_origin_browser_request_is_refused(self):
        for origin in ("https://attacker.example", "null", f"http://localhost:{PORT + 1}"):
            with self.subTest(origin=origin):
                headers = make_headers(Host=f"localhost:{PORT}", Origin=origin)
                self.assertEqual(voice_app._request_refusal(headers), "cross-origin request refused")

    def test_same_origin_browser_request_is_allowed(self):
        headers = make_headers(Host=f"localhost:{PORT}", Origin=f"http://localhost:{PORT}")
        self.assertIsNone(voice_app._request_refusal(headers))

    def test_cross_site_fetch_metadata_is_refused(self):
        headers = make_headers(Host=f"localhost:{PORT}", Sec_Fetch_Site="cross-site")
        self.assertEqual(voice_app._request_refusal(headers), "cross-site request refused")


class HandlerRefusesBeforeSideEffectsTests(unittest.TestCase):
    def make_handler(self, command, path, headers):
        handler = voice_app.VoiceHandler.__new__(voice_app.VoiceHandler)
        handler.command = command
        handler.path = path
        handler.headers = headers
        handler.send_json = mock.Mock()
        return handler

    def test_cross_site_post_never_reaches_the_manager(self):
        manager = mock.Mock()
        handler = self.make_handler("POST", "/stop", make_headers(
            Host=f"localhost:{PORT}", Origin="https://attacker.example"))
        with mock.patch.object(voice_app, "MANAGER", manager), \
                mock.patch.object(voice_app, "log"):
            handler.do_POST()
        manager.stop_all.assert_not_called()
        self.assertEqual(handler.send_json.call_args.kwargs.get("code"), 403)

    def test_rebinding_post_never_opens_the_microphone_or_saves_phrases(self):
        listener = mock.Mock()
        for path in ("/listen", "/interruption-listener/config"):
            with self.subTest(path=path):
                handler = self.make_handler("POST", path, make_headers(Host=f"attacker.example:{PORT}"))
                handler.handle_listen = mock.Mock()
                handler.read_body_json = mock.Mock(return_value={"phrases": "x"})
                with mock.patch.object(voice_app, "INTERRUPTION_LISTENER", listener), \
                        mock.patch.object(voice_app, "log"):
                    handler.do_POST()
                handler.handle_listen.assert_not_called()
                listener.set_phrases.assert_not_called()
                self.assertEqual(handler.send_json.call_args.kwargs.get("code"), 403)

    def test_rebinding_get_cannot_read_status(self):
        handler = self.make_handler("GET", "/playback", make_headers(Host=f"attacker.example:{PORT}"))
        with mock.patch.object(voice_app, "log"):
            handler.do_GET()
        handler.send_json.assert_called_once()
        self.assertEqual(handler.send_json.call_args.kwargs.get("code"), 403)

    def test_local_client_post_still_dispatches(self):
        manager = mock.Mock()
        state = mock.Mock()
        state.snapshot.return_value = {}
        handler = self.make_handler("POST", "/stop", make_headers(Host=f"localhost:{PORT}"))
        with mock.patch.object(voice_app, "MANAGER", manager), \
                mock.patch.object(voice_app, "STATE", state):
            handler.do_POST()
        manager.stop_all.assert_called_once()
        self.assertTrue(handler.send_json.call_args.args[0]["success"])


if __name__ == "__main__":
    unittest.main()
