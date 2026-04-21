"""MCP SSE server for Simple Cue.

Runs as a daemon thread inside HA.  Three tools are exposed:

  set_timer(name, when)   — schedule a named cue
  cancel_timer(name)      — cancel a named cue
  list_timers()           — spoken summary of all active cues

Tools call back into HA's event loop via asyncio.run_coroutine_threadsafe
so they stay off the HA thread while still driving real HA services.

SSE endpoint:  http://<ha-host>:<port>/sse
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DATETIME,
    ATTR_NAME,
    DOMAIN,
    SERVICE_CANCEL,
    SERVICE_SET,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .__init__ import CueManager  # noqa: F401

_LOGGER = logging.getLogger(__name__)


def _format_remaining_spoken(total_seconds: int) -> str:
    """Return a natural spoken countdown string."""
    if total_seconds <= 0:
        return "expired"

    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def build_mcp_server(
    hass: HomeAssistant,
    manager: CueManager,
    port: int,
) -> tuple[FastMCP, threading.Thread]:
    """Build the MCP server instance and a ready-to-start daemon thread.

    Returns (mcp, thread).  Caller starts the thread.
    """
    ha_loop: asyncio.AbstractEventLoop = hass.loop

    mcp = FastMCP("Simple Cue", host="0.0.0.0", port=port)

    # ------------------------------------------------------------------
    # Tool: set_timer
    # ------------------------------------------------------------------

    @mcp.tool()
    def set_timer(name: str, when: str) -> str:
        """Schedule a named timer.

        'when' accepts natural language such as 'in 20 minutes',
        'tomorrow at 7am', or 'next friday at 9pm', as well as
        ISO-8601 strings like '2025-06-01T08:00:00'.

        If a timer with the same name already exists it is replaced.
        """
        future = asyncio.run_coroutine_threadsafe(
            hass.services.async_call(
                DOMAIN,
                SERVICE_SET,
                {ATTR_NAME: name, ATTR_DATETIME: when},
                blocking=True,
            ),
            ha_loop,
        )
        try:
            future.result(timeout=10)
            return f"Timer '{name}' set for {when}."
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("set_timer failed for '%s': %s", name, err)
            return f"Sorry, I could not set the timer '{name}'. {err}"

    # ------------------------------------------------------------------
    # Tool: cancel_timer
    # ------------------------------------------------------------------

    @mcp.tool()
    def cancel_timer(name: str) -> str:
        """Cancel a named timer. Does nothing if it does not exist."""
        future = asyncio.run_coroutine_threadsafe(
            hass.services.async_call(
                DOMAIN,
                SERVICE_CANCEL,
                {ATTR_NAME: name},
                blocking=True,
            ),
            ha_loop,
        )
        try:
            future.result(timeout=10)
            return f"Timer '{name}' cancelled."
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("cancel_timer failed for '%s': %s", name, err)
            return f"Sorry, I could not cancel the timer '{name}'. {err}"

    # ------------------------------------------------------------------
    # Tool: list_timers
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_timers() -> str:
        """Return a spoken summary of all active timers and their remaining time."""
        cues = manager.cues  # dict snapshot — safe to read from thread
        if not cues:
            return "There are no active timers."

        now = dt_util.utcnow()
        parts: list[str] = []
        for cue_name, entry in cues.items():
            local_dt = dt_util.as_local(entry.fire_at)
            delta = entry.fire_at - now
            remaining = _format_remaining_spoken(int(delta.total_seconds()))
            time_str = local_dt.strftime("%I:%M %p").lstrip("0")
            parts.append(f"'{cue_name}' fires in {remaining}, at {time_str}")

        if len(parts) == 1:
            return f"One active timer: {parts[0]}."
        return (
            f"{len(parts)} active timers: "
            + "; ".join(parts[:-1])
            + "; and "
            + parts[-1]
            + "."
        )

    # ------------------------------------------------------------------
    # Thread runner
    # ------------------------------------------------------------------

    def _run() -> None:
        _LOGGER.info("Simple Cue MCP server starting on port %d", port)
        try:
            mcp.run(transport="sse")
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Simple Cue MCP server stopped unexpectedly")

    thread = threading.Thread(target=_run, name="simple_cue_mcp", daemon=True)
    return mcp, thread
