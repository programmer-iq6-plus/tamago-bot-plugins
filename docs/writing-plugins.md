# Writing a plugin

A plugin teaches the assistant a new tool without a firmware update. It is a
`manifest.json` and one Lua 5.4 file. The board runs each plugin in its own
locked-down Lua state; the LLM calls the plugin's tools the same way it calls
the built-in ones.

Example: [`plugins/cuaca/`](../plugins/cuaca/) (weather from Open-Meteo).

## Permissions at a glance

Each one is described in its own section below.

| Permission | API | Lua functions | What it gives | Risk |
|---|---|---|---|---|
| `internet` | 1 | `http_get` | fetch data from the web (4 calls per tool call) | medium: data can leave the Assistant |
| `gpio` | 2 | `gpio_write`, `gpio_read` | switch and read pins of the plugin's hardware roles | medium: drives real devices |
| `i2c` | 2 | `i2c_transfer` | talk to I2C modules at the addresses in the manifest | medium |
| `uart` | 2 | `uart_write`, `uart_read` | talk to serial modules (GPS, ...) | medium |
| `presence` | 3 | `presence` | radar: somebody near, distance | low |
| `face_state` | 3 | `face` | a face seen, looking, position, distance (never a picture) | low |
| `sensors` | 3 | `sensors` | chip temperature | low |
| `expression` | 3 | `expression` | a short face after the answer (happy, love, surprised, confused) | low |
| `schedule` | 3 | `every`, `after`, `cancel` | run functions later or regularly, without being asked; may drive hardware without asking | medium |
| `speak` | 3 | `say` | speak unasked, only while somebody is near and the Assistant is idle; needs `schedule` | medium |
| `notes_read` | 3 | `notes_list`, `notes_read` | the meeting notes on the SD card | medium; high together with `internet` (the app warns) |
| `files` | 3 | `file_write`, `file_read`, `file_list`, `file_delete` | a folder of its own on the SD card (64 files, 4 MB) | low |
| `display` | 3 | `screen_open`, `screen_close`, `screen_size`, `clear`, `rect`, `text`, `show`; `on_tick`, `on_button` | the screen below a bar the firmware keeps; buttons from the app | low: the person can always close it |

Every plugin also has, without a permission: `log`, `time`, `date`,
`json_encode`, `json_decode`, `store_get`, `store_set` (4 KB), `sleep_ms` (with
a hardware permission).

Not available to plugins for now (open items, looked at again when there is
a real need): raw microphone audio, camera pictures, the Assistant's settings
and keys, SSH, BLE, OTA and other system functions, pins outside the plugin
pool. An unknown permission makes the board refuse the plugin.

## manifest.json

```json
{
  "id": "cuaca",
  "name": {"id": "Cuaca", "en": "Weather", "zh": "天气", "ja": "天気"},
  "version": "1.0.0",
  "api": 1,
  "author": "your-github-name",
  "description": {"id": "...", "en": "...", "zh": "...", "ja": "..."},
  "permissions": ["internet"],
  "entry": "main.lua",
  "tools": [
    {
      "name": "cuaca_kota",
      "function": "cuaca_kota",
      "description": "What the tool does and when the assistant should use it.",
      "inputSchema": {"type": "object", "properties": {"kota": {"type": "string"}}},
      "acts": false
    }
  ]
}
```

