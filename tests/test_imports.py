"""Smoke tests — verify source files parse and MCP tools are registered."""

import sys
import types
import unittest
import py_compile
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Mock heavy dependencies before importing project modules
_MOCKS = [
    "mcp", "mcp.server", "mcp.server.fastmcp",
    "faster_whisper", "edge_tts", "pyaudio", "simpleaudio",
    "pydub", "pydub.effects", "scipy", "scipy.signal",
    "numpy", "nest_asyncio",
]


def _install_mocks():
    """Insert lightweight mocks for unavailable native packages."""
    for mod_name in _MOCKS:
        if mod_name not in sys.modules:
            mod = types.ModuleType(mod_name)
            if mod_name == "mcp.server.fastmcp":
                # FastMCP must be callable and return an object with .tool()
                class _FakeMCP:
                    def __init__(self, *a, **kw):
                        self._tools = []

                    def tool(self, *a, **kw):
                        def decorator(fn):
                            self._tools.append(fn.__name__)
                            return fn
                        return decorator

                mod.FastMCP = _FakeMCP
            if mod_name == "nest_asyncio":
                mod.apply = lambda: None
            sys.modules[mod_name] = mod


_install_mocks()


class TestServerModule(unittest.TestCase):
    def test_server_module_imports(self):
        """server.py imports and exposes an 'mcp' FastMCP instance."""
        import importlib
        spec = importlib.util.spec_from_file_location("server", os.path.join(ROOT, "server.py"))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        self.assertTrue(hasattr(server, "mcp"), "server.py must expose 'mcp' attribute")
        # Confirm the three expected tool functions exist
        for name in ("speak", "listen_for_speech", "start_voice_mode"):
            self.assertTrue(hasattr(server, name), f"server.py missing tool function: {name}")


class TestResponseAnalyzer(unittest.TestCase):
    def test_response_analyzer_imports(self):
        """response_analyzer.py parses without error."""
        import importlib
        spec = importlib.util.spec_from_file_location(
            "response_analyzer", os.path.join(ROOT, "response_analyzer.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)


class TestVoiceSourcesCompile(unittest.TestCase):
    def test_voice_sources_compile(self):
        """The listener, interruption helpers, and Voice App parse cleanly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            for filename in ("voice_server.py", "voice_interrupt.py", "voice_app.py"):
                with self.subTest(filename=filename):
                    source = os.path.join(ROOT, filename)
                    compiled = os.path.join(temp_dir, f"{filename}c")
                    py_compile.compile(source, cfile=compiled, doraise=True)


if __name__ == "__main__":
    unittest.main()
