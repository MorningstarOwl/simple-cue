"""Constants for Simple Cue."""

DOMAIN = "simple_cue"
STORAGE_KEY = "simple_cue"
STORAGE_VERSION = 1
EVENT_CUE_TRIGGERED = "simple_cue_triggered"

SIGNAL_CUE_ADDED = f"{DOMAIN}_cue_added"
SIGNAL_CUE_REMOVED = f"{DOMAIN}_cue_removed"
SIGNAL_CUES_UPDATED = f"{DOMAIN}_cues_updated"

ATTR_NAME = "name"
ATTR_DATETIME = "datetime"
ATTR_REMAINING = "remaining"
ATTR_CUES = "cues"
ATTR_ACTION = "action"
ATTR_CUES_WITH_ACTIONS = "cues_with_actions"

# Services (also referenced by mcp_server.py)
SERVICE_SET = "set"
SERVICE_CANCEL = "cancel"
SERVICE_CANCEL_ALL = "cancel_all"

# MCP server
CONF_MCP_PORT = "mcp_port"
DEFAULT_MCP_PORT = 8766
