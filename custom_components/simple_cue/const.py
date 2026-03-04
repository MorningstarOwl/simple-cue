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
