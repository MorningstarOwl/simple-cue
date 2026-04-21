"""Simple Cue — named one-shot scheduled triggers for Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.script import Script
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACTION,
    ATTR_DATETIME,
    ATTR_NAME,
    CONF_MCP_PORT,
    DEFAULT_MCP_PORT,
    DOMAIN,
    EVENT_CUE_TRIGGERED,
    SERVICE_CANCEL,
    SERVICE_CANCEL_ALL,
    SERVICE_SET,
    SIGNAL_CUE_ADDED,
    SIGNAL_CUE_REMOVED,
    SIGNAL_CUES_UPDATED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_SET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_DATETIME): str,
        vol.Optional(ATTR_ACTION): vol.Any(dict, list),
    }
)

SERVICE_CANCEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
    }
)


def _normalize_action(action: Any) -> list[dict] | None:
    """Normalize an action payload to a list of HA-native action dicts.

    - None → None
    - List of dicts with 'action' key → pass through as-is
    - Single dict with 'service' key → convert to single-item list with 'action' key
    - List of dicts with 'service' keys → convert each to 'action' key
    Raises ServiceValidationError on unrecognised input.
    """
    if action is None:
        return None

    items: list[Any] = action if isinstance(action, list) else [action]
    normalized: list[dict] = []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ServiceValidationError(
                f"action item {i} must be a mapping, got {type(item).__name__}"
            )

        if "action" in item:
            # Already HA-native format
            normalized.append(item)
        elif "service" in item:
            # Legacy format — convert 'service' key to 'action' key
            converted: dict[str, Any] = {"action": item["service"]}
            if "target" in item:
                converted["target"] = item["target"]
            if "data" in item:
                converted["data"] = item["data"]
            normalized.append(converted)
        else:
            raise ServiceValidationError(
                f"action item {i} must have an 'action' or 'service' key"
            )

    return normalized


@dataclass
class CueEntry:
    """Represents a single scheduled cue."""

    name: str
    fire_at: datetime
    action: list[dict] | None = None
    unsub: callback | None = None


class CueManager:
    """Manages all cue scheduling, storage, and lifecycle."""

    def __init__(self, hass: HomeAssistant, store: Store) -> None:
        """Initialise the cue manager."""
        self.hass = hass
        self._store = store
        self._cues: dict[str, CueEntry] = {}

    # -- Public API ----------------------------------------------------------

    @property
    def cues(self) -> dict[str, CueEntry]:
        """Return the active cues dict."""
        return dict(self._cues)

    @property
    def count(self) -> int:
        """Return the number of active cues."""
        return len(self._cues)

    @property
    def cues_with_actions_count(self) -> int:
        """Return the number of active cues that carry an action payload."""
        return sum(1 for e in self._cues.values() if e.action is not None)

    async def async_set_cue(
        self,
        name: str,
        fire_at: datetime,
        action: list[dict] | None = None,
    ) -> None:
        """Create or replace a cue."""
        # Ensure timezone-aware, stored in UTC
        if fire_at.tzinfo is None:
            fire_at = dt_util.as_utc(
                fire_at.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            )
        else:
            fire_at = dt_util.as_utc(fire_at)

        # Cancel existing cue with same name if present
        if name in self._cues:
            self._cancel_tracking(name)
            _LOGGER.debug("Replacing existing cue '%s'", name)

        unsub = async_track_point_in_time(
            self.hass, self._make_fire_callback(name), fire_at
        )
        self._cues[name] = CueEntry(name=name, fire_at=fire_at, action=action, unsub=unsub)

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_CUE_ADDED, name, fire_at, action)
        async_dispatcher_send(self.hass, SIGNAL_CUES_UPDATED)
        _LOGGER.info("Cue '%s' set for %s", name, fire_at.isoformat())

    async def async_cancel_cue(self, name: str) -> None:
        """Cancel a cue by name. No-op if it doesn't exist."""
        if name not in self._cues:
            _LOGGER.debug("Cancel requested for non-existent cue '%s'", name)
            return

        self._cancel_tracking(name)
        del self._cues[name]

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_CUE_REMOVED, name)
        async_dispatcher_send(self.hass, SIGNAL_CUES_UPDATED)
        _LOGGER.info("Cue '%s' cancelled", name)

    async def async_cancel_all(self) -> None:
        """Cancel every active cue."""
        names = list(self._cues.keys())
        for name in names:
            self._cancel_tracking(name)
            async_dispatcher_send(self.hass, SIGNAL_CUE_REMOVED, name)
        self._cues.clear()

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_CUES_UPDATED)
        _LOGGER.info("All cues cancelled (%d removed)", len(names))

    async def async_load(self) -> None:
        """Load persisted cues from storage and reschedule them."""
        data: dict[str, Any] | None = await self._store.async_load()
        if not data or "cues" not in data:
            return

        now = dt_util.utcnow()
        for name, cue_data in data["cues"].items():
            if isinstance(cue_data, str):
                iso_dt = cue_data
                raw_action: Any = None
            elif isinstance(cue_data, dict):
                iso_dt = cue_data.get("datetime", "")
                raw_action = cue_data.get("action")
                # Discard legacy string actions
                if isinstance(raw_action, str):
                    raw_action = None
            else:
                _LOGGER.warning("Skipping cue '%s' with unrecognised storage format", name)
                continue

            # Normalize / migrate legacy service:-keyed payloads
            try:
                action = _normalize_action(raw_action)
            except ServiceValidationError:
                _LOGGER.warning(
                    "Cue '%s' has invalid action payload, discarding action", name
                )
                action = None

            fire_at = dt_util.parse_datetime(iso_dt)
            if fire_at is None:
                _LOGGER.warning("Skipping cue '%s' with invalid datetime", name)
                continue
            fire_at = dt_util.as_utc(fire_at)

            if fire_at <= now:
                # Cue expired while HA was down — fire it immediately
                _LOGGER.info("Cue '%s' expired during downtime, firing now", name)
                event_data: dict[str, Any] = {
                    ATTR_NAME: name,
                    ATTR_DATETIME: fire_at.isoformat(),
                }
                event_data[ATTR_ACTION] = action
                self.hass.bus.async_fire(EVENT_CUE_TRIGGERED, event_data)

                continue

            unsub = async_track_point_in_time(
                self.hass, self._make_fire_callback(name), fire_at
            )
            self._cues[name] = CueEntry(name=name, fire_at=fire_at, action=action, unsub=unsub)
            _LOGGER.debug("Restored cue '%s' for %s", name, fire_at.isoformat())

        # Persist cleaned/migrated state
        await self._async_persist()

    async def async_shutdown(self) -> None:
        """Cancel all tracking on unload (does NOT persist removal)."""
        for entry in self._cues.values():
            if entry.unsub:
                entry.unsub()

    # -- Private helpers -----------------------------------------------------

    def _make_fire_callback(self, name: str):
        """Return a callback bound to a specific cue name."""

        async def _fire_cue(_now: datetime) -> None:
            entry = self._cues.pop(name, None)
            if entry is None:
                return

            _LOGGER.info("Cue '%s' fired", name)
            event_data: dict[str, Any] = {
                ATTR_NAME: name,
                ATTR_DATETIME: entry.fire_at.isoformat(),
            }
            event_data[ATTR_ACTION] = entry.action

            self.hass.bus.async_fire(EVENT_CUE_TRIGGERED, event_data)

            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_CUE_REMOVED, name)
            async_dispatcher_send(self.hass, SIGNAL_CUES_UPDATED)

            if entry.action:
                try:
                    script = Script(
                        self.hass,
                        entry.action,
                        f"Simple Cue {name}",
                        DOMAIN,
                    )
                    await script.async_run(context=Context())
                except Exception:
                    _LOGGER.exception("Error executing action for cue '%s'", name)

        return _fire_cue

    def _cancel_tracking(self, name: str) -> None:
        """Unsubscribe the point-in-time tracker for a cue."""
        entry = self._cues.get(name)
        if entry and entry.unsub:
            entry.unsub()
            entry.unsub = None

    async def _async_persist(self) -> None:
        """Write the current cues to disk."""
        await self._store.async_save(
            {
                "cues": {
                    name: {
                        "datetime": entry.fire_at.isoformat(),
                        "action": entry.action,
                    }
                    for name, entry in self._cues.items()
                }
            }
        )


