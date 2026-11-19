"""'Verified working' from the maker's own tested.json (a file at the root of their repo).

Each record says which device and MPC OS a version was tested on, e.g.
  {"id": "my-synth", "version": "1.2.0", "device": "MPC Live III (Gen2)", "firmware": "3.10.1", "date": "2026-10-11"}
A plugin is Verified when its newest stable version has a record. A device naming "Gen2" counts as Gen2.
"""
import json
import re

from .net import fetch

import threading

_cache = {}
_lock = threading.Lock()


def records(repo):
    with _lock:
        if repo in _cache:
            return _cache[repo]
    status, body, _ = fetch("https://raw.githubusercontent.com/%s/HEAD/tested.json" % repo)
    out = []
    if status == 200:
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            if isinstance(data, list):
                out = [r for r in data if isinstance(r, dict) and r.get("version")]
        except ValueError:
            pass
    with _lock:
        _cache[repo] = out
    return out


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


GEN2_RE = re.compile(r"gen\s*2|aarch64|arm64|live\s*(iii|3)\b|one\s*g2|key\s*g2|\bmpc\s*xl\b|\bg2\b")


def device_gen(device):
    """Which hardware family a tested device is: sample, gen2 or gen1. Knows the Gen2 models by name,
    so 'MPC Live III' counts as Gen2 even without the word 'Gen2'."""
    d = str(device or "").lower()
    if "mpc sample" in d:
        return "sample"
    return "gen2" if GEN2_RE.search(d) else "gen1"


def _tokens(text):
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t]


def same_plugin(record_id, plugin_name):
    """Loose match between a tested.json id and our plugin name ('airwindows-tape' ~ 'AW-Tape')."""
    a, b = _norm(record_id), _norm(plugin_name)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta, tb = _tokens(record_id), _tokens(plugin_name)
    return bool(ta and tb) and ta[-1] == tb[-1] and len(ta[-1]) > 2


def verified_for(repo, plugin_name, version, plugins_in_repo, version_owners=1):
    """{'gen1': [..], 'gen2': [..]} test records for this plugin's version (empty lists if none).
    version_owners: how many separate releases in the repo have this exact version as their newest. A record without an id
    only counts when that is 1, so it can't be credited to the wrong plugin."""
    result = {"gen1": [], "gen2": [], "sample": []}
    for r in records(repo):
        if str(r.get("version")).lstrip("v") != str(version).lstrip("v"):
            continue
        if plugins_in_repo > 1:
            rid = r.get("id")
            if rid and not same_plugin(rid, plugin_name):
                continue    # the record names a different plugin
            if not rid and version_owners != 1:
                continue    # no id and the version is shared: can't tell which plugin was tested
        gen = device_gen(r.get("device", ""))
        result[gen].append({"device": r.get("device", ""), "os": r.get("firmware", ""), "date": r.get("date", "")})
    return result
