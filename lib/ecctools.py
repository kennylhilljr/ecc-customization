#!/usr/bin/env python3
"""Helpers for ecc-customization: the project kit, machine snapshots (with
secrets removed), their restore, OpenClaw state restore and plugin wiring,
and a secret scan. Standard library only; Python 3.9 or newer.

    ecctools.py kit-new REPO --name NAME [options]
    ecctools.py kit-diff REPO
    ecctools.py kit-sync REPO
    ecctools.py snapshot --root machine [--home DIR]
    ecctools.py restore --root machine [--home DIR] [--overwrite] [--dry-run]
    ecctools.py openclaw-restore --archive PATH --dest DIR
    ecctools.py openclaw-plugin --plugin-dir DIR --state-dir DIR
    ecctools.py scan PATH...

Nothing here prints a secret value: findings name the file, the line and the
kind of match, never the matched text.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "kit")

# ------------------------------------------------------------------ secrets
SECRET_KEY = re.compile(
    r"(token|secret|passw|api[_-]?key|apikey|auth|cookie|credential|private[_-]?key|"
    r"bearer|session|signature|webhook|client[_-]?id)", re.I)
SAFE_KEYS = {"selectedType", "enforcedType", "type", "useExternal", "authType"}
ENV_KEY = re.compile(r"^(env|environment|headers|http_headers|set)$", re.I)
TOKEN_SHAPES = [
    ("anthropic or openai key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("github token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("groq key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("aws key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credential in url", re.compile(r"[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@", re.I)),
]
OPAQUE = re.compile(r"(?<![A-Za-z0-9_/.\-])[A-Za-z0-9_\-+=]{32,}(?![A-Za-z0-9_/.\-])")


def _opaque_secret(s):
    """A long mixed-case alphanumeric run that is not hex (shas are fine)."""
    for m in OPAQUE.finditer(s):
        t = m.group(0)
        if re.fullmatch(r"[0-9a-fA-F\-]+", t):
            continue
        if re.search(r"[a-z]", t) and re.search(r"[A-Z]", t) and re.search(r"[0-9]", t):
            return True
    return False


def secret_kind(s):
    for kind, rx in TOKEN_SHAPES:
        if rx.search(s):
            return kind
    if _opaque_secret(s):
        return "long opaque string"
    return None


def scan_paths(paths):
    """[(path, line, kind)] for every file under paths."""
    hits = []
    for top in paths:
        for path in _walk_files(top):
            try:
                with open(path, encoding="utf-8") as fh:
                    for n, line in enumerate(fh, 1):
                        kind = secret_kind(line)
                        if kind:
                            hits.append((path, n, kind))
            except (UnicodeDecodeError, OSError):
                continue
    return hits


def _walk_files(top):
    if os.path.isfile(top):
        yield top
        return
    for d, dirs, files in os.walk(top):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            p = os.path.join(d, f)
            if not os.path.islink(p):
                yield p


def scrub_json(value, path="", removed=None, sensitive=False):
    """Copy of value with secret-looking entries removed; their dotted paths
    go to removed."""
    removed = [] if removed is None else removed
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            p = f"{path}.{k}" if path else str(k)
            key_secret = bool(SECRET_KEY.search(str(k))) and str(k) not in SAFE_KEYS
            env_like = bool(ENV_KEY.match(str(k)))
            if isinstance(v, (dict, list)):
                out[k] = scrub_json(v, p, removed, sensitive or key_secret or env_like)
            elif isinstance(v, str) and str(k) in SAFE_KEYS and not secret_kind(v):
                out[k] = v
            elif isinstance(v, str) and (sensitive or key_secret or secret_kind(v)):
                removed.append(p)
            elif key_secret and v is not None and not isinstance(v, bool):
                removed.append(p)
            else:
                out[k] = v
        return out
    if isinstance(value, list):
        out = []
        for i, v in enumerate(value):
            p = f"{path}[{i}]"
            if isinstance(v, str) and (sensitive or secret_kind(v)):
                removed.append(p)
            elif isinstance(v, (dict, list)):
                out.append(scrub_json(v, p, removed, sensitive))
            else:
                out.append(v)
        return out
    return value


TOML_TABLE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
TOML_KEY = re.compile(r"""^\s*("[^"]+"|'[^']+'|[A-Za-z0-9_.\-]+)\s*=""")


