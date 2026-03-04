"""Assist intent handlers for Simple Cue."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util

from .const import DOMAIN


class SetSimpleCueIntent(intent.IntentHandler):
    """Handle setting a cue via voice."""

    intent_type = "set_simple_cue"
    slot_schema = {
        "name": intent.non_empty_string,
        "datetime": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass: HomeAssistant = intent_obj.hass
        manager = hass.data[DOMAIN]["manager"]

        name = intent_obj.slots["name"]["value"]
        dt_raw = intent_obj.slots["datetime"]["value"]

        fire_at = dt_util.parse_datetime(dt_raw)
        if fire_at is None:
            response = intent_obj.create_response()
            response.async_set_speech(
                f"Sorry, I couldn't understand the time '{dt_raw}'."
            )
            return response

        await manager.async_set_cue(name, fire_at)

        local_dt = dt_util.as_local(dt_util.as_utc(fire_at))
        response = intent_obj.create_response()
        response.async_set_speech(
            f"Done. The {name} cue is set for {local_dt.strftime('%I:%M %p on %A')}."
        )
        return response


class CancelSimpleCueIntent(intent.IntentHandler):
    """Handle cancelling a cue via voice."""

    intent_type = "cancel_simple_cue"
    slot_schema = {
        "name": intent.non_empty_string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass: HomeAssistant = intent_obj.hass
        manager = hass.data[DOMAIN]["manager"]

        name = intent_obj.slots["name"]["value"]
        had_cue = name in manager.cues
        await manager.async_cancel_cue(name)

        response = intent_obj.create_response()
        if had_cue:
            response.async_set_speech(f"The {name} cue has been cancelled.")
        else:
            response.async_set_speech(f"There's no {name} cue set right now.")
        return response


class ListSimpleCuesIntent(intent.IntentHandler):
    """Handle listing active cues via voice."""

    intent_type = "list_simple_cues"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the intent."""
        hass: HomeAssistant = intent_obj.hass
        manager = hass.data[DOMAIN]["manager"]

        response = intent_obj.create_response()

        if manager.count == 0:
            response.async_set_speech("There are no cues set right now.")
            return response

        lines: list[str] = []
        for name, entry in manager.cues.items():
            local_dt = dt_util.as_local(entry.fire_at)
            lines.append(f"{name} at {local_dt.strftime('%I:%M %p on %A')}")

        count_word = "is 1 cue" if manager.count == 1 else f"are {manager.count} cues"
        speech = f"There {count_word} set: {', '.join(lines)}."
        response.async_set_speech(speech)
        return response
