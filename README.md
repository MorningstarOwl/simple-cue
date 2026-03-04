# Simple Cue

Named, one-shot scheduled triggers for Home Assistant. Set a cue by name and datetime — when the time comes, an event fires and your automations take it from there. No helper entities, no template hacks.

## Installation (HACS)

1. Add this repo as a **custom repository** in HACS (type: Integration)
2. Search for "Simple Cue" and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Simple Cue**

## Services

### `simple_cue.set`

| Field    | Type   | Description                        |
|----------|--------|------------------------------------|
| name     | string | Unique slug (e.g. `coffee`)        |
| datetime | string | When the cue should fire           |

The `datetime` field accepts **natural language** or an **ISO-8601 string**:

| You type | Meaning |
|---|---|
| `tomorrow at 7am` | Tomorrow at 07:00 local time |
| `today at 17:30` | Today at 17:30 local time |
| `in 2 hours` | 2 hours from now |
| `in 30 minutes` | 30 minutes from now |
| `in 3 days` | 3 days from now |
| `next friday at 9pm` | The coming Friday at 21:00 |
| `monday at noon` | Next Monday at 12:00 |
| `midnight` | Start of tomorrow (00:00) |
| `noon` | 12:00 today (or tomorrow if already past) |
| `2025-06-01T08:00:00` | ISO-8601 exact datetime |

Setting a cue with an existing name replaces it.

### `simple_cue.cancel`

| Field | Type   | Description            |
|-------|--------|------------------------|
| name  | string | Cue name to cancel     |

No-op if the cue doesn't exist.

### `simple_cue.cancel_all`

Removes every active cue.

## Events

When a cue fires, `simple_cue_triggered` is emitted:

```yaml
event_type: simple_cue_triggered
event_data:
  name: coffee
  datetime: "2025-03-05T12:00:00+00:00"
```

## Entities

- **`sensor.simple_cue_{name}`** — per-cue sensor. State is the fire datetime. Attributes: `name`, `remaining` (e.g. `"2h 14m"`). Removed automatically when the cue fires or is cancelled.
- **`sensor.simple_cue_count`** — total active cues. Attribute `cues` is a dict of name → datetime.

## Voice (Assist)

- _"Set a coffee cue for 6:30 AM"_
- _"Cancel the coffee cue"_
- _"What cues are set?"_

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

## License

MIT