def scrub_toml(text, removed):
    """Line-based: drops secret-looking keys, every key inside env or header
    tables, inline env tables, and any line holding a token shape."""
    out, table, skipping = [], "", None
    for line in text.splitlines():
        if skipping:
            if skipping in line:
                skipping = None
            continue
        m = TOML_TABLE.match(line)
        if m:
            table = m.group(1)
            out.append(line)
            continue
        k = TOML_KEY.match(line)
        if k:
            key = k.group(1).strip("\"'")
            last = key.split(".")[-1]
            parts = [p.strip("\"'") for p in table.split(".")] if table else []
            env_table = any(ENV_KEY.match(p) for p in parts)
            name = f"{table}.{key}" if table else key
            if env_table or SECRET_KEY.search(last) or ENV_KEY.match(last) or secret_kind(line):
                removed.append(name)
                rest = line.split("=", 1)[1].strip()
                for q in ('"""', "'''"):
                    if rest.startswith(q) and rest.count(q) == 1:
                        skipping = q
                continue
        elif secret_kind(line):
            removed.append(f"{table or '(top)'}: line {len(out) + 1}")
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# ------------------------------------------------------------------ snapshot
SNAP_FILES = [  # (home-relative path, kind)
    (".claude/settings.json", "json"),
    (".claude/CLAUDE.md", "text"),
    (".codex/config.toml", "toml"),
    (".codex/AGENTS.md", "text"),
    (".gemini/settings.json", "json"),
    (".gemini/GEMINI.md", "text"),
]
SNAP_DIRS = [  # home-relative folders whose child entries are captured
    ".claude/skills", ".claude/agents", ".claude/commands",
    ".codex/skills", ".codex/prompts",
    ".gemini/skills", ".gemini/commands",
    ".agents/skills",
]
SKIP_NAMES = {".system", ".git", "node_modules", "__pycache__", ".DS_Store"}
MAX_FILE = 512 * 1024
HOME_TOKEN = "__HOME__"


def _home_out(text, home):
    return text.replace(home, HOME_TOKEN)


def _home_in(text, home):
    return text.replace(HOME_TOKEN, home)


