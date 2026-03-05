# Simple Cue

Named, one-shot scheduled triggers for Home Assistant. Set a cue by name and datetime — when the time comes, an event fires and your automations take it from there. No helper entities, no template hacks.

## Installation (HACS)

1. Add this repo as a **custom repository** in HACS (type: Integration)
2. Search for "Simple Cue" and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Simple Cue**

---

## Services

### `simple_cue.set`

| Field      | Type          | Required | Description                              |
|------------|---------------|----------|------------------------------------------|
| `name`     | string        | Yes      | Unique slug (e.g. `coffee`)              |
| `datetime` | string        | Yes      | When the cue should fire                 |
| `action`   | dict or list  | No       | Service call(s) to execute automatically |

Setting a cue with an existing name replaces it.

#### The `datetime` field

The `datetime` field accepts **natural language** or an **ISO-8601 string**.

> [!IMPORTANT]
> The natural language parser matches **exact phrases only** — it is not fuzzy and does not tolerate typos or alternate wording. Copy expressions from the table below character-for-character. If the string is not recognised, the cue will silently not be set and an error will appear in the Home Assistant logs.

**Accepted expressions — copy exactly as shown:**

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
| `2025-06-01T08:00:00` | ISO-8601 exact datetime (always works) |

**Time formats accepted anywhere a time appears:**
`5am` · `5pm` · `5:30am` · `5:30pm` · `17:00` · `17:30` · `noon` · `midnight`

**Day formats accepted anywhere a day appears:**
`today` · `tomorrow` · `monday` · `tuesday` · `wednesday` · `thursday` · `friday` · `saturday` · `sunday` · `next monday` (etc.)

**What will fail silently:**

| You type | Why it fails |
|---|---|
| `tommorow at 5am` | Typo |
| `tomorrow @ 5am` | Wrong separator (`@` instead of `at`) |
| `in a couple hours` | Not a number |
| `this friday at 9pm` | `this` is not a recognised keyword — use `next` or the bare weekday |
| `5 in the morning` | Unrecognised phrasing |

If a cue fails to set, check **Settings → System → Logs** in Home Assistant for a message beginning with `Could not parse datetime`.

#### The `action` field

