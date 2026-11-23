# Writing a plugin

A plugin teaches the assistant a new tool without a firmware update. It is a
`manifest.json` and one Lua 5.4 file. The board runs each plugin in its own
locked-down Lua state; the LLM calls the plugin's tools the same way it calls
the built-in ones.

Example: [`plugins/cuaca/`](../plugins/cuaca/) (weather from Open-Meteo).

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
| `permissions` | what the plugin may do beyond plain Lua. Version 1 knows only `internet`. An unknown permission makes the board refuse the plugin. |
| `entry` | the Lua file, default `main.lua`, at most 48 KB. |
| `tools` | 1 to 8 tools, in the MCP tool format: `name`, `description`, `inputSchema` (JSON Schema of the arguments). Names must start with `<id>_`. `function` is the global Lua function to call (default: the tool name). `acts: true` for tools that change something rather than only look something up. |

The tool description is what the LLM reads to decide when to use the tool:
say what it does and when to use it, in Indonesian (the assistant's prompt
language) or English.

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
plugins. Pins and buses (GPIO, I2C, UART) come in a later API version, behind
a permission.

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