# ---------------------------------------------------------------------------
# Integration setup
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Simple Cue from a config entry."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    manager = CueManager(hass, store)
    await manager.async_load()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["manager"] = manager

    # -- Register services ---------------------------------------------------

    async def handle_set(call: ServiceCall) -> None:
        name: str = call.data[ATTR_NAME]
        dt_raw = call.data[ATTR_DATETIME]
        raw_action: dict | list | None = call.data.get(ATTR_ACTION)

        # Normalize and validate action payload
        action = _normalize_action(raw_action)

        if isinstance(dt_raw, str):
            # Try ISO-8601 first, then fall back to natural language
            fire_at = dt_util.parse_datetime(dt_raw)
            if fire_at is None:
                from .time_parser import parse_fuzzy_datetime
                fire_at = parse_fuzzy_datetime(dt_raw)
            if fire_at is None:
                _LOGGER.error(
                    "Could not parse datetime '%s' for cue '%s'. "
                    "Use ISO-8601 (e.g. '2025-06-01T08:00:00') or natural "
                    "language (e.g. 'tomorrow at 7am', 'in 2 hours', "
                    "'next friday at 9pm').",
                    dt_raw,
                    name,
                )
                return
        elif isinstance(dt_raw, datetime):
            fire_at = dt_raw
        else:
            _LOGGER.error("Unexpected datetime type for cue '%s': %s", name, type(dt_raw))
            return

        await manager.async_set_cue(name, fire_at, action)

    async def handle_cancel(call: ServiceCall) -> None:
        await manager.async_cancel_cue(call.data[ATTR_NAME])

    async def handle_cancel_all(call: ServiceCall) -> None:
        await manager.async_cancel_all()

    hass.services.async_register(DOMAIN, SERVICE_SET, handle_set, SERVICE_SET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL, handle_cancel, SERVICE_CANCEL_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_ALL, handle_cancel_all)

    # -- Start MCP server ----------------------------------------------------

    port: int = entry.data.get(CONF_MCP_PORT, DEFAULT_MCP_PORT)
    from .mcp_server import build_mcp_server
    _mcp, _thread = build_mcp_server(hass, manager, port)
    _thread.start()
    hass.data[DOMAIN]["mcp_thread"] = _thread

    # -- Forward platforms ---------------------------------------------------

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Simple Cue."""
    manager: CueManager = hass.data[DOMAIN]["manager"]
    await manager.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.pop(DOMAIN, None)
        hass.services.async_remove(DOMAIN, SERVICE_SET)
        hass.services.async_remove(DOMAIN, SERVICE_CANCEL)
        hass.services.async_remove(DOMAIN, SERVICE_CANCEL_ALL)

    # MCP thread is a daemon — it will exit when HA exits.
    # On a config entry reload the old thread dies and a new one starts
    # after async_setup_entry runs again.  The OS will reclaim the port
    # within a few seconds (SO_REUSEADDR is set by uvicorn by default).

    return unload_ok