def _run(argv, timeout=60):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def snapshot(root, home):
    """Capture machine customizations into root, secrets removed."""
    home = os.path.realpath(home)
    files_dir = os.path.join(root, "home")
    staging = tempfile.mkdtemp(prefix="ecc-snapshot-")
    manifest = {"schema_version": 1,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "files": [], "dirs": [], "removed": {}, "skipped": [], "plugins": {}}
    s_home = os.path.join(staging, "home")

    for rel, kind in SNAP_FILES:
        src = os.path.join(home, rel)
        if not os.path.isfile(src) or os.path.islink(src):
            continue
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        removed = []
        if kind == "json":
            try:
                data = scrub_json(json.loads(text), removed=removed)
            except json.JSONDecodeError:
                manifest["skipped"].append(f"{rel}: not plain JSON")
                continue
            text = json.dumps(data, indent=2, sort_keys=False) + "\n"
        elif kind == "toml":
            text = scrub_toml(text, removed)
        elif secret_kind(text):
            manifest["skipped"].append(f"{rel}: holds something that looks like a secret")
            continue
        _write(os.path.join(s_home, rel), _home_out(text, home))
        manifest["files"].append(rel)
        if removed:
            manifest["removed"][rel] = removed

    for rel in SNAP_DIRS:
        base = os.path.join(home, rel)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            src = os.path.join(base, name)
            if name in SKIP_NAMES or os.path.islink(src):
                continue
            if os.path.isdir(src) and os.path.exists(os.path.join(src, ".skillfish.json")):
                manifest["skipped"].append(f"{rel}/{name}: managed copy of a published skill")
                continue
            ok, why = _copy_clean(src, os.path.join(s_home, rel, name), home)
            if ok:
                manifest["dirs"].append(f"{rel}/{name}")
            else:
                manifest["skipped"].append(f"{rel}/{name}: {why}")

    manifest["plugins"] = _capture_plugins(home)

    hits = scan_paths([staging])
    if hits:
        shutil.rmtree(staging)
        for p, n, kind in hits:
            print(f"snapshot: refused, {os.path.relpath(p, staging)} line {n}: {kind}", file=sys.stderr)
        return 1
    if os.path.isdir(files_dir):
        shutil.rmtree(files_dir)
    os.makedirs(root, exist_ok=True)
    if os.path.isdir(s_home):
        shutil.move(s_home, files_dir)
    else:
        os.makedirs(files_dir)
    _write(os.path.join(root, "manifest.json"), json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print(f"snapshot: {len(manifest['files'])} files, {len(manifest['dirs'])} folders, "
          f"{sum(len(v) for v in manifest['removed'].values())} secret-looking entries removed, "
          f"{len(manifest['skipped'])} skipped")
    for s in manifest["skipped"]:
        print(f"  skipped {s}")
    for rel, keys in manifest["removed"].items():
        print(f"  {rel}: removed {', '.join(keys)}")
    return 0


def _copy_clean(src, dest, home):
    """Copy a file or folder of text files; refuse binaries, big files and secrets."""
    pairs = []
    if os.path.isfile(src):
        pairs.append((src, dest))
    else:
        for d, dirs, files in os.walk(src):
            dirs[:] = [x for x in dirs if x not in SKIP_NAMES and not os.path.islink(os.path.join(d, x))]
            for f in files:
                p = os.path.join(d, f)
                if f in SKIP_NAMES or os.path.islink(p):
                    continue
                pairs.append((p, os.path.join(dest, os.path.relpath(p, src))))
    for s, _ in pairs:
        if os.path.getsize(s) > MAX_FILE:
            return False, f"{os.path.relpath(s, src) or s} is larger than {MAX_FILE // 1024} KB"
        try:
            with open(s, encoding="utf-8") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            return False, f"{os.path.basename(s)} is not text"
        if secret_kind(text):
            return False, f"{os.path.basename(s)} holds something that looks like a secret"
    for s, d in pairs:
        with open(s, encoding="utf-8") as fh:
            _write(d, _home_out(fh.read(), home))
        shutil.copymode(s, d)
    return True, ""


def _capture_plugins(home):
    plugins = {}
    code, out, _ = _run(["claude", "plugin", "list", "--json"])
    if code == 0:
        try:
            items = json.loads(out)
            plugins["claude"] = [{"id": p["id"], "scope": p.get("scope")} for p in items
                                 if p.get("scope") in ("user",) and p.get("id")]
        except (ValueError, KeyError, TypeError):
            pass
    code, out, _ = _run(["claude", "plugin", "marketplace", "list", "--json"])
    if code == 0:
        try:
            plugins["claude_marketplaces"] = [s for s in (_marketplace_source(m) for m in json.loads(out)) if s]
        except (ValueError, TypeError):
            pass
    code, out, _ = _run(["codex", "plugin", "list", "--json"])
    if code == 0:
        try:
            plugins["codex"] = sorted(set(_ids(json.loads(out))))
        except ValueError:
            pass
    code, out, _ = _run(["codex", "plugin", "marketplace", "list", "--json"])
    if code == 0:
        try:
            plugins["codex_marketplaces"] = [s for s in (_marketplace_source(m) for m in _items(json.loads(out))) if s]
        except ValueError:
            pass
    ext = os.path.join(home, ".gemini", "extensions")
    gem = []
    if os.path.isdir(ext):
        for name in sorted(os.listdir(ext)):
            meta = os.path.join(ext, name, ".gemini-extension-install.json")
            if os.path.isfile(meta):
                try:
                    with open(meta) as fh:
                        src = json.load(fh).get("source")
                except ValueError:
                    src = None
                if src and not secret_kind(src):
                    gem.append({"name": name, "source": _home_out(src, home)})
    if gem:
        plugins["gemini_extensions"] = gem
    return plugins


def _items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def _ids(data):
    """Installed plugin ids (name@marketplace) anywhere in a JSON document."""
    out = []
    if isinstance(data, dict):
        name = data.get("id") or data.get("name")
        market = data.get("marketplace") or data.get("marketplace_name") or data.get("marketplaceName")
        installed = data.get("installed", True)
        if isinstance(name, str) and installed:
            if "@" in name:
                out.append(name)
            elif isinstance(market, str):
                out.append(f"{name}@{market}")
        for v in data.values():
            if isinstance(v, (dict, list)):
                out.extend(_ids(v))
    elif isinstance(data, list):
        for v in data:
            out.extend(_ids(v))
    return out


def _marketplace_source(m):
    if isinstance(m, str):
        return m
    if not isinstance(m, dict):
        return None
    src = m.get("source", m)
    if isinstance(src, str):
        return src
    if isinstance(src, dict):
        for key in ("repo", "url", "path", "source"):
            v = src.get(key)
            if isinstance(v, str) and v not in ("github", "git", "directory", "url"):
                return v
    for key in ("url", "repo", "root", "path"):
        if isinstance(m.get(key), str):
            return m[key]
    return None


# ------------------------------------------------------------------ restore
def restore(root, home, overwrite=False, dry=False):
    manifest_path = os.path.join(root, "manifest.json")
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    src_home = os.path.join(root, "home")
    problems = 0

    def place(rel_src, dest):
        nonlocal problems
        with open(rel_src, encoding="utf-8") as fh:
            text = _home_in(fh.read(), home)
        if os.path.exists(dest):
            with open(dest, encoding="utf-8", errors="replace") as fh:
                if fh.read() == text:
                    return "same"
            if not overwrite:
                side = dest + ".ecc-snapshot"
                if not dry:
                    _write(side, text)
                print(f"   differs, left as is: {dest} (snapshot written beside it as .ecc-snapshot)")
                return "side"
            if not dry:
                shutil.copy2(dest, dest + ".ecc-backup")
        if dry:
            print(f"   + write {dest}")
            return "would"
        else:
            _write(dest, text)
            shutil.copymode(rel_src, dest)
        return "written"

    for rel in manifest.get("files", []):
        result = place(os.path.join(src_home, rel), os.path.join(home, rel))
        if result == "written":
            print(f"   restored ~/{rel}")
        keys = manifest.get("removed", {}).get(rel)
        if keys and result != "same":
            print(f"   ~/{rel}: secrets were removed from the snapshot; re-add if needed: {', '.join(keys)}")
    for rel in manifest.get("dirs", []):
        top = os.path.join(src_home, rel)
        written = 0
        for p in _walk_files(top):
            dest = os.path.join(home, rel, os.path.relpath(p, top)) if os.path.isdir(top) else os.path.join(home, rel)
            if place(p, dest) == "written":
                written += 1
        if written:
            print(f"   restored ~/{rel} ({written} files)")
    problems += _restore_plugins(manifest.get("plugins", {}), home, dry)
    return 1 if problems else 0


def _restore_plugins(plugins, home, dry):
    problems = 0

    def do(argv):
        nonlocal problems
        if dry:
            print("   + " + " ".join(argv))
            return
        code, _, err = _run(argv, timeout=300)
        if code != 0:
            problems += 1
            print(f"   failed: {' '.join(argv)} ({err.strip().splitlines()[-1] if err.strip() else code})")

    if plugins.get("claude") or plugins.get("claude_marketplaces"):
        _, out, _ = _run(["claude", "plugin", "list", "--json"])
        try:
            have = {p.get("id") for p in json.loads(out or "[]")}
        except ValueError:
            have = set()
        for src in plugins.get("claude_marketplaces", []):
            do(["claude", "plugin", "marketplace", "add", _home_in(src, home)])
        for p in plugins.get("claude", []):
            if p["id"] not in have:
                do(["claude", "plugin", "install", p["id"], "--scope", "user"])
    if plugins.get("codex") or plugins.get("codex_marketplaces"):
        _, out, _ = _run(["codex", "plugin", "list", "--json"])
        try:
            have = set(_ids(json.loads(out or "[]")))
        except ValueError:
            have = set()
        for src in plugins.get("codex_marketplaces", []):
            do(["codex", "plugin", "marketplace", "add", _home_in(src, home)])
        for pid in plugins.get("codex", []):
            if pid not in have:
                do(["codex", "plugin", "add", pid])
    for ext in plugins.get("gemini_extensions", []):
        if not os.path.isdir(os.path.join(home, ".gemini", "extensions", ext["name"])):
            print(f"   for you: gemini extensions install {_home_in(ext['source'], home)}")
    return problems


# ------------------------------------------------------------------ openclaw
def openclaw_restore(archive, dest):
    archive = os.path.abspath(os.path.expanduser(archive))
    dest = os.path.abspath(os.path.expanduser(dest))
    if os.path.exists(dest):
        print(f"openclaw-restore: {dest} exists; not touching it", file=sys.stderr)
        return 1
    manifest = os.path.join(os.path.dirname(archive), "manifest.json")
    if os.path.isfile(manifest):
        with open(manifest) as fh:
            want = json.load(fh).get("archive_sha256")
        h = hashlib.sha256()
        with open(archive, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if want and h.hexdigest() != want:
            print("openclaw-restore: archive checksum does not match manifest.json", file=sys.stderr)
            return 1
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".openclaw-restore-", dir=os.path.dirname(dest))
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for m in tar.getmembers():
            name = m.name
            if not (m.isfile() or m.isdir()) or name.startswith("/") or ".." in name.split("/"):
                print(f"openclaw-restore: refusing archive member {name!r}", file=sys.stderr)
                shutil.rmtree(tmp)
                return 1
            if not (name == "openclaw" or name.startswith("openclaw/")):
                continue
            members.append(m)
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(tmp, members=members, **extra)
    os.chmod(os.path.join(tmp, "openclaw"), 0o700)
    os.rename(os.path.join(tmp, "openclaw"), dest)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"openclaw-restore: {len(members)} entries restored to {dest}")
    return 0


