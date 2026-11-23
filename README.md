# Tamago-Bot plugins

The plugin catalog of the Tamago-Bot Assistant.
A plugin teaches the Assistant a new tool without a firmware update: a
`manifest.json` and one Lua file, run on the board in a locked-down sandbox.
The Assistant's Android app shows this catalog as its plugin store.

How to write one: [docs/writing-plugins.md](docs/writing-plugins.md).

## Permissions

A plugin gets nothing beyond plain Lua unless its manifest asks for it. The
app shows the permissions before installing and warns about risky
combinations; review checks that a plugin asks only for what it needs. The
board's plugin API is now version 3.

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

## How the catalog works

```
plugins/<id>/        source of plugins kept in this repository
registry/<id>.json   plugins kept in their author's own repository
keys/plugin_pub.pem  public key the Assistant checks signatures with
tools/               the checker, bundler and catalog builder
```

Every pull request is checked by CI with the same rules the board uses
(`python3 tools/tamago_plugin.py check`). After a maintainer reviews and
merges it, CI builds each plugin's install bundle, signs it, and publishes
`catalog.json` and the bundles on the
[`catalog`](https://github.com/programmer-iq6-plus/tamago-bot-plugins/tree/catalog) branch:

```
https://raw.githubusercontent.com/programmer-iq6-plus/tamago-bot-plugins/catalog/catalog.json
```

The Assistant downloads a bundle, checks its SHA-256 and the signature, and
only then installs it. Plugins in the catalog are shown as verified.

## Listing a plugin

Either way, open a pull request; one plugin per pull request.

**Source in this repository** — add `plugins/<id>/` with `manifest.json` and
the Lua file. To update, change the files and raise `version`.

**Source in your own repository** — publish the bundle
(`python3 tools/tamago_plugin.py bundle <folder>`) as an asset of a GitHub
release, then add `registry/<id>.json`:

```json
{
  "id": "myplugin",
  "repo": "your-name/tamago-myplugin",
  "url": "https://github.com/your-name/tamago-myplugin/releases/download/v1.0.0/myplugin-1.0.0.json",
  "sha256": "<the hash the bundle command printed>"
}
```

The catalog serves its own copy of that exact file, so changing or deleting
the release later does not change what users install. To update, publish a
new release and change `url` and `sha256` in a new pull request.

What review looks at: the plugin does what its description says, asks only
for the permissions it needs, and sends data only where its purpose needs it.

## Catalog format (`catalog.json`, format 1)

```json
{
 "format": 1,
 "generated": "2026-11-23T05:21:47Z",
 "signed": true,
 "plugins": [
  {
   "id": "cuaca", "version": "1.0.0", "api": 1,
   "name": {"id": "Cuaca", "en": "Weather", "zh": "天气", "ja": "天気"},
   "description": {"id": "...", "en": "...", "zh": "...", "ja": "..."},
   "author": "programmer-iq6-plus",
   "permissions": ["internet"],
   "hardware": [],
   "tools": [{"name": "cuaca_kota", "description": "...", "acts": false}],
   "source": "https://github.com/.../plugins/cuaca",
   "url": "https://raw.githubusercontent.com/.../catalog/bundles/cuaca-1.0.0.json",
   "size": 5181,
   "sha256": "...",
   "sig": "<base64>"
  }
 ]
}
```

`sig` is an ECDSA P-256 signature (DER, base64) over the SHA-256 of the text
`tamago-plugin/1 <id> <version> <sha256>`, made with the key whose public half
is `keys/plugin_pub.pem`.

`hardware` lists the plugin's hardware roles (`name`, `type`; API 2), so the
store can show what it needs before installing.

## License

[MIT](LICENSE), for the tools and for the plugins in `plugins/`. A plugin
listed through `registry/` keeps the license of its own repository.
