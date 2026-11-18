"""Starting list of known-good plugin repos.

Takes only the GitHub repo addresses of released, non-experimental plugins from Open MPC's
public list. Everything else (names, versions, downloads, checksums, tested-on) our own code
reads from each maker's repo.

    python -m mpcplugins.seeds      # refresh seeds.json
"""
import json
import os
import sys

from .net import fetch

SOURCE = "https://open-mpc.github.io/catalog.json"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = os.path.join(HERE, "seeds.json")


def refresh(log=print):
    status, body, _ = fetch(SOURCE, timeout=120)
    if status != 200:
        log("seeds: source not reachable (HTTP %s), keeping the saved list" % status)
        return load()
    repos = set()
    for p in json.loads(body).get("plugins", []):
        repo = p.get("repo")
        if not repo or p.get("distribution") == "build-yourself" or p.get("tier") == "experimental":
            continue
        repos.add(repo)
    old = set(load())
    merged = sorted(old | repos, key=str.lower)      # never drop a repo we already track
    tmp = SEEDS + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"repos": merged}, f, indent=1)
    os.replace(tmp, SEEDS)
    log("seeds: %d repos (%d new)" % (len(merged), len(set(merged) - old)))
    return merged


def load():
    try:
        with open(SEEDS, encoding="utf-8") as f:
            return json.load(f).get("repos", [])
    except (OSError, ValueError):
        return []


if __name__ == "__main__":
    refresh()
    sys.exit(0)
