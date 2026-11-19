"""Builds the MPC Plugins catalog.

    python -m mpcplugins.build [--out site] [--search]

1. Known-good repos (seeds.json + overrides.json add_repos).
2. For each repo: releases (versions, builds, checksums, notes, downloads), repo facts (README screenshot,
   activity, links) and the maker's tested.json.
3. Trust level, quality checklist, tags, collections, trending; writes catalog.json, then the site pages.
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import discover, outreach, releases, repoinfo, safety, seeds, site, tested

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERRIDES = os.path.join(HERE, "overrides.json")
STATE_DIR = os.path.join(HERE, "state")
STATE = os.path.join(STATE_DIR, "known_repos.json")
ADDED = os.path.join(STATE_DIR, "added.json")
HISTORY = os.path.join(STATE_DIR, "downloads.json")
WORKERS = 6            # repos checked at once; low enough to stay polite to GitHub

EFFECT_WORDS = ("reverb", "delay", "echo", " eq", "equaliz", "compress", "limiter", "saturat", "distort", "overdrive",
                "fuzz", "chorus", "flanger", "phaser", "tape", "vinyl", "lofi", "lo-fi", "bitcrush", "crusher", "filter",
                " fx", "effect", "verb", "tremolo", "tuner", "meter", "lufs", "amp ", "cab", "looper", "gate",
                "sidechain", "stereo", "widener", "exciter", "radio", "transient", "clipper", "mixbus", "strip")
ADDIN_WORDS = ("addin", "add-in", "ld_preload", "file browser", "usb audio", "skipback", "gateway", "commander")
INSTRUMENT_WORDS = ("synth", "sampler", "drum", "808", "909", "606", "303", "organ", "piano", "rompler", "sequencer",
                    "arp", "chord", "oscillator", "bass", "keys", "emulat", "instrument", "drone", "wavetable", " fm ")
STYLES = [("drum-machine", ("drum machine", "808", "909", "606", "drum")), ("sampler", ("sampler", "sample", "breaks", "sfz")),
          ("sequencer", ("sequencer", "arp", "euclid", "step")), ("synth", ("synth", "oscillator", "fm", "wavetable")),
          ("reverb", ("reverb", "verb", "hall", "plate", "room")), ("delay", ("delay", "echo")),
          ("tape", ("tape", "vhs", "vinyl", "lo-fi", "lofi")), ("saturation", ("saturat", "distort", "drive", "crush")),
          ("dynamics", ("compress", "limiter", "gate", "lufs", "transient")), ("eq", ("eq", "filter")),
          ("modulation", ("chorus", "flanger", "phaser", "tremolo", "vibe")), ("utility", ("tuner", "meter", "utility"))]
TAG_WORDS = ("808", "909", "606", "303", "drums", "breaks", "boom-bap", "lo-fi", "tape", "vinyl", "12-bit", "sampler", "synth",
             "fm", "analog", "vintage", "granular", "reverb", "delay", "chorus", "eq", "compressor", "saturation", "sequencer",
             "arpeggiator", "chords", "midi", "bass", "pads", "organ", "piano", "guitar", "looper", "dj", "utility")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "plugin"


def nice(name):
    return re.sub(r"[-_]+", " ", name).strip()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def words_of(*parts):
    return " " + " ".join(str(p or "") for p in parts).lower().replace("_", " ") + " "


def guess_kind(words, repo):
    if "addin" in repo.lower() or any(w in words for w in ADDIN_WORDS):
        return "addin"
    eff = sum(w in words for w in EFFECT_WORDS)
    ins = sum(w in words for w in INSTRUMENT_WORDS)
    return "effect" if eff > ins else "instrument"


def guess_style(words):
    for style, keys in STYLES:
        if any(k in words for k in keys):
            return style
    return "other"


def guess_tags(words, topics):
    tags = []
    for t in topics:
        t = slug(t)
        if t and t not in tags and t not in ("mpc", "akai", "vst", "vst2", "plugin", "akai-mpc", "akai-force", "mpc-plugin"):
            tags.append(t)
    for w in TAG_WORDS:
        if w.replace("-", " ") in words or w in words:
            if w not in tags:
                tags.append(w)
    return tags[:8]


def builds_present(version):
    b = version.get("builds", {})
    return {"gen1": "gen1" in b or "sdk" in b, "gen2": "gen2" in b or "sdk" in b}


def trust(stable, latest, works):
    """tier, verified_on list, evidence points."""
    has = builds_present(latest)
    on = []
    if works["gen1"] and has["gen1"]:
        on.append("gen1")
    if works["gen2"] and has["gen2"]:
        on.append("gen2")
    if works["sample"] and has["gen2"]:
        on.append("sample")
    if not stable:
        return "experimental", on, -1.0
    if not on:
        return "listed", on, 0.0
    needed = [g for g in ("gen1", "gen2") if has[g]]
    complete = all(g in on for g in needed) or ("sample" in on and not has["gen1"])
    return "verified", on, 3.0 if complete else 1.5


def quality(entry, latest, now):
    missing = []
    has = builds_present(latest)
    if not entry["stable"]:
        missing.append("stable-release")
    if not entry.get("screenshot"):
        missing.append("screenshot")
    if not entry["verified_on"]:
        missing.append("tested")
    elif has["gen2"] and "gen2" not in entry["verified_on"]:
        missing.append("tested-gen2")
    if not has["gen2"]:
        missing.append("gen2-build")
    if entry.get("archived"):
        missing.append("archived")
    pushed = entry.get("pushed")
    if pushed:
        try:
            if now - datetime.strptime(pushed[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) > timedelta(days=365):
                missing.append("inactive")
        except ValueError:
            pass
    if not entry.get("description"):
        missing.append("description")
    return missing


BAR_TEXT = {
    "stable-release": "publish a stable (non-beta) release",
    "screenshot": "add a picture of the plugin screen to the README",
    "tested": "add a tested.json entry for the newest release (device and MPC OS)",
    "tested-gen2": "add a tested.json entry for the newest release on a Gen2 device",
    "gen2-build": "publish a Gen2 (aarch64) build",
    "archived": "the repo is archived",
    "inactive": "no updates in over a year",
    "description": "add a short description to the repo",
    "review-flags": "explain the flagged behavior (network, running programs, installer commands) in the README",
}


def check_repo(info, log):
    """Plugin entries for one repo (empty if it has no MPC builds)."""
    repo = info["repo"]
    products = releases.mpc_releases(repo)
    if not products:
        return []
    facts = dict(info)
    facts.update({k: v for k, v in repoinfo.gather(repo).items() if v not in (None, "", [], {})})
    entries = []
    newest = {}
    for product, versions in products.items():
        stable = [v for v in versions if not v["prerelease"]]
        newest[product] = (stable[0] if stable else versions[0])["version"]
    for product, versions in products.items():
        stable = [v for v in versions if not v["prerelease"]]
        latest = stable[0] if stable else versions[0]
        owners = sum(1 for v in newest.values() if v == latest["version"])
        works = tested.verified_for(repo, product, latest["version"], len(products), owners) if stable \
            else {"gen1": [], "gen2": [], "sample": []}
        description = facts.get("description") or facts.get("readme_summary") or ""
        words = words_of(product, repo, description, " ".join(facts.get("topics", [])))
        tier, on, points = trust(bool(stable), latest, works)
        entries.append({
            "name": nice(product),
            "file_name": product,
            "maker": facts.get("owner") or repo.split("/")[0],
            "repo": repo,
            "kind": guess_kind(words, repo),
            "style": guess_style(words),
            "tags": guess_tags(words, facts.get("topics", [])),
            "description": description[:350],
            "about": facts.get("readme_summary", "")[:350],
            "screenshot": facts.get("screenshot"),
            "youtube": facts.get("youtube"),
            "tip": facts.get("tip"),
            "homepage": facts.get("homepage") if str(facts.get("homepage", "")).startswith("https://") else None,
            "topics": facts.get("topics", []),
            "stars": facts.get("stars", 0),
            "license": facts.get("license"),
            "archived": facts.get("archived", False),
            "pushed": facts.get("pushed"),
            "open_issues": facts.get("open_issues"),
            "stable": bool(stable),
            "latest": latest,
            "beta": versions[0] if versions[0] is not latest else None,
            "versions": versions,
            "downloads": sum(v.get("downloads", 0) for v in versions),
            "tested": works,
            "verified_on": on,
            "tier": tier,
            "points": points,
            "working": tier == "verified",
            "updated": versions[0]["updated"],
            "collection": slug(repo.split("/")[1]) if len(products) > 1 else None,
        })
    log("  + %-44s %s" % (repo, ", ".join("%s%s" % (e["name"], " *" if e["working"] else "") for e in entries)))
    return entries


def trending(final, today):
    """Downloads gained over the last 7 days, from our own nightly history."""
    hist = load_json(HISTORY, {})
    hist[today] = {p["id"]: p["downloads"] for p in final}
    days = sorted(hist)[-35:]
    hist = {d: hist[d] for d in days}
    save_json(HISTORY, hist, indent=None)
    week_ago = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    base_day = next((d for d in days if d >= week_ago), today)
    base = hist.get(base_day, {})
    for p in final:
        p["trending"] = max(0, p["downloads"] - base.get(p["id"], p["downloads"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the MPC Plugins catalog")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    ap.add_argument("--search", action="store_true",
                    help="also search GitHub for new plugins (they go to review.json, not the live list)")
    ap.add_argument("--no-site", action="store_true", help="write catalog.json only")
    ap.add_argument("--outreach", action="store_true",
                    help="send at most one note a day to a maker not contacted yet (needs MPC_OUTREACH_TOKEN)")
    ap.add_argument("--outreach-preview", action="store_true", help="write the next notes to state/outreach_preview.md, send nothing")
    ap.add_argument("--inspect", action="store_true",
                    help="safety-check release zips (downloads each new file once; used on GitHub's servers)")
    args = ap.parse_args(argv)
    log = lambda *a: print(*a, flush=True)
    started = time.time()
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    def blank(repo):
        return {"repo": repo, "owner": repo.split("/")[0], "description": "", "topics": []}

    log("1/4 Loading the known-good list")
    overrides = load_json(OVERRIDES, {})
    pool = {r: blank(r) for r in seeds.refresh(log=log)}
    for repo in overrides.get("add_repos", []):
        pool.setdefault(repo, blank(repo))
    for repo, info in load_json(STATE, {}).items():
        if repo in pool:
            pool[repo].update(info)
    log("   %d repos to check" % len(pool))

    log("2/4 Checking releases, repo pages and tested-on records")
    plugins, checked = [], set()

    def run(batch, into):
        """Check repos 6 at a time (each check is mostly waiting on the network)."""
        todo = [r for r in sorted(batch, key=str.lower) if r not in checked]
        checked.update(todo)

        def one(repo):
            try:
                return check_repo(batch[repo], log)
            except Exception as err:                    # one bad repo never stops the build
                log("  ! %s: %s" % (repo, err))
                return []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool_:
            for entries in pool_.map(one, todo):        # map keeps the order, so output is stable
                into.extend(entries)
    run(pool, plugins)

    review = []
    if args.search:
        log("   searching GitHub for plugins not on the list yet")
        finds = discover.candidates(log=log)
        finds.update(discover.owner_sweep({p["maker"] for p in plugins}, log=log))
        run({r: i for r, i in finds.items() if r not in pool}, review)
        save_json(os.path.join(STATE_DIR, "review.json"), {"note": "Found by search, NOT live. Add a repo to "
                  "overrides.json add_repos to publish it.", "plugins": review})
        log("   %d new plugins waiting for review" % len(review))

    log("3/4 Trust, quality, collections")
    hide = set(overrides.get("hide", []))
    fixes = overrides.get("plugins", {})
    added = load_json(ADDED, {})
    taken, final = set(), []
    for p in sorted(plugins, key=lambda e: (e["name"].lower(), e["repo"].lower())):
        pid = slug(p["file_name"])
        if pid in taken:
            pid = slug(p["maker"] + "-" + p["file_name"])
        taken.add(pid)
        p["id"] = pid
        if pid in hide or p["repo"] in hide:
            continue
        p.update(fixes.get(pid, {}))
        p["added"] = added.setdefault(pid, today)
        final.append(p)
    final = safety.apply_yanks(final, set(overrides.get("yank", [])))
    if args.inspect:
        log("   safety checks (each new download checked once)")
        final = safety.check_plugins(final, os.path.join(STATE_DIR, "inspect.json"), log=log)
    for old, new in overrides.get("aliases", {}).items():     # old page addresses that now belong to another plugin
        for p in final:
            if p["id"] == new and old not in p.get("old_ids", []):
                p.setdefault("old_ids", []).append(old)
    for p in final:
        p["bar_missing"] = quality(p, p["latest"], now)
        if p.get("safety", {}).get("risky") or p.get("safety", {}).get("installer_flags"):
            p["bar_missing"].append("review-flags")
    save_json(ADDED, added)
    trending(final, today)

    collections = {}
    for p in final:
        if p.get("collection"):
            c = collections.setdefault(p["collection"], {"id": p["collection"], "repo": p["repo"], "maker": p["maker"],
                                                         "title": nice(p["repo"].split("/")[1]), "members": []})
            c["members"].append(p["id"])
    for c in collections.values():
        c.update(fixes.get("collection:" + c["id"], {}))

    save_json(STATE, {p["repo"]: {"repo": p["repo"], "owner": p["maker"], "description": p["description"],
                                  "topics": p["topics"], "stars": p["stars"], "license": p["license"]} for p in final})
    counts = {}
    for p in final:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
    catalog = {
        "schema": "mpcplugins-1",
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(final),
        "makers": len({p["maker"] for p in final}),
        "working": sum(1 for p in final if p["working"]),
        "kinds": counts,
        "bar": BAR_TEXT,
        "collections": sorted(collections.values(), key=lambda c: c["title"].lower()),
        "plugins": final,
    }
    save_json(os.path.join(args.out, "catalog.json"), catalog, indent=None)

    if args.outreach_preview:
        n = outreach.preview(final, os.path.join(STATE_DIR, "outreach.json"), overrides, os.path.join(STATE_DIR, "outreach_preview.md"))
        log("   outreach preview: %d makers left, see state/outreach_preview.md" % n)
    if args.outreach:
        outreach.run(final, os.path.join(STATE_DIR, "outreach.json"), overrides, log=log, today=today)

    if not args.no_site:
        log("4/4 Writing plugin pages, feeds and sitemap")
        site.write(catalog, args.out, log=log)
    log("Done: %d plugins from %d makers, %d working, %s, in %.0f min" % (
        len(final), catalog["makers"], catalog["working"], counts, (time.time() - started) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
