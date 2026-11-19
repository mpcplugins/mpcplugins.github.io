"""One-time notes to plugin makers that their plugins are listed. Copyright (c) 2026 The Disk King. All rights reserved.

Rules (GitHub Acceptable Use: no excessive bulk activity, no advertising in other people's issues):
  * at most ONE note per calendar day (by date in state, not per run: the tracker runs on every push too)
  * at most one note per maker, EVER; every note is recorded in state/outreach.json (who, where, when, link)
  * before posting, GitHub itself is asked whether we already opened an issue there (so a lost state file
    can never cause a second note)
  * informational only: their listing, how to fix it, how to get Tested & Working, how to be removed. No store pitch.
  * skipped: overrides.json "no_contact", archived repos, repos with issues turned off, our own account
  * any refusal from GitHub (403/410/422/429) pauses outreach completely until "paused" is removed by hand
Needs the secret MPC_OUTREACH_TOKEN (a key from Jason's own account, which only he handles). Without it: does nothing.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
SITE = "https://thediskking.com/plugins/"
BADGE = "https://mpcplugins.github.io/badge/"
ALWAYS_SKIP = {"mpcplugins", "open-mpc"}


def _call(method, path, token, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                                          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "mpcplugins-tracker"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"null")
        except ValueError:
            return err.code, None
    except OSError as err:
        return 0, {"message": str(err)}


def key_check(token, today):
    """Ask GitHub who the key belongs to and what it may do. Returns a small report (no key in it)."""
    req = urllib.request.Request(API + "/user", headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                                                         "User-Agent": "mpcplugins-tracker"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            login = (json.loads(r.read() or b"{}") or {}).get("login")
            scopes = [s.strip() for s in (r.headers.get("X-OAuth-Scopes") or "").split(",") if s.strip()]
    except urllib.error.HTTPError as err:
        return {"date": today, "ok": False, "result": "GitHub did not accept the key (HTTP %s)" % err.code}
    except OSError as err:
        return {"date": today, "ok": False, "result": "could not reach GitHub (%s)" % err}
    if not login:
        return {"date": today, "ok": False, "result": "GitHub did not say whose key this is"}
    can_post = "public_repo" in scopes or "repo" in scopes
    return {"date": today, "ok": can_post, "login": login, "scopes": scopes,
            "result": ("OK: key for %s, can post notes" % login) if can_post else
                      ("key for %s works, but is missing the public_repo box" % login)}


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(path + ".tmp", path)


def owner_of(p):
    return p["repo"].split("/")[0]


def track_tested(plugins, state, today):
    """Remember when each plugin FIRST became Tested & Working. The first time this runs, everything already
    tested is the starting point (no notes for it). After that, a newly tested plugin puts its maker in 'pending'."""
    seen = state.setdefault("tested_seen", {})
    pending = state.setdefault("pending", {})
    first_time = not state.get("baseline")
    makers = state.setdefault("makers_seen", {})      # owner -> first day we listed them ("baseline" = before outreach)
    for p in plugins:
        makers.setdefault(owner_of(p), "baseline" if first_time else today)
    for p in plugins:
        if p.get("tier") != "verified" or p["id"] in seen:
            continue
        seen[p["id"]] = "baseline" if first_time else today
        if not first_time:
            pending.setdefault(owner_of(p), {"since": today, "plugins": []})
            if p["id"] not in pending[owner_of(p)]["plugins"]:
                pending[owner_of(p)]["plugins"].append(p["id"])
    if first_time:
        state["baseline"] = today


def queue(plugins, state, no_contact):
    """Makers waiting for their one note (a plugin of theirs newly became Tested & Working), oldest first."""
    by_id = {p["id"]: p for p in plugins}
    done = {o.lower() for o in list(state.get("contacted", {})) + list(state.get("skip", {})) + list(no_contact)} | ALWAYS_SKIP
    out = []
    for owner, info in state.get("pending", {}).items():
        if owner.lower() in done:
            continue
        new = [by_id[i] for i in info.get("plugins", []) if i in by_id and by_id[i].get("tier") == "verified"]
        if not new:
            continue
        new.sort(key=lambda p: (-(p.get("downloads") or 0), p["name"].lower()))
        repos = []
        for p in new:
            if p["repo"] not in repos:
                repos.append(p["repo"])
        is_new = state.get("makers_seen", {}).get(owner, "baseline") != "baseline"
        out.append({"owner": owner, "plugins": new, "repos": repos, "since": info.get("since", ""), "new_maker": is_new})
    # new makers first (they may not know any other plugin list yet), then oldest wait first
    out.sort(key=lambda x: (not x["new_maker"], x["since"], x["owner"].lower()))
    return out


def message(entry):
    ps = entry["plugins"]
    first = ps[0]
    title = "%s is Tested & Working on MPC Plugins" % first["name"] + (" (and %d more)" % (len(ps) - 1) if len(ps) > 1 else "")
    rows = ["- [%s](%s%s/)" % (p["name"], SITE, p["id"]) for p in ps[:25]]
    if len(ps) > 25:
        rows.append("- and %d more" % (len(ps) - 25))
    pid = first["id"]
    body = """Hi! Just a one-time note: your tested release%s now show%s as **Tested & Working** on **MPC Plugins**, a free list of plugins for the Akai MPC and Force that updates every night from GitHub releases:

