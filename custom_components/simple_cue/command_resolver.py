"""Deterministic command-to-service-call resolver for Simple Cue.

Given a natural language command (with the time phrase already stripped),
this module attempts to match it to a concrete HA service call dict without
invoking any LLM.  If confidence is insufficient, it returns None and the
caller falls through to the underlying conversation agent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verb → service mapping
# ---------------------------------------------------------------------------

@dataclass
class VerbEntry:
    service_suffix: str
    domains: list[str]


VERB_MAP: dict[str, VerbEntry] = {
    "turn on": VerbEntry("turn_on", ["light", "switch", "fan", "media_player", "automation"]),
    "turn off": VerbEntry("turn_off", ["light", "switch", "fan", "media_player", "automation"]),
    "switch on": VerbEntry("turn_on", ["light", "switch", "fan"]),
    "switch off": VerbEntry("turn_off", ["light", "switch", "fan"]),
    "lock": VerbEntry("lock", ["lock"]),
    "unlock": VerbEntry("unlock", ["lock"]),
    "open": VerbEntry("open_cover", ["cover"]),
    "close": VerbEntry("close_cover", ["cover"]),
    "start": VerbEntry("turn_on", ["automation", "switch", "fan"]),
    "stop": VerbEntry("turn_off", ["automation", "switch", "fan", "media_player"]),
    "pause": VerbEntry("media_pause", ["media_player"]),
    "play": VerbEntry("media_play", ["media_player"]),
    "arm": VerbEntry("alarm_arm_away", ["alarm_control_panel"]),
    "disarm": VerbEntry("alarm_disarm", ["alarm_control_panel"]),
    "run": VerbEntry("trigger", ["automation", "script"]),
    "trigger": VerbEntry("trigger", ["automation", "script"]),
    "activate": VerbEntry("turn_on", ["scene", "automation", "script"]),
}

# Sort longest first so "turn off" is matched before "turn" or "off"
_SORTED_VERBS = sorted(VERB_MAP.keys(), key=len, reverse=True)

# Minimum word-overlap ratio to accept an entity match
_MIN_CONFIDENCE = 0.5

# ---------------------------------------------------------------------------
# Brightness / colour helpers
# ---------------------------------------------------------------------------

_BRIGHTNESS_RE = re.compile(
    r"\bset\b.+?\bto\s+(\d{1,3})\s*%", re.IGNORECASE
)

_COLOR_NAMES: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "pink": (255, 182, 193),
    "white": (255, 255, 255),
    "warm white": (255, 200, 100),
    "cool white": (200, 220, 255),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
}

_COLOR_RE = re.compile(
    r"\bset\b.+?\bto\s+(" + "|".join(re.escape(c) for c in sorted(_COLOR_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _extract_brightness(command: str) -> int | None:
    """Return brightness 0-255 if command sets a percentage, else None."""
    m = _BRIGHTNESS_RE.search(command)
    if m:
        pct = int(m.group(1))
        return max(0, min(255, round(pct * 255 / 100)))
    return None


def _extract_color(command: str) -> tuple[int, int, int] | None:
    """Return RGB tuple if command sets a named colour, else None."""
    m = _COLOR_RE.search(command)
    if m:
        return _COLOR_NAMES.get(m.group(1).lower())
    return None


# ---------------------------------------------------------------------------
# Verb parsing
# ---------------------------------------------------------------------------

def _parse_verb(command: str) -> tuple[str, VerbEntry] | None:
    """Return (verb_text, VerbEntry) for the first matching verb, or None."""
    lower = command.lower()
    for verb in _SORTED_VERBS:
        if re.search(r"\b" + re.escape(verb) + r"\b", lower):
            return verb, VERB_MAP[verb]
    # Special case: "set ... to X%" implies light.turn_on with brightness
    if re.search(r"\bset\b", lower) and _BRIGHTNESS_RE.search(lower):
        return "set", VerbEntry("turn_on", ["light"])
    # Special case: "set ... to <colour>" implies light.turn_on with color
    if re.search(r"\bset\b", lower) and _COLOR_RE.search(lower):
        return "set", VerbEntry("turn_on", ["light"])
    return None


# ---------------------------------------------------------------------------
# Noun / entity extraction
# ---------------------------------------------------------------------------

def _noun_words(command: str, verb_text: str) -> list[str]:
    """Return the meaningful words from the command after stripping the verb."""
    # Remove the verb phrase
    cleaned = re.sub(r"\b" + re.escape(verb_text) + r"\b", "", command, flags=re.IGNORECASE)
    # Remove set...to...% / set...to...colour noise
    cleaned = re.sub(r"\bset\b|\bto\b|\d{1,3}\s*%", "", cleaned, flags=re.IGNORECASE)
    for colour in _COLOR_NAMES:
        cleaned = re.sub(r"\b" + re.escape(colour) + r"\b", "", cleaned, flags=re.IGNORECASE)
    # Strip filler words
    stopwords = {"the", "a", "an", "my", "all", "please", "and", "or", "of"}
    words = [w for w in cleaned.lower().split() if w and w not in stopwords]
    return words


def _score_entity(noun_words: list[str], friendly_name: str, entity_id: str) -> float:
    """Return a similarity score in [0, 1] between noun words and an entity."""
    if not noun_words:
        return 0.0

    name_words = set(friendly_name.lower().split())
    id_words = set(re.split(r"[_.]", entity_id.lower()))
    all_words = name_words | id_words

    noun_set = set(noun_words)
    overlap = len(noun_set & all_words)
    score = overlap / len(noun_set)

    # Bonus: exact friendly name match (case-insensitive)
    if friendly_name.lower() == " ".join(noun_words):
        score = min(1.0, score + 0.5)

    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ResolvedAction:
    """A resolved service call ready to schedule."""
    service: str
    entity_id: str
    friendly_name: str
    data: dict[str, Any]


def resolve_command(hass: HomeAssistant, command: str) -> ResolvedAction | None:
    """Attempt to resolve a natural language command to a service call.

    Returns a ResolvedAction on success, or None if resolution fails or
    confidence is below the threshold.
    """
    verb_result = _parse_verb(command)
    if verb_result is None:
        _LOGGER.debug("resolve_command: no verb found in %r", command)
        return None

    verb_text, verb_entry = verb_result
    noun_words = _noun_words(command, verb_text)

    if not noun_words:
        _LOGGER.debug("resolve_command: no noun words after stripping verb")
        return None

    # Collect all states matching allowed domains
    candidates: list[tuple[float, str, str]] = []  # (score, entity_id, friendly_name)
    for state in hass.states.async_all():
        domain = state.entity_id.split(".")[0]
        if domain not in verb_entry.domains:
            continue
        friendly = state.attributes.get("friendly_name", state.entity_id)
        score = _score_entity(noun_words, friendly, state.entity_id)
        if score >= _MIN_CONFIDENCE:
            candidates.append((score, state.entity_id, friendly))

    if not candidates:
        _LOGGER.debug(
            "resolve_command: no entity matched %r (noun_words=%r, domains=%r)",
            command, noun_words, verb_entry.domains,
        )
        return None

    # Pick highest-scoring; if tie, prefer earlier alphabetically for determinism
    candidates.sort(key=lambda c: (-c[0], c[1]))
    best_score, entity_id, friendly_name = candidates[0]

    # Reject if there are multiple candidates with the same top score —
    # ambiguous; let the LLM handle it.
    tied = [c for c in candidates if c[0] == best_score]
    if len(tied) > 1:
        _LOGGER.debug(
            "resolve_command: ambiguous match for %r — %d entities tied at %.2f",
            command, len(tied), best_score,
        )
        return None

    domain = entity_id.split(".")[0]
    service = f"{domain}.{verb_entry.service_suffix}"

    # Build extra data (brightness, colour)
    extra_data: dict[str, Any] = {}
    brightness = _extract_brightness(command)
    if brightness is not None:
        extra_data["brightness"] = brightness
    color = _extract_color(command)
    if color is not None:
        extra_data["rgb_color"] = list(color)

    _LOGGER.debug(
        "resolve_command: resolved %r → %s on %s (score=%.2f)",
        command, service, entity_id, best_score,
    )
    return ResolvedAction(
        service=service,
        entity_id=entity_id,
        friendly_name=friendly_name,
        data=extra_data,
    )


def build_cue_name(resolved: ResolvedAction) -> str:
    """Generate a deterministic slug for the cue from the resolved action.

    Example: light.turn_off on light.living_room → "living_room_turn_off"
    """
    # Strip domain prefix from entity_id
    entity_slug = resolved.entity_id.split(".", 1)[-1]
    # Get just the service action (after the domain)
    action_slug = resolved.service.split(".", 1)[-1]
    return f"{entity_slug}_{action_slug}"


def build_service_call_dict(resolved: ResolvedAction) -> dict[str, Any]:
    """Convert a ResolvedAction into the dict format used by CueManager."""
    return {
        "service": resolved.service,
        "target": {"entity_id": resolved.entity_id},
        "data": resolved.data,
    }