| Field | Rules |
|---|---|
| `id` | lowercase letters, digits, `_`; at most 24 characters. Also the folder name on the board. |
| `name`, `description` | a string, or one per language (`id`, `en`, `zh`, `ja`) for the app's store. |
| `version` | semver, e.g. `1.2.0`. |
| `api` | plugin API version the plugin was written for. The board refuses a plugin that needs a newer API than it has. |
| `permissions` | what the plugin may do beyond plain Lua: `internet` (API 1); `gpio`, `i2c`, `uart` (API 2, see [Hardware](#hardware-api-version-2)); `presence`, `face_state`, `sensors`, `expression` (API 3, see [What the Assistant senses](#what-the-assistant-senses-api-version-3)); `schedule`, `speak` (API 3, see [Running later, speaking first](#running-later-speaking-first-api-version-3)); `notes_read`, `files` (API 3, see [The SD card](#the-sd-card-api-version-3)); `display` (API 3, see [The screen](#the-screen-api-version-3)). An unknown permission makes the board refuse the plugin. |
| `entry` | the Lua file, default `main.lua`, at most 48 KB. |
| `tools` | 1 to 8 tools, in the MCP tool format: `name`, `description`, `inputSchema` (JSON Schema of the arguments). Names must start with `<id>_`. `function` is the global Lua function to call (default: the tool name). `acts: true` for tools that change something rather than only look something up. In a plugin with a hardware permission an `acts` tool also needs `question`. |
| `hardware` | API 2: the hardware roles, see below. |

The tool description is what the LLM reads to decide when to use the tool:
say what it does and when to use it, in Indonesian (the assistant's prompt
language) or English.

One tool per question. The LLM tends to say everything a tool returns, so a
tool that answers "is anyone near?" with the distance, the face and the chip
temperature gets all three read out. Return only what the tool is for.

## The Lua side (API version 1)

Each tool is a global function. It gets the arguments as a table and returns
a table (sent to the LLM as JSON), a string, or nothing. Return
`{error = "..."}` for a failure the assistant should tell the user about.

```lua
function cuaca_kota(args)
  local status, body = tamago.http_get("https://example.com/?q=" .. args.kota)
  if not status then return { error = body } end
  return { status = status, data = tamago.json_decode(body) }
end
```

Available: the Lua base library (without `load`, `loadfile`, `dofile`),
`string` (without `string.dump`), `table`, `math`, `utf8`, `coroutine`, and:

| Function | |
|---|---|
| `tamago.log(text)` | writes to the board's log |
| `tamago.time()` | seconds since 1970, 0 while the clock is not set yet |
| `tamago.date()` | local time: `{year, month, day, hour, min, sec, wday}` (`wday` 1 = Sunday) |
| `tamago.json_encode(value)` | text, or `nil, error` |
| `tamago.json_decode(text)` | value, or `nil, error` |
| `tamago.store_get(key)` | a value this plugin saved earlier, or `nil` |
| `tamago.store_set(key, value)` | saves it on the board (`nil` deletes); 4 KB per plugin, kept over updates |
| `tamago.http_get(url [, headers])` | `status, body`, or `nil, error`. Needs `internet`. Body up to 16 KB, 8 s timeout, at most 4 requests per tool call. |
| `tamago.api` | the API version number |

Not available, ever: files, the board's settings and passwords, SSH, other
plugins.

## Hardware (API version 2)

A plugin never names a pin. It lists **roles**; the person picks the pins for
them in the app after installing, from the pins the board keeps for plugins
(GPIO 2, 3, 5, 6, 22, 46, 47, 48). A pin belongs to one plugin. The plugin does
not run until all its roles have pins.

```json
"api": 2,
"permissions": ["gpio", "i2c"],
"hardware": [
  {"name": "relay",  "type": "gpio_out", "default": 0},
  {"name": "tombol", "type": "gpio_in", "pull": "up"},
  {"name": "sensor", "type": "i2c", "addresses": [118], "speed": 100000},
  {"name": "gps",    "type": "uart", "baud": 9600}
]
```

| Type | Permission | Pins | Options |
|---|---|---|---|
| `gpio_out` | `gpio` | 1 | `default`: 0 or 1, the level from the moment the plugin is loaded |
| `gpio_in` | `gpio` | 1 | `pull`: `up`, `down` or `none` |
| `i2c` | `i2c` | SDA, SCL | `addresses` (1-4, 7-bit, required): the only addresses it may talk to; `speed` 100000 or 400000. All plugins share one external I2C bus (internal pull-ups on); an address belongs to one plugin. |
| `uart` | `uart` | TX, RX | `baud` 1200-921600 (8N1). At most 2 UARTs on the board. |

At most 4 roles; names: lowercase letters, digits, `_`, at most 15.

**Asking first.** Every `acts` tool of a plugin with a hardware permission is
asked aloud before it runs, with its `question` (at most 159 bytes; `{arg}`
is replaced by that argument, `true`/`false` become "ya"/"tidak"). If the
person does not say yes, the tool does not run.

```json
{"name": "saklar_nyalakan", "acts": true, "question": "Boleh saya nyalakan saklarnya?", "description": "..."}
```

Lua functions (only in plugins with a hardware permission; `role` is the
role's name):

| Function | |
|---|---|
| `tamago.gpio_write(role, level)` | 0/1 or false/true. Only from an `acts` tool. |
| `tamago.gpio_read(role)` | 0 or 1; an output reads back its own level |
| `tamago.i2c_transfer(role, addr, write, nread [, timeout_ms])` | `write`: a string or a table of bytes (up to 64), `nread` 0-64; returns a table of bytes, or `nil, error` when the device does not answer. A tool without `acts` may only read: write at most 2 bytes (a register address) and read at least 1. |
| `tamago.uart_write(role, text)` | up to 1024 bytes. Only from an `acts` tool. |
| `tamago.uart_read(role [, max [, timeout_ms]])` | what came in, up to `max` (default 256, at most 1024) bytes; empty text if nothing came |
| `tamago.sleep_ms(ms)` | 0-1000, e.g. to wait for a sensor |

Waiting for hardware (`uart_read`, `sleep_ms`, I2C) is not counted in the 2 s
of Lua time, but is limited to 3 s per tool call. When the plugin is removed,
switched off or fails to load, its pins go back to plain inputs.

Example: [`plugins/saklar/`](../plugins/saklar/).

## What the Assistant senses (API version 3)

Four small permissions give a plugin a read-only view of the Assistant, or
let it pick a face. The functions exist only in plugins that have the
permission. They answer at once (no waiting), so they fit in any tool.

```json
"api": 3,
"permissions": ["presence", "face_state", "sensors", "expression"],
```

| Permission | Function | Returns |
|---|---|---|
| `presence` | `tamago.presence()` | `{radar, mood, near, distance_cm}`. `radar`: the presence radar is connected. `mood`: `"awake"` (somebody near), `"asleep"` or `"unknown"`. `near` and `distance_cm` only while the radar is connected; without it nobody knows, so they are left out. |
| `face_state` | `tamago.face()` | `{camera, seen, facing, x, y, distance_m}`. `camera`: face detection is running (the camera sleeps when nobody is near). `seen`: a face was seen in the last ~0.6 s; only then come `facing` (looking at the Assistant), `x`, `y` (-1 to 1 in the camera picture, rounded) and `distance_m` (rough). Never a picture. |
| `sensors` | `tamago.sensors()` | `{chip_temp_c}`: the chip's own temperature, 10-20 °C above the room while running. Missing if the sensor could not be read. |
| `expression` | `tamago.expression(name)` | `true`. `name`: `"happy"`, `"love"`, `"surprised"` or `"confused"`. The face shows once the Assistant has spoken its answer; the last call of a turn wins. A thank-you from the person still shows the love face. Listening, thinking and speaking faces belong to the Assistant and cannot be set. |

```lua
function tamago_example_check(args)
  local p = tamago.presence()
  local f = tamago.face()
  if f.seen and f.facing then tamago.expression("love") end
  return {near = p.near, looking = f.seen and f.facing or false}
end
```

## Running later, speaking first (API version 3)

`schedule` lets a plugin run its own functions later or again and again,
without anybody asking. `speak` lets such a function say something on its
own (a reminder, a greeting). `speak` needs `schedule`: inside a tool the
LLM already speaks what the tool returns.

| Function | |
|---|---|
| `tamago.every(seconds, "fn")` | runs the global function `fn` every `seconds` (60 s to 7 days); returns an id |
| `tamago.after(seconds, "fn")` | runs `fn` once, after `seconds` (5 s to 7 days); returns an id |
| `tamago.cancel(id)` | stops it; `true` if it was there |
| `tamago.say(text)` | only inside a scheduled function, once per run, at most 300 bytes. Returns `true` when queued. |

- At most 4 timers per plugin. Timers live in memory: after a restart or an
  update they are gone, so set the regular ones in the top-level code of
  `main.lua` (it runs every time the plugin loads).
- A scheduled function gets no arguments and its return value is only
  logged. Its limits are those of a tool call (2 s of Lua time, 4
  `http_get`). It may write to hardware **without asking** (unlike an
  `acts` tool, which is asked aloud first); the app warns about this when a
  plugin has `schedule` together with `gpio`, `i2c` or `uart`.
- **When the Assistant speaks it:** only while the presence radar sees
  somebody near at that moment and the Assistant is idle (not listening, answering, asking
  or taking meeting notes). Otherwise the text waits, and after 2 minutes it
  is dropped. Without a radar nothing is spoken. At most 4 texts wait at a
  time (of all plugins).
- What was said goes into the conversation, so a reply like "okay, done"
  makes sense to the LLM.
- For a time of day ("every morning at 7"), work out the seconds with
  `tamago.date()` and use `after`, then set the next one when it runs.

```lua
-- Remind to drink every 45 minutes
tamago.every(45 * 60, "minum_ingatkan")

function minum_ingatkan()
  tamago.say("Sudah waktunya minum air putih.")
end
```

## The SD card (API version 3)

Both need a microSD card in the Assistant; without one the functions return
`nil` and `"kartu SD tidak ada"`.

**`notes_read`**: the meeting notes the Assistant took ("tolong catat rapat
ini"). They are kept in `/sdcard/catatan/`: a finished note is a Markdown
file (title, summary, points, tasks, the full transcript); while a meeting
runs, or if it was cut off, there is a `..._mentah.txt` with the raw
transcript.

| Function | Returns |
|---|---|
| `tamago.notes_list()` | `{{name, size, unfinished}, ...}`, newest first, at most 30 |
| `tamago.notes_read(name [, offset])` | up to 8 KB of text, and the offset to read on from (`nil` at the end) |

Meeting notes are private. The app warns when a plugin asks for
`notes_read` together with `internet`.

**`files`**: a folder of the plugin's own on the card,
`/sdcard/plugins/<id>/`, for things too big for `store_set` (a log, a list,
a word game's words). At most 64 files and 4 MB; names are letters, digits,
`_ . -`, at most 48 characters, no folders. Kept over updates, deleted with
the plugin.

| Function | Returns |
|---|---|
| `tamago.file_write(name, data [, append])` | `true`; at most 64 KB per call |
| `tamago.file_read(name [, offset [, max]])` | the data (at most 16 KB per call), or `nil` + error |
| `tamago.file_list()` | `{{name, size}, ...}` |
| `tamago.file_delete(name)` | `true` if it was there |

## The screen (API version 3)

`display` lets a plugin take the Assistant's 240x320 screen for a while.
The firmware keeps a 16-pixel bar at the top with the plugin's name and a
dot while the Assistant listens (green), thinks (yellow) or speaks (blue);
the plugin draws the 240x304 area below it. The pairing code and the
camera preview still come first.

| Function | |
|---|---|
| `tamago.screen_open([seconds [, tick_ms]])` | takes the screen for `seconds` (5-600, default 120); calling it again extends the time. Returns `true`, or `nil` + error (another plugin has it). With `tick_ms` (100-2000) the global `on_tick(ms)` runs that often. |
| `tamago.screen_close()` | gives the screen back to the face |
| `tamago.screen_size()` | `240, 304` |
| `tamago.clear([color])` | fills the canvas |
| `tamago.rect(x, y, w, h, color)` | a filled rectangle |
| `tamago.text(x, y, text, [color [, scale]])` | 8x16 text (ASCII; other characters show as `?`), `scale` 1-6; `\n` starts a new line; returns the width |
| `tamago.show()` | puts the canvas on the screen (draw first, then show once) |

Colours are `0xRRGGBB` or `"#RRGGBB"`.

**Input.** Voice goes through the LLM to your tools as usual ("geser ke
kanan" -> a tool that draws and shows). The app has a remote while a plugin
has the screen: its arrows, OK and Back call the global `on_button(name)`
with `"up"`, `"down"`, `"left"`, `"right"`, `"ok"` or `"back"`.

**Limits.** `on_tick` gets 50 ms of Lua time, `on_button` 500 ms; three
failed `on_tick` in a row close the screen. Like a scheduled function they
may drive hardware. `store_set` from them is saved at the next tool call.
The person can always leave: by voice (the firmware adds a
`close_plugin_screen` tool while the screen is open), with "Close screen" in
the app, or when the time is up.

```lua
function papan_buka(args)
  local ok, err = tamago.screen_open(120)
  if not ok then return {error = err} end
  tamago.clear("#101820")
  tamago.text(10, 20, "Halo!", "#F5F0E1", 3)
  tamago.show()
  return {ok = true}
end
```

## Limits (the "locked room")

- 256 KB of Lua memory per plugin.
- 2 s of Lua time per tool call; time spent waiting for `http_get` is not
  counted. Code that runs longer is stopped with an error.
- An error stops only that call; the plugin stays loaded.

## Trying it on your own Assistant

```
python3 tools/tamago_plugin.py bundle path/to/your-plugin
```

checks the manifest with the board's rules (the folder name must be the
plugin's `id`) and writes `<id>-<version>.json` (manifest + Lua in one JSON
file) and its SHA-256. Serve that file over HTTP(S) and install it on the
Assistant from its URL and hash. A plugin installed this way is shown as
unverified.

To list it in the store, see [the README](../README.md#listing-a-plugin).