%s

Tested & Working plugins are shown first everywhere on the list. Each page has your releases and download counts, the install steps for MPC OS 3.10.1, and an automatic check of each release zip.

**If anything is wrong**, or you'd rather not be listed, just reply here. We'll fix it or remove it, and we won't post here again either way.

Optional: a README badge that updates itself: `[![MPC Plugins](%s%s.svg)](%s%s/)`

Thanks for making it, and feel free to close this issue.
MPC Plugins Manager (https://mpcplugins.github.io)""" % (
        "s" if len(ps) > 1 else "", "" if len(ps) > 1 else "s", "\n".join(rows), BADGE, pid, SITE, pid)
    return title, body


def preview(plugins, state_path, overrides, out_path):
    """Write the next few notes to a file, sending nothing. Works without a token."""
    state = _load(state_path)                      # a copy: the preview never saves state
    track_tested(plugins, state, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    q = queue(plugins, state, overrides.get("no_contact", []))
    parts = ["# Outreach preview (nothing sent)\n", "Makers waiting for their one note: %d (1 a day).\n" % len(q)]
    if not q:     # show what a note looks like, using a tested plugin
        sample = [p for p in plugins if p.get("tier") == "verified"][:1]
        if sample:
            q = [{"owner": owner_of(sample[0]), "plugins": sample, "repos": [sample[0]["repo"]], "new_maker": False}]
            parts.append("Nobody is waiting yet; this is a SAMPLE of what a note looks like.\n")
    for e in q[:3]:
        t, b = message(e)
        parts.append("\n---\n## %s%s  ->  %s\n**%s**\n\n%s\n" % (e["owner"], " (new maker)" if e.get("new_maker") else "", e["repos"][0], t, b))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return len(q)


def run(plugins, state_path, overrides, log=print, today=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _load(state_path)
    state.setdefault("contacted", {})
    state.setdefault("skip", {})
    track_tested(plugins, state, today)            # always keep the record, even before the key is set up
    token = os.environ.get("MPC_OUTREACH_TOKEN", "").strip()
    if not token:
        state["key_check"] = {"date": today, "result": "no key set"}
        _save(state_path, state)
        log("   outreach: off (no MPC_OUTREACH_TOKEN secret); %d makers waiting" % len(queue(plugins, state, overrides.get("no_contact", []))))
        return
    state["key_check"] = key_check(token, today)       # never stores the key, only whether GitHub accepts it
    log("   outreach key: %s" % state["key_check"]["result"])
    if not state["key_check"].get("ok"):
        _save(state_path, state)
        return
    if state.get("paused"):
        _save(state_path, state)
        log("   outreach: PAUSED (%s). Remove 'paused' from state/outreach.json to resume." % state["paused"])
        return
    if state.get("last_sent") == today:
        _save(state_path, state)
        log("   outreach: already sent today's note")
        return
    login = state["key_check"]["login"]
    q = [e for e in queue(plugins, state, overrides.get("no_contact", [])) if e["owner"].lower() != login.lower()]
    log("   outreach: %d makers left" % len(q))
    for e in q[:10]:                               # look at up to 10 makers to find one we can post to; send ONE
        target = None
        for repo in e["repos"][:5]:
            s, info = _call("GET", "/repos/" + repo, token)
            if s == 200 and info and info.get("has_issues") and not info.get("archived"):
                target = repo
                break
        if not target:
            state["skip"][e["owner"]] = {"why": "issues off or archived", "date": today}
            log("   outreach: skip %s (issues off or archived)" % e["owner"])
            continue
        s, found = _call("GET", "/search/issues?q=" + urllib.request.quote("repo:%s author:%s is:issue" % (target, login)), token)
        if s == 200 and found and found.get("total_count"):
            state["contacted"][e["owner"]] = {"repo": target, "date": today, "url": found["items"][0].get("html_url"),
                                              "note": "found an earlier issue by us; not posting again"}
            log("   outreach: %s already has a note from us, recorded" % e["owner"])
            continue
        title, body = message(e)
        s, made = _call("POST", "/repos/%s/issues" % target, token, {"title": title, "body": body})
        if s == 201 and made:
            state["contacted"][e["owner"]] = {"repo": target, "date": today, "url": made.get("html_url"),
                                              "plugins": [p["id"] for p in e["plugins"]]}
            state["last_sent"] = today
            log("   outreach: sent note to %s (%s)" % (e["owner"], made.get("html_url")))
        else:
            state["paused"] = "GitHub answered HTTP %s on %s: %s" % (s, today, (made or {}).get("message", ""))
            log("   outreach: GitHub refused (HTTP %s); outreach paused for safety" % s)
        break
    _save(state_path, state)
