# Simple Cue

Named, one-shot scheduled triggers for Home Assistant. Set a cue by name and datetime — when the time comes, Simple Cue executes the stored action and fires a `simple_cue_triggered` event. No helper entities, no template hacks.

---

## Installation (HACS)

1. Add this repo as a **custom repository** in HACS (type: Integration)
2. Search for **Simple Cue** and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Simple Cue**
5. Set the MCP server port (default: `8777`) and click **Submit**

---

## How It Works

Call `simple_cue.set` from any automation or script with a name, a datetime, and an optional list of actions. Simple Cue stores the cue, waits, then:

1. Fires a `simple_cue_triggered` event (for any external listeners)
2. Executes the stored action list directly via HA's script engine

---

## Services

### `simple_cue.set`

| Field      | Type       | Required | Description                        |
|------------|------------|----------|------------------------------------|
| `name`     | string     | Yes      | Unique slug (e.g. `coffee`)        |
| `datetime` | string     | Yes      | When the cue should fire           |
| `action`   | list       | No       | HA-native action(s) to execute     |

Setting a cue with an existing name replaces it.

#### The `datetime` field

Accepts **natural language** or an **ISO-8601 string**.

> [!IMPORTANT]
> The natural language parser matches **exact phrases only**. Copy expressions from the table below exactly. Unrecognised strings fail silently — check **Settings → System → Logs** for `Could not parse datetime` errors.

| Expression | Meaning |
|---|---|
| `tomorrow at 7am` | Tomorrow at 07:00 local time |
| `tomorrow at 6:30am` | Tomorrow at 06:30 local time |
| `today at 17:30` | Today at 17:30 local time |
| `in 2 hours` | 2 hours from now |
| `in 30 minutes` | 30 minutes from now |
| `in 3 days` | 3 days from now |
| `next friday at 9pm` | The coming Friday at 21:00 |
| `monday at noon` | Next Monday at 12:00 |
| `midnight` | Start of tomorrow (00:00) |
| `noon` | 12:00 today (or tomorrow if already past) |
| `2025-06-01T08:00:00` | ISO-8601 exact datetime |

**Time formats:** `5am` · `5pm` · `5:30am` · `17:00` · `noon` · `midnight`

**Day formats:** `today` · `tomorrow` · `monday` – `sunday` · `next monday` – `next sunday`

**Common mistakes:**

| You type | Why it fails |
|---|---|
| `tommorow at 5am` | Typo |
| `tomorrow @ 5am` | Use `at`, not `@` |
| `in a couple hours` | Needs a number |
| `this friday at 9pm` | Use `next friday` or bare `friday` |

#### The `action` field

Uses HA's native action format — the same syntax as automation actions. In the UI you get the full visual action builder.

**Single action:**
```yaml
action: simple_cue.set
data:
  name: living_room_lights_off
  datetime: "today at 6:45pm"
  action:
    - action: light.turn_off
      target:
        entity_id: light.living_room
```

**Multiple actions (sequence):**
```yaml
action: simple_cue.set
data:
  name: bedtime_routine
  datetime: "today at 11pm"
  action:
    - action: light.turn_off
      target:
        entity_id: light.all_lights
    - action: lock.lock
      target:
        entity_id: lock.front_door
    - action: climate.set_temperature
      target:
        entity_id: climate.thermostat
      data:
        temperature: 68
```

**No action** (event-only — your own automation handles it):
```yaml
action: simple_cue.set
data:
  name: coffee
  datetime: "tomorrow at 6:30am"
```

### `simple_cue.cancel`

| Field  | Type   | Description        |
|--------|--------|--------------------|
| `name` | string | Cue name to cancel |

### `simple_cue.cancel_all`

Removes every active cue.

---

## Events

When a cue fires, `simple_cue_triggered` is emitted before the action executes.

```yaml
event_type: simple_cue_triggered
event_data:
  name: living_room_lights_off
  datetime: "2025-06-01T21:00:00+00:00"
  action:
    - action: light.turn_off
      target:
        entity_id: light.living_room
```

The `action` key is always present. It is `null` when no action was provided.

---

## Entities

### `sensor.simple_cue_{name}`

One entity per active cue, visible under **Settings → Devices & Services → Simple Cue → Entities** while the timer is running. Removed automatically when the cue fires or is cancelled.

| Attribute   | Type        | Description                                 |
|-------------|-------------|---------------------------------------------|
| `name`      | string      | Cue slug                                    |
| `remaining` | string      | Human-readable countdown (e.g. `"2h 14m"`) |
| `action`    | list / null | Stored action payload, or `null`            |

State is the fire datetime in local time (ISO-8601).

### `sensor.simple_cue_count`

Always present. Shows the total number of active cues.

| Attribute           | Type | Description                                     |
|---------------------|------|-------------------------------------------------|
| `cues`              | dict | name → fire datetime for all active cues        |
| `cues_with_actions` | int  | Count of active cues carrying an action payload |

---

