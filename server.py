#!/usr/bin/env python3
"""
Voice MCP Server - Full conversation mode with Edge TTS
"""

from mcp.server.fastmcp import FastMCP
import os
import platform
import shutil
import urllib.request
import json
import asyncio
import subprocess
import tempfile
import nest_asyncio

nest_asyncio.apply()  # Allow nested event loops

mcp = FastMCP("Voice")


def _play_generated_audio(audio_path: str) -> None:
    if platform.system() == "Darwin":
        subprocess.run(["afplay", audio_path], check=True)
        return

    # Convert MP3 to WAV and play with simpleaudio (no delay)
    from pydub import AudioSegment
    import simpleaudio as sa

    # Set ffmpeg path for pydub (env var > PATH lookup > bare name)
    FFMPEG_PATH = os.environ.get("VOICE_FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
    AudioSegment.converter = FFMPEG_PATH

    audio = AudioSegment.from_mp3(audio_path)
    wav_path = audio_path.replace('.mp3', '.wav')
    audio.export(wav_path, format='wav')

    wave_obj = sa.WaveObject.from_wave_file(wav_path)
    play_obj = wave_obj.play()
    play_obj.wait_done()


@mcp.tool()
def speak(text: str, voice: str = "en-GB-RyanNeural", rate: str = "-15%") -> str:
    """
    Speak text aloud using Windows TTS.

    Args:
        text: What to say
        voice: Voice name (default en-GB-RyanNeural)
        rate: Speaking rate, e.g. "-20%", "+10%", "-15%" (default -15%)
    """
    try:
        import edge_tts

        # Create temp file for audio
        temp_path = os.path.join(tempfile.gettempdir(), "claude_voice.mp3")

        # Generate speech with edge-tts
        async def generate():
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(temp_path)

        asyncio.run(generate())

        _play_generated_audio(temp_path)

        return "spoke"
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def listen_for_speech(timeout: int = 30) -> str:
    """
    Listen for voice input via standalone server.

    Requires voice_server.py running separately.
    Returns transcribed speech or error.

    Args:
        timeout: Max seconds to wait
    """
    try:
        url = f"http://localhost:5123/listen?timeout={timeout}"
        req = urllib.request.Request(url, method='POST')

        with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
            result = json.loads(resp.read().decode())
            if result.get('success'):
                return result.get('text', '')
            else:
                return f"[ERROR: {result.get('error', 'Unknown')}]"
    except urllib.error.URLError:
        return "[ERROR: Voice server not running. Start: python voice_server.py]"
    except Exception as e:
        return f"[ERROR: {str(e)}]"

@mcp.tool()
def start_voice_mode() -> str:
    """
    Check if voice server is ready for conversation mode.

    Returns status. If ready, Claude should:
    1. Call listen_for_speech() to hear user
    2. Generate response
    3. Call speak() to say it
    4. Repeat until user says "stop" or "exit"
    """
    try:
        url = "http://localhost:5123/status"
        with urllib.request.urlopen(url, timeout=2) as resp:
            result = json.loads(resp.read().decode())
            if result.get('success'):
                return "READY - Voice server running. Entering conversation mode."
            return "ERROR - Server responded but not ready"
    except Exception:
        return "ERROR - Voice server not running. Start it first: python voice_server.py"

if __name__ == "__main__":
    mcp.run()
