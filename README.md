# Simple Cue

Named, one-shot scheduled triggers for Home Assistant. Set a cue by name and datetime — when the time comes, an event fires and your automations take it from there. No helper entities, no template hacks.

**New in 1.5.0:** Simple Cue now ships a built-in **conversation agent**. Set it as your default voice assistant and it transparently intercepts scheduling commands ("turn off the lights at 9pm"), resolves them deterministically into structured HA service calls, and passes everything else straight through to your real LLM agent (Ollama, etc.). No more LLM failures at fire time.

---

## Installation (HACS)

1. Add this repo as a **custom repository** in HACS (type: Integration)
2. Search for **Simple Cue** and install
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Simple Cue**
5. Select the conversation agent you want Simple Cue to forward non-scheduled commands to (e.g. your Ollama agent)

---

## Setup Overview

Simple Cue has two modes. You can use either or both:

| Mode | How | Best for |
|---|---|---|
| **Conversation agent (recommended)** | Set Simple Cue as your default voice assistant | Hands-free voice scheduling with reliable execution |
| **Direct service calls** | Call `simple_cue.set` from automations or scripts | Programmatic scheduling, precise control |

---

## Conversation Agent Setup (Recommended)

The Simple Cue conversation agent wraps your real LLM agent. It intercepts voice commands that contain a future time, resolves them deterministically into structured HA service calls, and schedules them. Commands with no time phrase pass straight through to your underlying agent unchanged.

### Step 1 — Configure the integration

When you add Simple Cue via the UI, you'll be asked to choose an **underlying conversation agent**. This is the agent that handles all non-scheduled commands (general questions, immediate commands, etc.).

To change this later: **Settings → Devices & Services → Simple Cue → Configure**.

### Step 2 — Set Simple Cue as your default assistant

1. Go to **Settings → Voice Assistants**
2. Create a new assistant (or edit your existing one)
3. Set the **Conversation agent** to **Simple Cue**
4. Save

Your voice pipeline now looks like this:

```
Your voice
    │
    ▼
Simple Cue agent
    ├─ Detects time phrase → resolves command → schedules cue → confirms
    └─ No time phrase → forwards to your Ollama/HA agent unchanged
```

### What it handles

| Voice command | What happens |
|---|---|
| "Turn off the living room lights at 9pm" | Schedules `light.turn_off` on `light.living_room` for 9 PM |
| "Lock the front door in 30 minutes" | Schedules `lock.lock` on `lock.front_door` in 30 minutes |
| "Turn on the coffee machine tomorrow at 6am" | Schedules `switch.turn_on` on the matching switch |
| "Set the bedroom light to 50% at 10pm" | Schedules `light.turn_on` with `brightness: 127` |
| "Turn on the lamp" | Passes through to your LLM agent (no time phrase) |
| "What's the weather?" | Passes through to your LLM agent |

### How entity matching works

The agent strips the time phrase from your command, then:

1. Identifies the **verb** ("turn off", "lock", "open", etc.) and the domains it applies to
2. Scores every HA entity in those domains by how well its friendly name matches the remaining words
3. Requires ≥50% word overlap and rejects ties — ambiguous commands fall through to your LLM
4. Builds a concrete service call dict and schedules it via `simple_cue.set`

Because the action is stored as a structured dict (not natural language), execution at fire time is deterministic — no LLM is involved.

### Step 3 — Install the Action Dispatcher automation

Install this automation once. It listens for `simple_cue_triggered` events and executes the stored action payload automatically.

```yaml
alias: "Simple Cue — Action Dispatcher"
description: >
  Routes simple_cue_triggered action payloads. Dict/list actions (from the
  conversation agent or direct service calls) execute as structured HA service
  calls. String actions re-issue as voice commands (legacy path).
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
      # String: re-issue as a voice command (legacy / manually set cues)
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.action is string }}"
        sequence:
          - action: conversation.process
            data:
              text: "{{ trigger.event.data.action }}"
              agent_id: conversation.ollama_conversation  # adjust to your agent entity ID
mode: queued
max: 20
```

> **Note:** The `agent_id` in the string branch only matters for manually set cues where you stored a plain sentence. Voice-scheduled cues from the Simple Cue agent always store dict actions and never hit this branch.

