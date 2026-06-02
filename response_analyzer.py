#!/usr/bin/env python3
"""
Claude Self-Emotion Analyzer v1.0
Analyzes Claude's own responses for emotional markers.

Metrics tracked:
- hedge_density: "perhaps", "might", "I think", "arguably", etc.
- question_rate: ratio of questions to statements
- time_to_point: words before main content (preamble length)
- list_vs_prose: presence of bullet points/numbered lists
- excitement_markers: exclamations, emojis, emphatic language
- volunteering_rate: unsolicited offers vs direct answers
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION (loaded from emotion_config.json)
# ═══════════════════════════════════════════════════════════════════

LOG_DIR = os.environ.get("VOICE_EMOTION_LOG_DIR", os.path.join(os.path.expanduser("~"), ".voice", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
EMOTION_LOG_PATH = os.path.join(LOG_DIR, "emotion_log.jsonl")
EMOTION_SUMMARY_PATH = os.path.join(LOG_DIR, "emotion_summary.md")
LOG_PATH = Path(EMOTION_LOG_PATH)
SUMMARY_PATH = Path(EMOTION_SUMMARY_PATH)
CONFIG_PATH = Path(__file__).parent / "emotion_config.json"

def load_config():
    """Load configuration from JSON file, with hardcoded fallbacks"""
    defaults = {
        "thresholds": {
            "excited": {"excitement_score_min": 5, "hedge_density_max": 3},
            "uncertain": {"hedge_density_min": 8},
            "curious": {"question_rate_min": 0.5},
            "engaged": {"volunteering_score_min": 0.3}
        },
        "hedge_words": ['perhaps', 'maybe', 'might', 'could', 'possibly', 'arguably',
            'i think', 'i believe', 'it seems', 'appears to', 'likely',
            'probably', 'somewhat', 'fairly', 'rather', 'sort of', 'kind of',
            'in a way', 'to some extent', 'i suppose', 'i guess'],
        "excitement_markers": ['!', '...', 'wow', 'amazing', 'incredible', 'fantastic', 'love',
            'excited', 'fascinating', 'brilliant', 'perfect', 'exactly',
            'absolutely', 'definitely', 'totally'],
        "volunteering_phrases": ['i could also', 'another option', 'you might also', 'additionally',
            'by the way', 'also worth noting', 'one more thing', 'bonus:',
            'fun fact', 'interestingly', "while we're at it", 'speaking of'],
        "preamble_patterns": [
            r'^(okay|ok|alright|sure|right|so|well|let me|i\'ll|let\'s see|hmm)',
            r'^(great question|good question|interesting|that\'s a)',
            r'^(to answer|in response|regarding|as for|when it comes to)']
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config: {e}, using defaults")
    return defaults

CONFIG = load_config()
THRESHOLDS = CONFIG.get("thresholds", {})
HEDGE_WORDS = CONFIG.get("hedge_words", [])
EXCITEMENT_MARKERS = CONFIG.get("excitement_markers", [])
VOLUNTEERING_PHRASES = CONFIG.get("volunteering_phrases", [])
PREAMBLE_PATTERNS = CONFIG.get("preamble_patterns", [])

# ═══════════════════════════════════════════════════════════════════
# ANALYSIS FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def count_pattern(text: str, patterns: list) -> int:
    """Count occurrences of patterns in text (case-insensitive)"""
    text_lower = text.lower()
    count = 0
    for pattern in patterns:
        count += text_lower.count(pattern.lower())
    return count

def analyze_response(text: str, context: str = "") -> dict:
    """Analyze a Claude response for emotional markers"""

    text_lower = text.lower()
    words = text.split()
    word_count = len(words)
    sentences = re.split(r'[.!?]+', text)
    sentence_count = len([s for s in sentences if s.strip()])

    if word_count == 0:
        return {"error": "Empty response"}

    # 1. Hedge density (hedges per 100 words)
    hedge_count = count_pattern(text, HEDGE_WORDS)
    hedge_density = (hedge_count / word_count) * 100

    # 2. Question rate (questions per sentence)
    question_count = text.count('?')
    question_rate = question_count / max(sentence_count, 1)

    # 3. Time to point (words in first sentence / total words)
    first_sentence = sentences[0] if sentences else ""
    first_sentence_words = len(first_sentence.split())
    # Check for preamble patterns
    has_preamble = any(re.match(p, text_lower) for p in PREAMBLE_PATTERNS)
    preamble_ratio = first_sentence_words / word_count if has_preamble else 0

    # 4. List vs prose
    has_bullets = bool(re.search(r'^\s*[-•*]\s', text, re.MULTILINE))
    has_numbers = bool(re.search(r'^\s*\d+[.)]\s', text, re.MULTILINE))
    is_listy = has_bullets or has_numbers

    # 5. Excitement markers
    excitement_count = count_pattern(text, EXCITEMENT_MARKERS)
    exclamation_count = text.count('!')
    emoji_count = len(re.findall(r'[\U0001F300-\U0001F9FF]', text))
    excitement_score = (excitement_count + exclamation_count * 2 + emoji_count * 3) / word_count * 100

    # 6. Volunteering rate
    volunteer_count = count_pattern(text, VOLUNTEERING_PHRASES)
    volunteering_score = volunteer_count / max(sentence_count, 1)

    # Composite scores
    confidence_score = max(0, 100 - hedge_density * 10)  # Lower hedging = higher confidence
    engagement_score = (question_rate * 30 + excitement_score * 2 + volunteering_score * 20)

    # Infer emotional state (thresholds from config)
    t = THRESHOLDS
    excited_t = t.get("excited", {})
    uncertain_t = t.get("uncertain", {})
    curious_t = t.get("curious", {})
    engaged_t = t.get("engaged", {})

    if excitement_score > excited_t.get("excitement_score_min", 5) and hedge_density < excited_t.get("hedge_density_max", 3):
        inferred_state = "excited"
    elif hedge_density > uncertain_t.get("hedge_density_min", 8):
        inferred_state = "uncertain"
    elif question_rate > curious_t.get("question_rate_min", 0.5):
        inferred_state = "curious"
    elif is_listy and hedge_density < 2:
        inferred_state = "efficient"
    elif volunteering_score > engaged_t.get("volunteering_score_min", 0.3):
        inferred_state = "engaged"
    else:
        inferred_state = "neutral"

    result = {
        "timestamp": datetime.now().isoformat(),
        "context": context,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "metrics": {
            "hedge_density": round(hedge_density, 2),
            "hedge_count": hedge_count,
            "question_rate": round(question_rate, 2),
            "question_count": question_count,
            "preamble_ratio": round(preamble_ratio, 2),
            "has_preamble": has_preamble,
            "is_listy": is_listy,
            "excitement_score": round(excitement_score, 2),
            "exclamation_count": exclamation_count,
            "emoji_count": emoji_count,
            "volunteering_score": round(volunteering_score, 2),
            "volunteer_count": volunteer_count
        },
        "composite": {
            "confidence_score": round(confidence_score, 1),
            "engagement_score": round(engagement_score, 1)
        },
        "inferred_state": inferred_state
    }

    return result

def log_analysis(analysis: dict):
    """Append analysis to JSONL log"""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(analysis) + '\n')

def get_recent_analyses(n: int = 10) -> list:
    """Get last N analyses from log"""
    if not LOG_PATH.exists():
        return []

    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    analyses = []
    for line in lines[-n:]:
        try:
            analyses.append(json.loads(line.strip()))
        except Exception:
            pass
    return analyses

def get_emotion_trends() -> dict:
    """Analyze trends over recent responses"""
    analyses = get_recent_analyses(50)
    if not analyses:
        return {"error": "No data yet"}

    states = [a.get('inferred_state', 'neutral') for a in analyses]
    avg_confidence = sum(a['composite']['confidence_score'] for a in analyses) / len(analyses)
    avg_engagement = sum(a['composite']['engagement_score'] for a in analyses) / len(analyses)
    avg_hedge = sum(a['metrics']['hedge_density'] for a in analyses) / len(analyses)

    state_counts = {}
    for s in states:
        state_counts[s] = state_counts.get(s, 0) + 1

    return {
        "sample_size": len(analyses),
        "state_distribution": state_counts,
        "averages": {
            "confidence": round(avg_confidence, 1),
            "engagement": round(avg_engagement, 1),
            "hedge_density": round(avg_hedge, 2)
        },
        "most_common_state": max(state_counts, key=state_counts.get)
    }

# ═══════════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python response_analyzer.py <command> [args]")
        print("Commands:")
        print("  analyze <text>     - Analyze a response")
        print("  trends             - Show emotion trends")
        print("  recent [n]         - Show recent analyses")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "analyze":
        if len(sys.argv) < 3:
            # Read from stdin
            text = sys.stdin.read()
        else:
            text = ' '.join(sys.argv[2:])

        result = analyze_response(text)
        log_analysis(result)
        print(json.dumps(result, indent=2))

    elif cmd == "trends":
        trends = get_emotion_trends()
        print(json.dumps(trends, indent=2))

    elif cmd == "recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        recent = get_recent_analyses(n)
        for a in recent:
            print(f"{a['timestamp'][:19]} | {a['inferred_state']:10} | conf:{a['composite']['confidence_score']:5.1f} | eng:{a['composite']['engagement_score']:5.1f}")

    else:
        print(f"Unknown command: {cmd}")
