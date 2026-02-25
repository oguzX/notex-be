"""Intent classification for routing between Ops Mode, MCP Tool Mode, and
proposal-action intents (approve / cancel / note-only)."""

from __future__ import annotations

import re
from enum import Enum


class IntentType(Enum):
    """Classification of user intent."""

    OPS_MODE = "ops"  # Task/note management operations
    TOOL_MODE = "tool"  # External tool calls (weather, FX, etc.)
    APPROVE_PROPOSAL = "approve_proposal"  # User confirms / approves a pending proposal
    CANCEL_PROPOSAL = "cancel_proposal"  # User cancels a pending proposal
    NOTE_ONLY = "note_only"  # Store message without any operation


# ── Pattern sets ──────────────────────────────────────────────────────

# Patterns that signal the user is *approving* a pending proposal.
APPROVE_KEYWORDS: list[str] = [
    # Turkish
    r"\bonayladım\b",
    r"\bonaylıyorum\b",
    r"\btamam(?:\s+(?:bu|bunu|şunu))?\b",
    r"\bevet\b",
    r"\bkabul\b",
    r"\buygula\b",
    r"\bkaydet\b",
    r"\byap\b",
    r"\bolur\b",
    # English
    r"\bapprove\b",
    r"\bconfirm\b",
    r"\byes\b",
    r"\baccept\b",
    r"\bapply\b",
    r"\blgtm\b",
    r"\bok\b",
    r"\bokay\b",
    r"\bgo ahead\b",
    r"\bdo it\b",
    r"\bsave it\b",
]

# Patterns that signal the user wants to *cancel* a pending proposal.
CANCEL_KEYWORDS: list[str] = [
    # Turkish
    r"\biptal\b",
    r"\bvazgeç\b",
    r"\bvazgec\b",
    r"\bistemiyorum\b",
    r"\bhayır\b",
    r"\bhayir\b",
    r"\bgeri al\b",
    # English
    r"\bcancel\b",
    r"\bnevermind\b",
    r"\bnever mind\b",
    r"\bno\b",
    r"\bdiscard\b",
    r"\bdon'?t\b",
    r"\bundo\b",
    r"\bforget it\b",
    r"\bskip\b",
]

# Keywords that indicate tool mode (weather, currency, etc.)
TOOL_MODE_KEYWORDS = [
    # Weather keywords - English
    r"\bweather\b",
    r"\btemperature\b",
    r"\bforecast\b",
    r"\bclimate\b",
    r"\brain\b",
    r"\bhumidity\b",
    r"\bwind\b",

    # Weather keywords - Turkish
    r"\bhava\b",
    r"\bhava durumu\b",
    r"\bsıcaklık\b",
    r"\bsicaklik\b",
    r"\bderece\b",
    r"\byağmur\b",
    r"\byagmur\b",
    r"\brüzgar\b",
    r"\bruzgar\b",
    r"\bnem\b",

    # Currency/FX keywords - English
    r"\bcurrency\b",
    r"\bexchange\b",
    r"\bconvert\b",
    r"\b(usd|eur|gbp|jpy|cad|aud|chf|try|tl)\b",
    r"\bdollar\b",
    r"\beuro\b",
    r"\bpound\b",
    r"\byen\b",
    r"\blira\b",

    # Currency/FX keywords - Turkish
    r"\bdöviz\b",
    r"\bdoviz\b",
    r"\bkur\b",
    r"\bçevir\b",
    r"\bcevir\b",

    # Location keywords (often used with weather)
    r"\bin\s+[A-Z][a-z]+",  # "in London", "in Paris"
    r"(?:istanbul|ankara|izmir|antalya|bursa|adana)'?[dD][aAeE]\b",
    r"(?:london|paris|berlin|new york|tokyo|rome)'?[dD][aAeE]\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Return True if *text* matches any of the regex patterns."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def classify_intent(message: str) -> IntentType:
    """Classify user intent from the raw message text.

    Evaluation order (first match wins):
      1. Approve-proposal signals
      2. Cancel-proposal signals
      3. Tool-mode signals (weather / FX)
      4. Default → OPS_MODE (create / update / delete tasks & notes)

    Args:
        message: User message text

    Returns:
        IntentType indicating routing decision
    """
    message_lower = message.lower().strip()

    # Short affirmative-only messages are almost certainly proposal actions
    if _matches_any(message_lower, APPROVE_KEYWORDS):
        return IntentType.APPROVE_PROPOSAL

    if _matches_any(message_lower, CANCEL_KEYWORDS):
        return IntentType.CANCEL_PROPOSAL

    # Check for tool mode keywords
    if _matches_any(message_lower, TOOL_MODE_KEYWORDS):
        return IntentType.TOOL_MODE

    # Default to ops mode for task/note management
    return IntentType.OPS_MODE
