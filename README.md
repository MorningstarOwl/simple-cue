# Simple Cue

Named, one-shot scheduled triggers for Home Assistant. Set a cue by name and datetime — when the time comes, an event fires and your automations take it from there. No helper entities, no template hacks.

---

## Installation (HACS)

1. Add this repo as a **custom repository** in HACS (type: Integration)
2. Search for **Simple Cue** and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Simple Cue**

---

## How It Works

Call `simple_cue.set` from any automation or script with a name and a datetime. Simple Cue stores the cue, waits, then fires a `simple_cue_triggered` event. Your automations listen for that event and act.

---

## Services

### `simple_cue.set`

| Field      | Type       | Required | Description                        |
|------------|------------|----------|------------------------------------|
| `name`     | string     | Yes      | Unique slug (e.g. `coffee`)        |
| `datetime` | string     | Yes      | When the cue should fire           |
| `action`   | dict/list  | No       | Structured service call(s) to run  |

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

**Structured dict** (single service call):
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

**Structured list** (sequence of service calls):
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

When a cue fires, `simple_cue_triggered` is emitted.

```yaml
event_type: simple_cue_triggered
event_data:
  name: living_room_lights_off
  datetime: "2025-06-01T21:00:00+00:00"
  action:
    service: light.turn_off
    target:
      entity_id: light.living_room
    data: {}
```

The `action` key is always present. It is `null` when no action was provided.

---

## Entities

### `sensor.simple_cue_{name}`

One entity per active cue, removed automatically when the cue fires or is cancelled.

| Attribute   | Type              | Description                                 |
|-------------|-------------------|---------------------------------------------|
| `name`      | string            | Cue slug                                    |
| `remaining` | string            | Human-readable countdown (e.g. `"2h 14m"`) |
| `action`    | dict / list / null | Stored action payload, or `null`           |

State is the fire datetime in local time (ISO-8601).

### `sensor.simple_cue_count`

Always present. Shows the total number of active cues.

| Attribute           | Type | Description                                     |
|---------------------|------|-------------------------------------------------|
| `cues`              | dict | name → fire datetime for all active cues        |
| `cues_with_actions` | int  | Count of active cues carrying an action payload |

---

## Example: Coffee Machine

```yaml
# Automation 1 — schedule the cue
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

```yaml
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

## Action Dispatcher Automation

Install this automation once if you use the `action` field in `simple_cue.set`. It listens for `simple_cue_triggered` events and executes the stored action payload automatically.

```yaml
alias: "Simple Cue — Action Dispatcher"
description: >
  Executes structured action payloads when a cue fires.
triggers:
  - trigger: event
    event_type: simple_cue_triggered
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.action is not none }}"
actions:
  - choose:
      # Dict: single structured service call
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.action is mapping }}"
        sequence:
          - action: "{{ trigger.event.data.action.service }}"
            target: "{{ trigger.event.data.action.get('target', {}) }}"
            data: "{{ trigger.event.data.action.get('data', {}) }}"
      # List: sequence of structured service calls
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

## Troubleshooting

**Cue fires but nothing happens**
- Check that the Action Dispatcher automation is installed and enabled
- Open **Developer Tools → Events**, listen for `simple_cue_triggered`, and check the `action` field in the payload
- If the action is a dict, verify the `service` and `entity_id` are correct

**"Could not parse datetime" in logs**
- The natural language parser is strict — see the accepted expressions table above
- Use ISO-8601 for exact datetimes: `2025-06-01T21:00:00`

---

## License

MIT
