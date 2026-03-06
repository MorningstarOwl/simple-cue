"""Simple Cue conversation agent — scheduling middleware for Home Assistant.

This agent intercepts voice commands, detects future-timed scheduling intent,
and routes accordingly:

- Future-timed commands  → strip time, resolve command deterministically,
                           schedule via CueManager, return confirmation.
- Immediate commands     → pass through to the user's configured LLM agent.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    AgentInfo,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent as intent_helper
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .command_resolver import build_cue_name, build_service_call_dict, resolve_command
from .const import CONF_AGENT_ID, DOMAIN
from .time_parser import parse_fuzzy_datetime

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Time phrase detection & extraction
# ---------------------------------------------------------------------------

# Time token patterns (building blocks)
_TIME_TOKEN = (
    r"(?:"
    r"noon|midnight"
    r"|(?:\d{1,2}(?::\d{2})?\s*(?:am|pm))"
    r"|\d{1,2}:\d{2}"
    r")"
)

# Full time phrase patterns — order matters: longer/more-specific first
_TIME_PATTERNS: list[re.Pattern[str]] = [
    # "next <weekday> at <time>"
    re.compile(
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+at\s+" + _TIME_TOKEN,
        re.IGNORECASE,
    ),
    # "tomorrow at <time>"
    re.compile(r"\btomorrow\s+at\s+" + _TIME_TOKEN, re.IGNORECASE),
    # "today at <time>"
    re.compile(r"\btoday\s+at\s+" + _TIME_TOKEN, re.IGNORECASE),
    # "<weekday> at <time>"
    re.compile(
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+at\s+" + _TIME_TOKEN,
        re.IGNORECASE,
    ),
    # "in <n> minutes/hours/days"
    re.compile(r"\bin\s+\d+\s+(?:minutes?|hours?|days?)\b", re.IGNORECASE),
    # "at <time>"
    re.compile(r"\bat\s+" + _TIME_TOKEN, re.IGNORECASE),
    # standalone "noon" / "midnight" / bare time token (lower priority)
    re.compile(r"\b(?:noon|midnight)\b", re.IGNORECASE),
    re.compile(r"\b" + _TIME_TOKEN + r"\b", re.IGNORECASE),
]


def _extract_time_phrase(text: str) -> tuple[str, str] | None:
    """Find the time phrase in *text* and return (time_phrase, command).

    Returns None if no recognisable time phrase is found or the phrase does
    not parse to a valid datetime.  The returned command is the text with the
    time phrase (and any surrounding connector words like "at") removed.
    """
    for pattern in _TIME_PATTERNS:
        m = pattern.search(text)
        if m is None:
            continue

        phrase = m.group(0).strip()

        # Validate with the real parser
        if parse_fuzzy_datetime(phrase) is None:
            # Try stripping a leading "at " connector for bare-time patterns
            bare = re.sub(r"^at\s+", "", phrase, flags=re.IGNORECASE).strip()
            if parse_fuzzy_datetime(bare) is None:
                continue
            phrase = bare

        # Build the command: remove the matched span + optional leading/trailing
        # connector words ("at", "in", "for")
        start, end = m.start(), m.end()
        before = text[:start].rstrip()
        after = text[end:].lstrip()

        # Strip trailing connector at boundary (e.g. "turn off lights [at]")
        before = re.sub(r"\s+(?:at|in|for)$", "", before, flags=re.IGNORECASE)
        # Strip leading connector at boundary (e.g. "[at] 9pm turn off lights" leftover)
        after = re.sub(r"^(?:at|in|for)\s+", "", after, flags=re.IGNORECASE)

        command = (before + " " + after).strip()
        command = re.sub(r"\s{2,}", " ", command)

        if not command:
            continue

        return phrase, command

    return None


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Simple Cue conversation agent."""
    agent = SimpleCueConversationAgent(hass, entry)
    async_add_entities([agent])


# ---------------------------------------------------------------------------
# Conversation agent
# ---------------------------------------------------------------------------