The optional `action` field carries what to do when the cue fires. It is included in the `simple_cue_triggered` event payload and executed automatically by the [Action Dispatcher automation](#action-dispatcher-automation) — no per-cue automation needed.

**Preferred (LLM / voice-scheduled cues):** pass a plain natural language sentence. The Action Dispatcher re-issues it as a fresh voice command via `conversation.process`, so the LLM executes it exactly as if the user had said it aloud.

```yaml
action: simple_cue.set
data:
  name: living_room_lights_off
  datetime: "2025-06-01T18:45:00"
  action: "Turn off the living room lights"
```

**Legacy (structured payloads):** pass a dict or list of HA service calls. These are executed directly without going through the LLM.

A single action:

```yaml
action: simple_cue.set
data:
  name: living_room_lights_off
  datetime: "today at 6:45pm"
  action:
    service: light.turn_off
    target:
      entity_id: light.living_room
```

An action with service data:

```yaml
action: simple_cue.set
data:
  name: living_room_dim
  datetime: "in 30 minutes"
  action:
    service: light.turn_on
    target:
      entity_id: light.living_room
    data:
      brightness_pct: 20
      color_temp_kelvin: 2700
```

A sequence of actions (list):

```yaml
action: simple_cue.set
data:
  name: bedtime_routine
  datetime: "today at 11pm"
  action:
    - service: light.turn_off
      target:
        entity_id: light.all_lights
    - service: lock.lock
      target:
        entity_id: lock.front_door
    - service: climate.set_temperature
      target:
        entity_id: climate.thermostat
      data:
        temperature: 68
```

A sequence including media playback:

```yaml
action: simple_cue.set
data:
  name: movie_time
  datetime: "in 10 minutes"
  action:
    - service: light.turn_off
      target:
        entity_id: light.living_room
    - service: media_player.play_media
      target:
        entity_id: media_player.tv
      data:
        media_content_type: app
        media_content_id: netflix
```

Each action item must contain a `service` key (string). `target` and `data` are optional. Simple Cue validates structure at set time but does not check whether entity IDs or service names exist — that happens when the action executes.

Cues without an `action` field work exactly as before — a `simple_cue_triggered` event fires and your dedicated automations handle it.

---

### `simple_cue.cancel`

| Field  | Type   | Description        |
|--------|--------|--------------------|
| `name` | string | Cue name to cancel |

No-op if the cue doesn't exist.

### `simple_cue.cancel_all`

Removes every active cue.

---

## Events

When a cue fires, `simple_cue_triggered` is emitted.

**Without an action payload** (`action` is always present; `null` when unset):

```yaml
event_type: simple_cue_triggered
event_data:
  name: coffee
  datetime: "2025-03-05T12:00:00+00:00"
  action: null
```

**With an action:**

```yaml
event_type: simple_cue_triggered
event_data:
  name: porch_lights_off
  datetime: "2025-03-05T00:00:00+00:00"
  action:
    service: light.turn_off
    target:
      entity_id: light.porch_lights
```

The `action` key is always present in the event payload. It contains the stored action when set, or `null` when no action was provided.

---

## Entities

### `sensor.simple_cue_{name}`

One entity per active cue. Removed automatically when the cue fires or is cancelled.

| Attribute   | Type            | Description                                    |
|-------------|-----------------|------------------------------------------------|
| `name`      | string          | Cue slug                                       |
| `remaining` | string          | Human-readable countdown (e.g. `"2h 14m"`)    |
| `action`    | dict / list / null | Stored action payload, or `null` if none    |

State is the fire datetime in local time (ISO-8601).

### `sensor.simple_cue_count`

Always present. Shows the total number of active cues.

| Attribute           | Type | Description                                       |
|---------------------|------|---------------------------------------------------|
| `cues`              | dict | name → fire datetime for all active cues          |
| `cues_with_actions` | int  | Count of active cues that carry an action payload |

---

## Action Dispatcher Automation

Install this automation once to automatically route any cue that carries an `action` payload. String actions (the primary LLM path) are re-issued as voice commands via `conversation.process`. Dict and list actions are executed as direct structured service calls (legacy fallback). Cues without an action are ignored and continue to work through their own dedicated automations as before.

> **Note:** Set `agent_id` to the entity ID of your Ollama conversation agent (find it at **Settings → Voice Assistants → [your agent] → Entity ID**). The value `conversation.ollama_conversation` is the most common default.

```yaml
alias: "Simple Cue — Action Dispatcher"
description: >
  Routes simple_cue_triggered action payloads. Strings are re-issued as
  voice commands via conversation.process. Dicts and lists are executed
  as direct structured service calls (legacy). Install once; never touch again.
triggers:
  - trigger: event
    event_type: simple_cue_triggered
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.action is not none }}"
actions:
  - choose:
      # String: re-issue as a voice command via the LLM
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.action is string }}"
        sequence:
          - action: conversation.process
            data:
              text: "{{ trigger.event.data.action }}"
              agent_id: conversation.ollama_conversation  # adjust to your agent entity ID
      # Dict: single structured service call (legacy)
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.action is mapping }}"
        sequence:
          - action: "{{ trigger.event.data.action.service }}"
            target: "{{ trigger.event.data.action.get('target', {}) }}"
            data: "{{ trigger.event.data.action.get('data', {}) }}"
      # List: sequence of structured service calls (legacy)
      - conditions:
          - condition: template
            value_template: >-
              {{ trigger.event.data.action is sequence
                 and trigger.event.data.action is not string }}
        sequence:
          - repeat:
              for_each: "{{ trigger.event.data.action }}"
              sequence:
                - action: "{{ repeat.item.service }}"
                  target: "{{ repeat.item.get('target', {}) }}"
                  data: "{{ repeat.item.get('data', {}) }}"
mode: queued
max: 20
```

---

## Voice (Assist)

- _"Set a coffee cue for 6:30 AM"_
- _"Cancel the coffee cue"_
- _"What cues are set?"_

---

## Voice Assistant / LLM Integration

With the `action` field, an LLM conversation agent (e.g. a local Ollama model with tool calling) can schedule arbitrary future home actions from natural language — without any pre-built automations.

**How it works:**

1. User says: _"Remember to turn off the porch lights at midnight."_
2. The LLM identifies this as a future action, computes the ISO-8601 datetime, and calls `simple_cue.set` with `action: "Turn off the porch lights"` — a plain sentence, no structured payload.
3. At midnight, `simple_cue_triggered` fires. The Action Dispatcher calls `conversation.process` with that sentence, and the LLM executes it as a fresh voice command.

### Required: Configure your conversation agent

> [!IMPORTANT]
> **Scheduling future actions will not work without this step.** By default, LLMs handle every request as an immediate command. You must add the instruction below to your conversation agent's system prompt so the model knows to use `simple_cue.set` for future-timed requests instead.

**Where to add it in Home Assistant:**

1. Go to **Settings → Voice Assistants**
2. Select your assistant (e.g. your Ollama agent)
3. Find the **Instructions** or **System prompt** field
4. Paste the text below at the end of whatever is already there

**Copy this exactly into your agent's instructions:**

```
**Scheduling future actions with Simple Cue**
When a user asks to do something at a future time, use `simple_cue.set` with these fields:

- `name`: a clean lowercase slug describing the action only, no times, no spaces.
  Examples: `living_room_lights_off`, `bedroom_fan_on`, `kitchen_switch_off`
- `datetime`: an ISO-8601 datetime string calculated from the current time.
  Always resolve relative times like "in 30 minutes" or "tonight at 9pm" into
  an exact ISO-8601 string — do not pass relative language.
- `action`: a plain natural language sentence describing what to do at that time,
  written exactly as if the user had said it as a new voice command.
  Examples: "Turn off the living room lights", "Turn on the bedroom fan",
  "Turn off all the lights"

Never put the time in the `name` field. Never omit the `action` field.
Never put structured data in the `action` field — it must be a plain sentence.

**Cancelling a scheduled action**
Use `simple_cue.cancel` with the `name` slug to cancel a scheduled action.
```

---

## Example: Coffee Machine

**Automation 1 — Schedule the cue (toggle-driven)**

```yaml
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
```

**Automation 2 — React when the cue fires**

```yaml
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

## License

MIT
