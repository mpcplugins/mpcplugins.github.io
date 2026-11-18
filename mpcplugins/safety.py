"""Phase 3: safety checks in the nightly build.

- Every download of a plugin's newest version is checked once (inspect.check_zip) and remembered by sha256
  in state/inspect.json, so later nights only check new files.
- A version with a real problem (bad checksum, broken zip, no ARM library, wrong CPU, needs a newer MPC OS)
  is pulled: the plugin falls back to its newest stable version that passes.
- overrides.json "yank": ["id@1.2.0", "id@*"] pulls versions by hand ("id@*" hides the plugin).
- Addins that replace the same system function, where one doesn't pass the call on, are flagged as clashing.
- Two plugins shipping the same library file name are flagged (they can overwrite each other).
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from . import inspect, tested

_lock = threading.Lock()


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".new", "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(path + ".new", path)


def apply_yanks(plugins, yank):
    """Remove hand-pulled versions. Returns the plugins still listed."""
    out = []
    for p in plugins:
        if p["id"] + "@*" in yank:
            continue
        keep = [v for v in p["versions"] if "%s@%s" % (p["id"], v["version"]) not in yank]
        if not keep:
            continue
        if len(keep) != len(p["versions"]):
            p["yanked"] = [v["version"] for v in p["versions"] if v not in keep]
            p["versions"] = keep
            stable = [v for v in keep if not v["prerelease"]]
            p["latest"] = stable[0] if stable else keep[0]
            p["stable"] = bool(stable)
        out.append(p)
    return out


def _check_version(version, cache, budget):
    """Check every build of one version (cached). Returns {kind: result}."""
    results = {}
    for kind, b in version.get("builds", {}).items():
        sha = b.get("sha256")
        with _lock:
            hit = cache.get(sha) if sha else None
        if hit is None:
            with _lock:
                if budget[0] <= 0:
                    continue
                budget[0] -= 1
            hit = inspect.check_zip(b["url"], sha, kind)
            if hit.get("sha256"):
                with _lock:
                    cache[hit["sha256"]] = hit
                    if sha and sha != hit["sha256"]:
                        cache[sha] = hit
        results[kind] = hit
    return results


def _summary(results):
    problems = sorted({x for r in results.values() for x in r.get("problems", [])})
    warnings = sorted({x for r in results.values() for x in r.get("warnings", [])})
    os_by = {k: r.get("os") for k, r in results.items() if r.get("os")}
    return {
        "checked": bool(results),
        "ok": bool(results) and not problems,
        "problems": problems,
        "warnings": warnings,
        "risky": sorted({x for r in results.values() for x in r.get("risky", [])}),
        "risky_calls": sorted({x for r in results.values() for x in r.get("risky_calls", [])}),
        "installer_flags": sorted({x for r in results.values() for x in r.get("installer_flags", [])}),
        "os": os_by,
        "glibc": {k: r.get("glibc") for k, r in results.items() if r.get("glibc")},
        "builds_checked": sorted(results),
    }


def check_plugins(plugins, cache_path, log=print, workers=4, max_downloads=1500):
    """Run safety checks; pulls bad versions. Returns the updated plugin list."""
    cache = load(cache_path)
    budget = [max_downloads]

    def one(p):
        stable = [v for v in p["versions"] if not v["prerelease"]]
        candidates = stable if stable else p["versions"][:1]
        first = candidates[0] if candidates else p["latest"]
        res = _check_version(first, cache, budget)
        summary = _summary(res)
        if summary["checked"] and not summary["ok"]:
            # pull it: fall back to the newest older stable version that passes
            for older in candidates[1:4]:
                r2 = _check_version(older, cache, budget)
                s2 = _summary(r2)
                if s2["ok"]:
                    p["pulled"] = {"version": first["version"], "problems": summary["problems"]}
                    p["latest"] = older
                    summary = s2
                    break
            else:
                p["pulled"] = {"version": first["version"], "problems": summary["problems"]}
                p["blocked"] = True                 # no good version: listed, but no download offered
        p["safety"] = summary
        return p

    with ThreadPoolExecutor(max_workers=workers) as pool:
        plugins = list(pool.map(one, plugins))

    # re-check "tested" for plugins whose newest version was pulled
    for p in plugins:
        if p.get("pulled") and not p.get("blocked"):
            w = tested.verified_for(p["repo"], p["file_name"], p["latest"]["version"], 1)
            p["tested"] = w
            p["verified_on"] = [g for g in ("gen1", "gen2", "sample") if w.get(g)]
            if not p["verified_on"] and p.get("tier") == "verified":
                p["tier"], p["working"], p["points"] = "listed", False, 0.0
        if p.get("blocked"):
            p["tier"], p["working"], p["points"] = "experimental", False, -1.0

    # addins that clash, and shared library file names
    addins = [p for p in plugins if p["kind"] == "addin"]
    exports = {}
    for p in addins:
        for r in _results_for(p, cache):
            exports.setdefault(p["id"], {"names": set(), "chains": False})
            exports[p["id"]]["names"].update(r.get("exports", []))
            exports[p["id"]]["chains"] |= bool(r.get("chains"))
    ids = sorted(exports)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = exports[a]["names"] & exports[b]["names"]
            if shared and not (exports[a]["chains"] and exports[b]["chains"]):
                for x, y in ((a, b), (b, a)):
                    px = next(p for p in plugins if p["id"] == x)
                    px.setdefault("clashes_with", []).append({"id": y, "functions": sorted(shared)[:6]})
    owners = {}
    for p in plugins:
        for r in _results_for(p, cache):
            for so in r.get("so_names", []):
                owners.setdefault(so, set()).add(p["id"])
    for so, ids_ in owners.items():
        if len(ids_) > 1:
            for p in plugins:
                if p["id"] in ids_:
                    p.setdefault("same_file_as", []).extend(sorted(ids_ - {p["id"]}))

    save(cache_path, cache)
    checked = sum(1 for p in plugins if p["safety"]["checked"])
    pulled = sum(1 for p in plugins if p.get("pulled"))
    flagged = sum(1 for p in plugins if p["safety"]["risky"] or p["safety"]["installer_flags"])
    log("   safety: %d checked, %d versions pulled, %d flagged for review, %d downloads left in budget"
        % (checked, pulled, flagged, budget[0]))
    return plugins


def _results_for(p, cache):
    out = []
    for b in p["latest"].get("builds", {}).values():
        r = cache.get(b.get("sha256") or "")
        if r:
            out.append(r)
    return out