def _oc_get(key):
    for argv in (["openclaw", "config", "get", key, "--json"], ["openclaw", "config", "get", key]):
        code, out, err = _run(argv)
        if code == 0:
            out = out.strip()
            if not out or out in ("undefined", "null"):
                return None
            try:
                return json.loads(out)
            except ValueError:
                continue
        elif re.search(r"not (found|set)|no value|unknown key|undefined", (err + out), re.I):
            return None
    raise RuntimeError(f"cannot read OpenClaw config key {key}")


def _oc_set(key, value):
    code, _, err = _run(["openclaw", "config", "set", key, json.dumps(value)])
    if code != 0:
        raise RuntimeError(f"openclaw config set {key} failed: {err.strip()[:200]}")


def openclaw_plugin(plugin_dir, state_dir):
    plugin_dir = os.path.abspath(os.path.expanduser(plugin_dir))
    state_dir = os.path.abspath(os.path.expanduser(state_dir))
    entry = {"enabled": True, "config": {
        "eventLog": os.path.join(state_dir, "openclaw-events.jsonl"),
        "inbox": os.path.join(state_dir, "decisions"),
        "stateDir": os.path.join(state_dir, "openclaw-plugin")}}
    os.makedirs(entry["config"]["inbox"], exist_ok=True)
    os.makedirs(entry["config"]["stateDir"], exist_ok=True)
    try:
        paths = _oc_get("plugins.load.paths") or []
        if plugin_dir not in paths:
            _oc_set("plugins.load.paths", list(paths) + [plugin_dir])
            print("   added the plugin folder to plugins.load.paths")
        current = _oc_get("plugins.entries.ecc-orchestrator")
        if current != entry:
            _oc_set("plugins.entries.ecc-orchestrator", entry)
            print("   set plugins.entries.ecc-orchestrator")
        allow = _oc_get("plugins.allow")
        if allow and "ecc-orchestrator" not in allow:
            _oc_set("plugins.allow", list(allow) + ["ecc-orchestrator"])
            print("   added ecc-orchestrator to plugins.allow")
    except RuntimeError as exc:
        print(f"   {exc}", file=sys.stderr)
        return 1
    code, _, _ = _run(["openclaw", "plugins", "inspect", "ecc-orchestrator"])
    if code != 0:
        print("   openclaw plugins inspect ecc-orchestrator did not succeed", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------ kit
KIT_VARS = ["NAME", "SLUG", "REPO", "SPEC", "PRD", "TEST_PLAN", "SETUP_CMD", "TEST_CMD",
            "GATE_CMD", "FAST_GATE_CMD", "MILESTONE", "MILESTONE_LC", "RUN_ID",
            "RUNTIME_DIR", "STATE_DIR"]
KIT_RECORD = ".agents/kit.json"


def _kit_files(vars_):
    """[(template path, project-relative destination)]"""
    out = []
    for d, _, files in os.walk(KIT):
        for f in files:
            src = os.path.join(d, f)
            rel = os.path.relpath(src, KIT)
            if rel == "gitignore":
                continue
            dest = rel.replace("skills/run-project", f"skills/run-{vars_['SLUG']}")
            out.append((src, dest))
    return sorted(out, key=lambda x: x[1])


def _render(src, vars_):
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    for k in KIT_VARS:
        text = text.replace("{{" + k + "}}", vars_[k])
    left = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if left:
        raise SystemExit(f"kit: {os.path.relpath(src, KIT)} has unknown placeholders {sorted(set(left))}")
    return text


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _kit_version():
    code, out, _ = _run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"])
    return out.strip() if code == 0 else "unknown"


def _stack_value(name, default):
    path = os.path.join(ROOT, "stack.conf")
    try:
        with open(path) as fh:
            for line in fh:
                m = re.match(rf'^{name}="(.*)"\s*$', line.strip())
                if m:
                    return m.group(1).replace("$HOME", "~")
    except OSError:
        pass
    return default


def kit_new(repo, a):
    repo = os.path.abspath(os.path.expanduser(repo))
    if not os.path.isdir(repo):
        raise SystemExit(f"kit: {repo} is not a folder")
    home = os.path.expanduser("~")
    milestone = a.milestone
    vars_ = {
        "NAME": a.name, "SLUG": a.slug or os.path.basename(repo),
        "REPO": repo.replace(home, "~", 1) if repo.startswith(home) else repo,
        "SPEC": a.spec, "PRD": a.prd, "TEST_PLAN": a.test_plan,
        "SETUP_CMD": a.setup, "TEST_CMD": a.test_cmd, "GATE_CMD": a.gate,
        "FAST_GATE_CMD": a.fast_gate or a.gate, "MILESTONE": milestone,
        "MILESTONE_LC": milestone.lower(),
        "RUN_ID": a.run_id or f"{a.slug or os.path.basename(repo)}-{milestone.lower()}a",
        "RUNTIME_DIR": _stack_value("ECC_RUNTIME_DIR", "~/.local/share/openclaw-ecc-orchestrator/runtime"),
        "STATE_DIR": _stack_value("ECC_STATE_DIR", "~/.local/state/openclaw-ecc-orchestrator"),
    }
    record = {"kit_version": _kit_version(), "vars": vars_, "files": {}}
    for src, rel in _kit_files(vars_):
        text = _render(src, vars_)
        dest = os.path.join(repo, rel)
        record["files"][rel] = _sha(text)
        if os.path.exists(dest) and not a.force:
            print(f"  kept     {rel} (exists; --force replaces it)")
            continue
        _write(dest, text)
        print(f"  wrote    {rel}")
    link = os.path.join(repo, ".claude", "skills")
    if not os.path.lexists(link):
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink("../.agents/skills", link)
        print("  linked   .claude/skills -> ../.agents/skills")
    gi = os.path.join(repo, ".gitignore")
    existing = open(gi).read().splitlines() if os.path.exists(gi) else []
    with open(os.path.join(KIT, "gitignore")) as fh:
        add = [line for line in fh.read().splitlines() if line and line not in existing]
    if add:
        with open(gi, "a") as fh:
            if existing and existing[-1] != "":
                fh.write("\n")
            fh.write("\n".join(add) + "\n")
        print(f"  updated  .gitignore (+{len(add)} lines)")
    _write(os.path.join(repo, KIT_RECORD), json.dumps(record, indent=2) + "\n")
    print(f"  recorded {KIT_RECORD} (kit {record['kit_version']})")
    print("\nStill yours to fill in:")
    print("  .orchestration/config.yaml   high_risk_paths (the files a security reviewer must see)")
    print("  .orchestration/team.json     architect.contract_paths, designer.when_paths, milestone doc sections")
    print(f"  .agents/skills/run-{vars_['SLUG']}/SKILL.md   the real isolation settings and how to drive the project")
    print("  AGENTS.md                    project rules (the comment under Rules)")
    print(f"  .orchestration/plan-{vars_['MILESTONE_LC']}.json  the milestone plan, from the specification's work breakdown")
    return 0


def _load_record(repo):
    path = os.path.join(repo, KIT_RECORD)
    if not os.path.isfile(path):
        raise SystemExit(f"kit: {repo} has no {KIT_RECORD}; run kit-new first")
    with open(path) as fh:
        return json.load(fh)


def kit_diff(repo):
    repo = os.path.abspath(os.path.expanduser(repo))
    record = _load_record(repo)
    changed = 0
    for src, rel in _kit_files(record["vars"]):
        new = _render(src, record["vars"])
        dest = os.path.join(repo, rel)
        cur = open(dest, encoding="utf-8").read() if os.path.exists(dest) else ""
        if cur == new:
            continue
        changed += 1
        sys.stdout.writelines(difflib.unified_diff(
            new.splitlines(True), cur.splitlines(True), f"kit/{rel}", f"project/{rel}"))
    print(f"\n{changed} file(s) differ between the kit and the project "
          "('-' lines are the kit, '+' lines the project).")
    return 0


def kit_sync(repo):
    """Bring kit improvements into files the project has not changed since the
    kit wrote them; report the rest."""
    repo = os.path.abspath(os.path.expanduser(repo))
    record = _load_record(repo)
    for src, rel in _kit_files(record["vars"]):
        new = _render(src, record["vars"])
        dest = os.path.join(repo, rel)
        cur = open(dest, encoding="utf-8").read() if os.path.exists(dest) else None
        base = record["files"].get(rel)
        if cur == new:
            record["files"][rel] = _sha(new)
            continue
        if cur is None or _sha(cur) == base:
            _write(dest, new)
            record["files"][rel] = _sha(new)
            print(f"  updated  {rel}")
        else:
            print(f"  evolved  {rel} (changed in the project; see kit-diff)")
    record["kit_version"] = _kit_version()
    _write(os.path.join(repo, KIT_RECORD), json.dumps(record, indent=2) + "\n")
    return 0


# ------------------------------------------------------------------ main
def main(argv=None):
    p = argparse.ArgumentParser(prog="ecctools")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kit-new")
    k.add_argument("repo")
    k.add_argument("--name", required=True)
    k.add_argument("--slug")
    k.add_argument("--spec", default="docs/spec/SPEC-v1.md")
    k.add_argument("--prd", default="docs/prd/PRD-v1.md")
    k.add_argument("--test-plan", default="docs/test-plan/TEST-PLAN-v1.md")
    k.add_argument("--setup", default="uv sync --frozen")
    k.add_argument("--test-cmd", default="uv run pytest -q")
    k.add_argument("--gate", default="tools/ci.sh")
    k.add_argument("--fast-gate")
    k.add_argument("--milestone", default="M0")
    k.add_argument("--run-id")
    k.add_argument("--force", action="store_true")
    sub.add_parser("kit-diff").add_argument("repo")
    sub.add_parser("kit-sync").add_argument("repo")
    s = sub.add_parser("snapshot")
    s.add_argument("--root", required=True)
    s.add_argument("--home", default=os.path.expanduser("~"))
    r = sub.add_parser("restore")
    r.add_argument("--root", required=True)
    r.add_argument("--home", default=os.path.expanduser("~"))
    r.add_argument("--overwrite", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    o = sub.add_parser("openclaw-restore")
    o.add_argument("--archive", required=True)
    o.add_argument("--dest", required=True)
    op = sub.add_parser("openclaw-plugin")
    op.add_argument("--plugin-dir", required=True)
    op.add_argument("--state-dir", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("paths", nargs="+")
    a = p.parse_args(argv)

    if a.cmd == "kit-new":
        return kit_new(a.repo, a)
    if a.cmd == "kit-diff":
        return kit_diff(a.repo)
    if a.cmd == "kit-sync":
        return kit_sync(a.repo)
    if a.cmd == "snapshot":
        return snapshot(os.path.abspath(a.root), a.home)
    if a.cmd == "restore":
        return restore(os.path.abspath(a.root), os.path.realpath(a.home), a.overwrite, a.dry_run)
    if a.cmd == "openclaw-restore":
        return openclaw_restore(a.archive, a.dest)
    if a.cmd == "openclaw-plugin":
        return openclaw_plugin(a.plugin_dir, a.state_dir)
    if a.cmd == "scan":
        hits = scan_paths(a.paths)
        for path, n, kind in hits:
            print(f"{path}:{n}: looks like a {kind}")
        return 1 if hits else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