class SimpleCueConversationAgent(conversation.ConversationEntity):
    """Conversation agent that adds scheduling intelligence to any LLM agent."""

    _attr_has_entity_name = True
    _attr_name = None  # uses device name

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the agent."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = None  # standalone entity

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages (delegate to underlying agent)."""
        return ["*"]

    @property
    def agent_info(self) -> AgentInfo:
        """Return info about this agent."""
        return AgentInfo(
            id=self.entity_id,
            name="Simple Cue",
        )

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Process a voice command.

        If the command contains a future-time phrase, resolve it and schedule.
        Otherwise, delegate to the underlying conversation agent.
        """
        text = user_input.text.strip()
        _LOGGER.debug("SimpleCue processing: %r", text)

        # -- Try to extract a time phrase -----------------------------------
        extraction = _extract_time_phrase(text)
        if extraction is not None:
            time_phrase, command = extraction
            _LOGGER.debug("Time phrase %r → command %r", time_phrase, command)

            fire_at = parse_fuzzy_datetime(time_phrase)
            if fire_at is not None:
                result = await self._schedule_command(
                    user_input, text, command, time_phrase, fire_at
                )
                if result is not None:
                    return result
                # Resolution failed — fall through to underlying agent

        return await self._passthrough(user_input)

    # -- Private helpers ----------------------------------------------------

    async def _schedule_command(
        self,
        user_input: ConversationInput,
        original_text: str,
        command: str,
        time_phrase: str,
        fire_at: datetime,
    ) -> ConversationResult | None:
        """Try to resolve *command* and schedule a cue.

        Returns a ConversationResult on success, None if resolution fails.
        """
        resolved = resolve_command(self.hass, command)
        if resolved is None:
            _LOGGER.debug(
                "Command resolver could not resolve %r — falling through", command
            )
            return None

        cue_name = build_cue_name(resolved)
        action_dict = build_service_call_dict(resolved)

        manager = self.hass.data[DOMAIN]["manager"]
        await manager.async_set_cue(cue_name, fire_at, action_dict)

        # Format a friendly confirmation
        local_dt = dt_util.as_local(dt_util.as_utc(fire_at))
        time_str = _format_time(local_dt)
        speech = _build_confirmation(resolved.friendly_name, resolved.service, time_str)

        intent_response = intent_helper.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(speech)
        return ConversationResult(response=intent_response)

    async def _passthrough(self, user_input: ConversationInput) -> ConversationResult:
        """Forward the request to the configured underlying agent."""
        agent_id: str | None = self.entry.data.get(CONF_AGENT_ID)

        if not agent_id:
            # No underlying agent configured — return a helpful error
            intent_response = intent_helper.IntentResponse(language=user_input.language)
            intent_response.async_set_speech(
                "Simple Cue has no underlying conversation agent configured. "
                "Please go to Settings → Devices & Services → Simple Cue → Configure "
                "and select your assistant."
            )
            return ConversationResult(response=intent_response)

        try:
            return await conversation.async_converse(
                hass=self.hass,
                text=user_input.text,
                conversation_id=user_input.conversation_id,
                context=user_input.context,
                language=user_input.language,
                agent_id=agent_id,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error forwarding to underlying agent %r", agent_id)
            intent_response = intent_helper.IntentResponse(language=user_input.language)
            intent_response.async_set_speech(
                "I had trouble reaching the underlying assistant. Please try again."
            )
            return ConversationResult(response=intent_response)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _format_time(dt: datetime) -> str:
    """Format a datetime as a human-friendly string."""
    now = dt_util.now()

    if dt.date() == now.date():
        return dt.strftime("today at %-I:%M %p").replace(":00 ", " ")
    elif dt.date() == (now + timedelta(days=1)).date():
        return dt.strftime("tomorrow at %-I:%M %p").replace(":00 ", " ")
    else:
        return dt.strftime("%A at %-I:%M %p").replace(":00 ", " ")


def _build_confirmation(friendly_name: str, service: str, time_str: str) -> str:
    """Build a natural language confirmation message."""
    action_suffix = service.split(".", 1)[-1]

    verb_phrases: dict[str, str] = {
        "turn_on": "turn on",
        "turn_off": "turn off",
        "lock": "lock",
        "unlock": "unlock",
        "open_cover": "open",
        "close_cover": "close",
        "media_pause": "pause",
        "media_play": "play",
        "alarm_arm_away": "arm",
        "alarm_disarm": "disarm",
        "trigger": "trigger",
    }
    verb = verb_phrases.get(action_suffix, action_suffix.replace("_", " "))

    intros = ["Done.", "Got it.", "Scheduled.", "Sure."]
    # Deterministic intro based on hash of name so it varies across entities
    intro = intros[hash(friendly_name) % len(intros)]

    return f"{intro} I'll {verb} {friendly_name} {time_str}."
