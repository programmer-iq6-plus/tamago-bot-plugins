#!/usr/bin/env python3
"""Checks, bundles and signs Tamago-Bot plugins, and builds the catalog.

    python3 tools/tamago_plugin.py check                 every plugin and registry entry
    python3 tools/tamago_plugin.py bundle plugins/<id>   write <id>-<version>.json, print its sha256
    python3 tools/tamago_plugin.py catalog --out DIR [--key KEY.pem]

The checks are the same as the board's firmware,
so a plugin that passes here loads there, apart from errors in the Lua code
itself (those are caught with `luac -p` when luac is installed).

A plugin comes from one of two places:
  plugins/<id>/        source kept in this repository (official plugins)
  registry/<id>.json   a plugin kept in its author's repository:
                       {"id": "...", "repo": "owner/name",
                        "url": "https://github.com/owner/name/releases/download/...",
                        "sha256": "..."}
Either way the catalog serves a copy of the bundle from this repository, so a
listed plugin cannot change or disappear behind the catalog's back.

Signature: ECDSA P-256 over SHA-256 of the text
    tamago-plugin/1 <id> <version> <sha256 of the bundle, hex>
DER-encoded, base64 in the catalog. The board checks it with keys/plugin_pub.pem.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = 3
VIEW_PERMISSIONS = {"presence", "face_state", "sensors", "expression", "schedule", "speak", "notes_read", "files", "display"}  # API 3
HW_PERMISSIONS = {"gpio", "i2c", "uart"}           # API 2
PERMISSIONS = {"internet"} | HW_PERMISSIONS | VIEW_PERMISSIONS
HW_TYPES = {"gpio_out": "gpio", "gpio_in": "gpio", "i2c": "i2c", "uart": "uart"}
HW_ROLES_MAX = 4
QUESTION_MAX = 159
LANGS = ("id", "en", "zh", "ja")
TOOLS_MAX = 8
NAME_MAX = 63
SOURCE_MAX = 48 * 1024
BUNDLE_MAX = 64 * 1024
SIG_PREFIX = "tamago-plugin/1"
ID_RE = re.compile(r"[a-z0-9_]{1,24}")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?")
REPO_RE = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")


class Bad(Exception):
    pass


def text(v):
    """A plain string, or the Indonesian/English/first one of a per-language object"""
    if isinstance(v, str):
        return v
    if isinstance(v, dict) and v:
        return v.get("id") or v.get("en") or next(iter(v.values()))
    return None


def check_lang_text(m, field):
    v = m.get(field)
    if isinstance(v, str) and v.strip():
        return
    if isinstance(v, dict) and v and all(isinstance(s, str) and s.strip() for s in v.values()):
        unknown = set(v) - set(LANGS)
        if unknown:
            raise Bad(f"{field}: unknown language(s) {sorted(unknown)}, use {', '.join(LANGS)}")
        return
    raise Bad(f"{field}: a text, or one text per language ({', '.join(LANGS)})")


def check_manifest(m):
    """Raises Bad on a manifest the board would refuse; returns the entry file name"""
    if not isinstance(m, dict):
        raise Bad("manifest is not a JSON object")
    pid = m.get("id")
    if not isinstance(pid, str) or not ID_RE.fullmatch(pid):
        raise Bad("id: lowercase letters, digits and _, at most 24")
    if m.get("api") not in range(1, API_VERSION + 1):
        raise Bad(f"api must be 1..{API_VERSION}")
    if not isinstance(m.get("version"), str) or len(m["version"]) >= 24 or not VERSION_RE.fullmatch(m["version"]):
        raise Bad("version: semver such as 1.2.0")
    check_lang_text(m, "name")
    check_lang_text(m, "description")
    if not isinstance(m.get("author"), str) or not m["author"].strip():
        raise Bad("author missing")
    entry = m.get("entry", "main.lua")
    if not isinstance(entry, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,28}\.lua", entry) or entry.startswith("."):
        raise Bad("entry must be a .lua file name")
    perms = m.get("permissions", [])
    if not isinstance(perms, list):
        raise Bad("permissions must be a list")
    for p in perms:
        if p not in PERMISSIONS:
            raise Bad(f"unknown permission {p!r} (API {API_VERSION} knows {sorted(PERMISSIONS)})")
        if p in HW_PERMISSIONS and m["api"] < 2:
            raise Bad(f"permission {p} needs \"api\": 2")
        if p in VIEW_PERMISSIONS and m["api"] < 3:
            raise Bad(f"permission {p} needs \"api\": 3")
    if "speak" in perms and "schedule" not in perms:
        raise Bad("permission speak needs schedule (in a tool the LLM already speaks the result)")
    hardware = bool(set(perms) & HW_PERMISSIONS)
    check_hardware(m.get("hardware"), set(perms))
    tools = m.get("tools")
    if not isinstance(tools, list) or not 1 <= len(tools) <= TOOLS_MAX:
        raise Bad(f"tools must hold 1-{TOOLS_MAX} tools")
    seen = set()
    for t in tools:
        if not isinstance(t, dict):
            raise Bad("every tool must be an object")
        name = t.get("name", "")
        if (not isinstance(name, str) or not name.startswith(pid + "_") or len(name) > NAME_MAX
                or not re.fullmatch(r"[A-Za-z0-9_-]+", name)):
            raise Bad(f"tool name {name!r} must start with {pid}_ and use [A-Za-z0-9_-], at most {NAME_MAX}")
        if name in seen:
            raise Bad(f"tool {name} appears twice")
        seen.add(name)
        if not text(t.get("description")):
            raise Bad(f"tool {name} has no description")
        if "inputSchema" in t and not isinstance(t["inputSchema"], dict):
            raise Bad(f"inputSchema of {name} must be an object")
        fn = t.get("function", name)
        if not isinstance(fn, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", fn):
            raise Bad(f"function of {name} must be a Lua name")
        if "acts" in t and not isinstance(t["acts"], bool):
            raise Bad(f"acts of {name} must be true or false")
        if hardware and t.get("acts"):
            q = text(t.get("question"))
            if not q or len(q.encode()) > QUESTION_MAX:
                raise Bad(f"tool {name} changes hardware: it needs a question (at most {QUESTION_MAX} bytes), "
                          "asked aloud before it runs")
    return entry


def check_hardware(hw, perms):
    if hw is None:
        return
    if not isinstance(hw, list) or len(hw) > HW_ROLES_MAX:
        raise Bad(f"hardware: a list of at most {HW_ROLES_MAX} roles")
    names = set()
    for r in hw:
        if not isinstance(r, dict):
            raise Bad("hardware: every role must be an object")
        name, typ = r.get("name"), r.get("type")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]{1,15}", name):
            raise Bad("hardware role name: lowercase letters, digits and _, at most 15")
        if name in names:
            raise Bad(f"hardware role {name} appears twice")
        names.add(name)
        if typ not in HW_TYPES:
            raise Bad(f"role {name}: type must be one of {sorted(HW_TYPES)}")
        if HW_TYPES[typ] not in perms:
            raise Bad(f"role {name} needs the {HW_TYPES[typ]} permission")
        if typ == "gpio_out" and r.get("default", 0) not in (0, 1):
            raise Bad(f"role {name}: default must be 0 or 1")
        if typ == "gpio_in" and r.get("pull", "none") not in ("up", "down", "none"):
            raise Bad(f"role {name}: pull must be up, down or none")
        if typ == "uart" and not (isinstance(r.get("baud", 9600), int) and 1200 <= r.get("baud", 9600) <= 921600):
            raise Bad(f"role {name}: baud 1200-921600")
        if typ == "i2c":
            if r.get("speed", 100000) not in (100000, 400000):
                raise Bad(f"role {name}: speed 100000 or 400000")
            a = r.get("addresses")
            if (not isinstance(a, list) or not 1 <= len(a) <= 4
                    or not all(isinstance(x, int) and 0x08 <= x <= 0x77 for x in a)):
                raise Bad(f"role {name}: addresses, 1-4 7-bit addresses (8-119)")


def luac():
    for name in ("luac5.4", "luac"):
        path = shutil.which(name)
        if path:
            out = subprocess.run([path, "-v"], capture_output=True, text=True)
            if "5.4" in out.stdout + out.stderr:
                return path
    return None


def check_lua(source, label):
    path = luac()
    if not path:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as f:
        f.write(source)
    try:
        out = subprocess.run([path, "-p", f.name], capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    if out.returncode:
        raise Bad(f"{label}: Lua syntax error: {(out.stderr or out.stdout).strip()}")
    return True


def make_bundle(folder):
    """(manifest, bundle bytes) of a plugin source folder"""
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Bad(f"manifest.json: {e}")
    entry = check_manifest(manifest)
    if manifest["id"] != folder.name:
        raise Bad(f"folder name {folder.name} differs from id {manifest['id']}")
    try:
        source = (folder / entry).read_text(encoding="utf-8")
    except OSError as e:
        raise Bad(f"{entry}: {e}")
    if len(source.encode()) > SOURCE_MAX:
        raise Bad(f"{entry} is over {SOURCE_MAX // 1024} KB")
    check_lua(source, entry)
    bundle = json.dumps({"manifest": manifest, "files": {entry: source}}, ensure_ascii=False,
                        separators=(",", ":")).encode()
    if len(bundle) > BUNDLE_MAX:
        raise Bad(f"bundle is over {BUNDLE_MAX // 1024} KB")
    return manifest, bundle


def check_bundle(data):
    """manifest of a downloaded bundle, checked the way the board checks it"""
    if len(data) > BUNDLE_MAX:
        raise Bad(f"bundle is over {BUNDLE_MAX // 1024} KB")
    try:
        b = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Bad(f"bundle is not JSON: {e}")
    if not isinstance(b, dict) or not isinstance(b.get("files"), dict):
        raise Bad("bundle must be {\"manifest\": {...}, \"files\": {...}}")
    entry = check_manifest(b.get("manifest"))
    source = b["files"].get(entry)
    if not isinstance(source, str):
        raise Bad(f"bundle has no {entry}")
    if len(source.encode()) > SOURCE_MAX:
        raise Bad(f"{entry} is over {SOURCE_MAX // 1024} KB")
    check_lua(source, entry)
    return b["manifest"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tamago-plugin-registry"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(BUNDLE_MAX + 1)
    if len(data) > BUNDLE_MAX:
        raise Bad(f"bundle is over {BUNDLE_MAX // 1024} KB")
    return data


def registry_entry(path):
    """(entry, manifest, bundle bytes) of a registry/<id>.json file"""
    try:
        e = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise Bad(f"{path.name}: {err}")
    pid = path.stem
    if e.get("id") != pid:
        raise Bad(f"{path.name}: id must be {pid!r}, the file name")
    repo = e.get("repo")
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        raise Bad(f"{path.name}: repo must be owner/name on GitHub")
    url = e.get("url")
    if not isinstance(url, str) or not url.startswith(f"https://github.com/{repo}/releases/download/"):
        raise Bad(f"{path.name}: url must be a release asset of {repo}")
    sha = e.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise Bad(f"{path.name}: sha256 must be 64 lowercase hex digits")
    try:
        data = fetch(url)
    except Bad:
        raise
    except Exception as err:
        raise Bad(f"{path.name}: download failed: {err}")
    if hashlib.sha256(data).hexdigest() != sha:
        raise Bad(f"{path.name}: the file at url does not match sha256")
    manifest = check_bundle(data)
    if manifest["id"] != pid:
        raise Bad(f"{path.name}: the bundle's id is {manifest['id']!r}")
    return e, manifest, data


def all_plugins():
    """[(source link, manifest, bundle bytes)]; raises Bad listing every problem"""
    repo = os.environ.get("GITHUB_REPOSITORY", "programmer-iq6-plus/tamago-bot-plugins")
    found, problems = [], []
    for folder in sorted(p for p in (ROOT / "plugins").iterdir() if p.is_dir()):
        try:
            m, data = make_bundle(folder)
            found.append((f"https://github.com/{repo}/tree/main/plugins/{folder.name}", m, data))
        except Bad as e:
            problems.append(f"plugins/{folder.name}: {e}")
    for path in sorted((ROOT / "registry").glob("*.json")):
        try:
            e, m, data = registry_entry(path)
            found.append((f"https://github.com/{e['repo']}", m, data))
        except Bad as err:
            problems.append(f"registry/{err}" if str(err).startswith(path.name) else f"registry/{path.name}: {err}")
    ids = [m["id"] for _, m, _ in found]
    for pid in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"{pid}: listed both in plugins/ and registry/")
    if problems:
        raise Bad("\n".join(problems))
    return found


def sign(key, message):
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(message.encode())
    try:
        out = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key), f.name], capture_output=True)
        if out.returncode:
            raise Bad(f"signing failed: {out.stderr.decode().strip()}")
        sig = out.stdout
        with tempfile.NamedTemporaryFile(delete=False) as s:
            s.write(sig)
        try:
            ok = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(ROOT / "keys/plugin_pub.pem"),
                                 "-signature", s.name, f.name], capture_output=True)
        finally:
            os.unlink(s.name)
        if ok.returncode:
            raise Bad("the signing key does not match keys/plugin_pub.pem")
        return base64.b64encode(sig).decode()
    finally:
        os.unlink(f.name)


def cmd_check(_args):
    found = all_plugins()
    lua = "with" if luac() else "WITHOUT (install lua5.4 for it)"
    for _, m, data in found:
        print(f"ok  {m['id']} {m['version']}  {len(data)} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
    print(f"{len(found)} plugin(s), checked {lua} a Lua syntax check")


def cmd_bundle(args):
    folder = Path(args.folder)
    m, data = make_bundle(folder.resolve())
    out = Path(args.out) if args.out else Path(f"{m['id']}-{m['version']}.json")
    out.write_bytes(data)
    print(f"{out}  {len(data)} bytes")
    print(f"sha256 {hashlib.sha256(data).hexdigest()}")


def cmd_catalog(args):
    repo = os.environ.get("GITHUB_REPOSITORY", "programmer-iq6-plus/tamago-bot-plugins")
    base = args.base_url or f"https://raw.githubusercontent.com/{repo}/catalog"
    out = Path(args.out)
    (out / "bundles").mkdir(parents=True, exist_ok=True)
    plugins = []
    for source, m, data in all_plugins():
        sha = hashlib.sha256(data).hexdigest()
        fname = f"{m['id']}-{m['version']}.json"
        (out / "bundles" / fname).write_bytes(data)
        item = {
            "id": m["id"],
            "version": m["version"],
            "api": m["api"],
            "name": m["name"],
            "description": m["description"],
            "author": m["author"],
            "permissions": m.get("permissions", []),
            "hardware": [{"name": r["name"], "type": r["type"]} for r in m.get("hardware", [])],
            "tools": [{"name": t["name"], "description": t["description"], "acts": bool(t.get("acts", False))}
                      for t in m["tools"]],
            "source": source,
            "url": f"{base}/bundles/{fname}",
            "size": len(data),
            "sha256": sha,
        }
        if args.key:
            item["sig"] = sign(args.key, f"{SIG_PREFIX} {m['id']} {m['version']} {sha}")
        plugins.append(item)
    catalog = {
        "format": 1,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signed": bool(args.key),
        "plugins": plugins,
    }
    (out / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out}/catalog.json: {len(plugins)} plugin(s), {'signed' if args.key else 'NOT signed'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    b = sub.add_parser("bundle")
    b.add_argument("folder")
    b.add_argument("out", nargs="?")
    b.set_defaults(fn=cmd_bundle)
    c = sub.add_parser("catalog")
    c.add_argument("--out", required=True)
    c.add_argument("--key", help="private key (PEM) to sign with")
    c.add_argument("--base-url", help="where the out folder is served from")
    c.set_defaults(fn=cmd_catalog)
    args = ap.parse_args()
    try:
        args.fn(args)
    except Bad as e:
        sys.exit(f"error:\n{e}")


if __name__ == "__main__":
    main()