---

## Direct Service Calls

You can also schedule cues directly without going through the conversation agent — useful for automations, scripts, or LLM tool calls.

### `simple_cue.set`

| Field      | Type          | Required | Description                              |
|------------|---------------|----------|------------------------------------------|
| `name`     | string        | Yes      | Unique slug (e.g. `coffee`)              |
| `datetime` | string        | Yes      | When the cue should fire                 |
| `action`   | str/dict/list | No       | What to execute when the cue fires       |

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

Three formats are accepted:

**Structured dict** (recommended — reliable execution):
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

**Plain string** (re-issued as a voice command at fire time via `conversation.process`):
```yaml
action: simple_cue.set
data:
  name: lights_off
  datetime: "tomorrow at 9pm"
  action: "Turn off the living room lights"
```

> **Note:** String actions depend on the LLM successfully interpreting the sentence at fire time, which can be unreliable. Prefer dict/list actions for anything that must execute reliably. The conversation agent always stores dict actions.

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

## LLM Tool Call Setup (Optional)

If you want your LLM agent to schedule cues autonomously via tool calls (without the Simple Cue conversation agent middleware), add this to its system prompt:

```
**Scheduling future actions with Simple Cue**
When a user asks to do something at a future time, use `simple_cue.set` with:

- `name`: a lowercase slug describing the action only (no times, no spaces).
  Examples: `living_room_lights_off`, `bedroom_fan_on`
- `datetime`: an ISO-8601 datetime string resolved from the current time.
  Always convert relative language ("in 30 minutes", "tonight at 9pm") into
  an exact ISO-8601 string — never pass relative language.
- `action`: a plain sentence describing the action, written as a new voice command.
  Examples: "Turn off the living room lights", "Turn on the bedroom fan"

Never put the time in `name`. Never omit `action`. Never use structured data in `action`.

**Cancelling:** use `simple_cue.cancel` with the name slug.
```

> [!NOTE]
> When using the Simple Cue conversation agent (recommended setup), you do not need to add these instructions to your LLM — the conversation agent handles scheduling before the LLM sees the request.

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

| Attribute   | Type                | Description                                 |
|-------------|---------------------|---------------------------------------------|
| `name`      | string              | Cue slug                                    |
| `remaining` | string              | Human-readable countdown (e.g. `"2h 14m"`) |
| `action`    | dict / list / null  | Stored action payload, or `null`            |

State is the fire datetime in local time (ISO-8601).

### `sensor.simple_cue_count`

Always present. Shows the total number of active cues.

| Attribute           | Type | Description                                      |
|---------------------|------|--------------------------------------------------|
| `cues`              | dict | name → fire datetime for all active cues         |
| `cues_with_actions` | int  | Count of active cues carrying an action payload  |

---

## Voice Commands (Assist / non-LLM)

When using Simple Cue as your conversation agent, voice commands with time phrases are handled automatically. The following explicit Assist intents also work independently of the LLM:

- _"Set a coffee cue for 6:30 AM"_
- _"Cancel the coffee cue"_
- _"What cues are set?"_

---

## Example: Coffee Machine (event-only pattern)

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

## Troubleshooting

**Cue fires but nothing happens**
- Check that the Action Dispatcher automation is installed and enabled
- Open **Developer Tools → Events**, listen for `simple_cue_triggered`, and check the `action` field in the payload
- If the action is a dict, verify the `service` and `entity_id` are correct

**Scheduled voice command does nothing at fire time**
- Ensure you're using the Simple Cue conversation agent — it stores dict actions (reliable path)
- If you set cues via direct LLM tool calls with string actions, see the LLM setup section above

**Command passes through to LLM instead of being scheduled**
- The entity matcher requires ≥50% of the noun words to appear in the entity's friendly name
- Check **Developer Tools → States** and look at the entity's `friendly_name` attribute
- Rename the entity in the UI if needed (e.g. rename to "Living Room Lights" to match "living room lights" perfectly)
- Ambiguous matches — two entities tied at the same score — always fall through to the LLM intentionally

**"Could not parse datetime" in logs**
- The natural language parser is strict — see the accepted expressions table above
- Use ISO-8601 for exact datetimes: `2025-06-01T21:00:00`

---

## License

MIT
