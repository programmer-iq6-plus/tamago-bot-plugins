# Tamago-Bot plugins

The plugin catalog of the Tamago-Bot Assistant.
A plugin teaches the Assistant a new tool without a firmware update: a
`manifest.json` and one Lua file, run on the board in a locked-down sandbox.
The Assistant's Android app shows this catalog as its plugin store.

How to write one: [docs/writing-plugins.md](docs/writing-plugins.md).

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