## MCP Voice Interface

Simple Cue includes a built-in MCP SSE server. Any Home Assistant AI assistant — including Ollama-backed voice pipelines — can set, cancel, and query timers by voice with no additional addons.

### Setup

**1. Add the MCP integration**

Go to **Settings → Devices & Services → Add Integration → Model Context Protocol** and set the SSE URL:

```
http://homeassistant.local:8777/sse
```

(Replace `8777` with your custom port if you changed it during Simple Cue setup.)

**2. Optional — announce when timers fire**

Add a TTS automation so your voice assistant speaks when a timer completes:

```yaml
alias: "Simple Cue — Announce Timer"
triggers:
  - trigger: event
    event_type: simple_cue_triggered
actions:
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.your_player
      message: "Timer done. {{ trigger.event.data.name }} is complete."
```

### Voice Tools

| Tool | Example phrase | What it does |
|---|---|---|
| `find_entity(search)` | *(called automatically by the LLM)* | Searches HA entities by friendly name or entity ID |
| `set_timer(name, when, action?)` | *"Turn on Grace's lamp in 2 minutes"* | Schedules a named cue, optionally with a HA action |
| `cancel_timer(name)` | *"Cancel the pasta timer"* | Cancels a named cue |
| `list_timers()` | *"What timers do I have?"* | Lists all active timers with remaining time |

The `when` field accepts the same natural language and ISO-8601 strings as `simple_cue.set`.

#### How device control works

When you ask the assistant to perform a HA action at a future time, the LLM automatically:

1. Calls `find_entity` to resolve the device name to an entity ID
2. Calls `set_timer` with the resolved entity ID and the appropriate HA action packed into the `action` field
3. When the timer fires, Simple Cue executes the stored action directly — no extra automations required

**Examples of what you can say:**
- *"Turn on Grace's lamp in 2 minutes"* → turns on the lamp
- *"Turn off the coffee machine in 30 minutes"* → turns off the switch
- *"Lock the front door at 10pm"* → calls lock.lock
- *"Turn off all the lights and lock the front door in 20 minutes"* → multi-step action
- *"Dim the living room lights to 30% at 9pm"* → calls light.turn_on with brightness data

> [!IMPORTANT]
> Always phrase requests so the device action is clear. The LLM must be able to resolve both the device and the intended action (on, off, lock, dim, etc.) to schedule correctly. If a timer fires but the device doesn't respond, check **Settings → System → Logs** for `simple_cue` errors and confirm the timer was set with a populated action — see [Troubleshooting](#troubleshooting).

---

## Example: Coffee Machine

```yaml
# Automation 1 — schedule the cue (with inline action)
alias: "Coffee — Schedule Cue"
triggers:
  - trigger: state
    entity_id: input_boolean.coffee_tomorrow
    to: "on"
actions:
  - action: simple_cue.set
    data:
      name: coffee
      datetime: "tomorrow at 6:30am"
      action:
        - action: switch.turn_on
          target:
            entity_id: switch.coffee_machine
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.coffee_tomorrow
```

Or use the event-only pattern and react separately:

```yaml
# Automation 1 — schedule the cue (no action)
alias: "Coffee — Schedule Cue"
triggers:
  - trigger: state
    entity_id: input_boolean.coffee_tomorrow
    to: "on"
actions:
  - action: simple_cue.set
    data:
      name: coffee
      datetime: "tomorrow at 6:30am"
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.coffee_tomorrow

# Automation 2 — react when the cue fires
alias: "Coffee — Brew"
triggers:
  - trigger: event
    event_type: simple_cue_triggered
    event_data:
      name: coffee
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.coffee_machine
```

---

## Troubleshooting

**Cue fires but action doesn't execute**
- Check **Settings → System → Logs** for errors from `simple_cue`
- Open **Developer Tools → Events**, listen for `simple_cue_triggered`, and verify the `action` field looks correct
- Confirm the `entity_id` and action name (e.g. `light.turn_off`) are valid

**"Could not parse datetime" in logs**
- The natural language parser is strict — see the accepted expressions table above
- Use ISO-8601 for exact datetimes: `2025-06-01T21:00:00`

**MCP client can't connect**
- Confirm Simple Cue is loaded and HA has been restarted since install (HA installs `mcp[cli]` on first restart)
- Check the port in the SSE URL matches the port set during Simple Cue setup
- Check **Settings → System → Logs** for `Simple Cue MCP server` entries

**Timer fires but the device action doesn't happen**
- Open **Developer Tools → Events**, listen for `simple_cue_triggered`, and confirm the `action` field in the event data is populated (not `null`)
- If `action` is `null`, the LLM set the timer without an action — ask it again and confirm it found the entity via `find_entity` first
- Check **Settings → System → Logs** for errors from `simple_cue` around the time the timer fired

---

## Migrating from v1.x

Action payloads stored with the old `service:` key format are automatically converted to the new `action:` key format on first load. No manual changes are needed.

---

## License

MIT
