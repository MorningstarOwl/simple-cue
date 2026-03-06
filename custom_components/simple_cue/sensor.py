"""Sensor platform for Simple Cue."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACTION,
    ATTR_CUES,
    ATTR_CUES_WITH_ACTIONS,
    ATTR_NAME,
    ATTR_REMAINING,
    DOMAIN,
    SIGNAL_CUE_ADDED,
    SIGNAL_CUE_REMOVED,
    SIGNAL_CUES_UPDATED,
)

_LOGGER = logging.getLogger(__name__)

REMAINING_UPDATE_INTERVAL = timedelta(minutes=1)


def _format_remaining(fire_at: datetime) -> str:
    """Return a human-readable countdown string."""
    now = dt_util.utcnow()
    delta = fire_at - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "expired"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Simple Cue sensors."""
    manager = hass.data[DOMAIN]["manager"]
    entities: dict[str, SimpleCueSensor] = {}

    # -- Count sensor (always present) --------------------------------------
    count_sensor = SimpleCueCountSensor(manager)

    # -- Periodic refresh for remaining countdowns --------------------------
    @callback
    def _refresh_remaining(_now: datetime | None = None) -> None:
        for entity in entities.values():
            entity.async_write_ha_state()
        count_sensor.async_write_ha_state()

    unsub_interval = async_track_time_interval(
        hass, _refresh_remaining, REMAINING_UPDATE_INTERVAL
    )

    # -- Dispatcher: cue added ----------------------------------------------
    @callback
    def _handle_cue_added(
        name: str, fire_at: datetime, action: dict | list | None
    ) -> None:
        # If replacing, remove old entity first
        if name in entities:
            old = entities.pop(name)
            hass.async_create_task(old.async_remove())

        sensor = SimpleCueSensor(name, fire_at, action)
        entities[name] = sensor
        async_add_entities([sensor])

    # -- Dispatcher: cue removed --------------------------------------------
    @callback
    def _handle_cue_removed(name: str) -> None:
        entity = entities.pop(name, None)
        if entity is not None:
            async def _full_removal() -> None:
                await entity.async_remove()
                er = entity_registry.async_get(hass)
                reg_id = er.async_get_entity_id(
                    "sensor", DOMAIN, f"simple_cue_{name}"
                )
                if reg_id:
                    er.async_remove(reg_id)
            hass.async_create_task(_full_removal())

    async_dispatcher_connect(hass, SIGNAL_CUE_ADDED, _handle_cue_added)
    async_dispatcher_connect(hass, SIGNAL_CUE_REMOVED, _handle_cue_removed)
    async_dispatcher_connect(hass, SIGNAL_CUES_UPDATED, _refresh_remaining)

    # -- Bootstrap existing cues from manager --------------------------------
    initial_sensors: list[SimpleCueSensor] = []
    for name, cue_entry in manager.cues.items():
        sensor = SimpleCueSensor(name, cue_entry.fire_at, cue_entry.action)
        entities[name] = sensor
        initial_sensors.append(sensor)

    async_add_entities([count_sensor, *initial_sensors])


class SimpleCueSensor(SensorEntity):
    """Sensor representing a single active cue."""

    _attr_should_poll = False
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, name: str, fire_at: datetime, action: dict | list | None = None
    ) -> None:
        """Initialise the cue sensor."""
        self._cue_name = name
        self._fire_at = fire_at
        self._action = action

        self._attr_unique_id = f"simple_cue_{name}"
        self._attr_name = f"Simple Cue {name}"

    @property
    def native_value(self) -> str:
        """ISO datetime the cue will fire."""
        local_dt = dt_util.as_local(self._fire_at)
        return local_dt.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        """Return friendly name, remaining countdown, and optional action."""
        attrs: dict = {
            ATTR_NAME: self._cue_name,
            ATTR_REMAINING: _format_remaining(self._fire_at),
            ATTR_ACTION: self._action,
        }
        return attrs


class SimpleCueCountSensor(SensorEntity):
    """Sensor showing the total number of active cues."""

    _attr_should_poll = False
    _attr_unique_id = "simple_cue_count"
    _attr_name = "Simple Cue Count"
    _attr_icon = "mdi:counter"

    def __init__(self, manager) -> None:
        """Initialise the count sensor."""
        self._manager = manager

    @property
    def native_value(self) -> int:
        """Return the number of active cues."""
        return self._manager.count

    @property
    def extra_state_attributes(self) -> dict:
        """Return a dict of all active cues and the count carrying actions."""
        return {
            ATTR_CUES: {
                name: dt_util.as_local(entry.fire_at).isoformat()
                for name, entry in self._manager.cues.items()
            },
            ATTR_CUES_WITH_ACTIONS: self._manager.cues_with_actions_count,
        }
