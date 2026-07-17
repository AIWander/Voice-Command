import json
import tempfile
import unittest
from pathlib import Path

from voice_interrupt import (
    RESPONSE_INSTRUCTION,
    build_interruption_context,
    decorate_listen_result,
    is_empty_capture,
    load_phrase_override,
    match_trigger,
    normalize_trigger_phrases,
    save_phrase_override,
)


class TriggerPhraseTests(unittest.TestCase):
    def test_default_and_dedup(self):
        self.assertEqual(normalize_trigger_phrases(None), ["umm"])
        self.assertEqual(
            normalize_trigger_phrases(" Umm, hey Claude, UMM "),
            ["umm", "hey claude"],
        )

    def test_filler_variants_match_umm(self):
        for transcript in ("Um.", "umm", "UHM", "well, ummmm, wait"):
            with self.subTest(transcript=transcript):
                self.assertEqual(match_trigger(transcript, ["umm"]), "umm")

    def test_word_boundaries_prevent_substring_matches(self):
        self.assertIsNone(match_trigger("umbrella", ["umm"]))
        self.assertIsNone(match_trigger("summary", ["umm"]))

    def test_empty_runtime_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            save_phrase_override(" , ")


class PhraseSettingsTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "interrupt-listener.json"
            phrases, written = save_phrase_override("umm, excuse me", path)
            self.assertEqual(phrases, ["umm", "excuse me"])
            self.assertEqual(written, path)
            self.assertEqual(load_phrase_override(path), phrases)
            self.assertEqual(json.loads(path.read_text())["schema"], 1)

    def test_invalid_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "interrupt-listener.json"
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(load_phrase_override(path))


class InterruptionContractTests(unittest.TestCase):
    def test_context_and_result_contract(self):
        context = build_interruption_context(
            "wake_phrase",
            "umm",
            {"text": "original answer", "position_ms": 2500, "duration_ms": 10000},
            ["queued follow-up"],
        )
        self.assertEqual(context["played_fraction"], 0.25)
        self.assertEqual(context["prior_response"], "original answer")
        result = decorate_listen_result(
            {"success": True, "text": "new detail"}, "wake_phrase", context
        )
        self.assertEqual(result["listen_reason"], "wake_phrase")
        self.assertEqual(result["response_instruction"], RESPONSE_INSTRUCTION)
        self.assertEqual(result["interruption"]["queued_responses"], ["queued follow-up"])

    def test_empty_capture_classification(self):
        self.assertTrue(is_empty_capture({"success": False, "error": "No speech detected"}))
        self.assertTrue(
            is_empty_capture({"success": False, "error": "Could not understand audio"})
        )
        self.assertFalse(is_empty_capture({"success": False, "error": "microphone missing"}))


if __name__ == "__main__":
    unittest.main()
