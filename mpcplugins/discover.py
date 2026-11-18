"""Finds MPC plugin repos on GitHub by searching, then confirms each one by its releases.

Search uses GitHub's public repository search (10 searches a minute without a sign-in,
30 on GitHub's servers). A repo only counts as a plugin when a release actually carries
an MPC build (see releases.build_of).
"""
import time
from urllib.parse import quote

from .net import fetch_json

# Wide net: names, descriptions, README text and topics MPC plugin makers use.
QUERIES = [
    "mpc-vst in:name",
    "mpc-addin in:name",
    "mpc-plugin in:name",
    "mpc vst in:name,description",
    "mpc vst2 in:name,description,readme",
    "akai mpc plugin in:name,description,readme",
    "akai force plugin in:name,description,readme",
    "mpc os plugin in:description,readme",
    "mpc live plugin in:description,readme",
    "mpc one plugin in:description,readme",
    "mpc-armv7 in:readme",
    "mpc-aarch64 in:readme",
    "MPC Plugin SDK in:readme",
    "pluginList-arm in:readme",
    "VST2 Plugins MPC in:readme",
    "topic:akai-mpc",
    "topic:akai-force",
    "topic:mpc-plugin",
    "topic:mpc-vst",
    "topic:akai",
    "topic:mpc",
]


def search_repos(query, max_pages=10, pause=None):
    """All repos for one search query: {full_name: info}."""
    import os
    if pause is None:
        pause = 2.2 if os.environ.get("GITHUB_TOKEN") else 6.5   # stay under the search limit
    found = {}
    for page in range(1, max_pages + 1):
        url = "https://api.github.com/search/repositories?q=%s&per_page=100&page=%d" % (quote(query), page)
        status, data, _ = fetch_json(url)
        time.sleep(pause)
        if status != 200 or not data:
            break
        for item in data.get("items", []):
            found[item["full_name"]] = {
                "repo": item["full_name"],
                "owner": item["owner"]["login"],
                "description": item.get("description") or "",
                "topics": item.get("topics") or [],
                "stars": item.get("stargazers_count", 0),
                "fork": item.get("fork", False),
                "archived": item.get("archived", False),
                "pushed": item.get("pushed_at"),
                "homepage": item.get("homepage") or "",
                "license": (item.get("license") or {}).get("spdx_id"),
            }
        if len(data.get("items", [])) < 100:
            break
    return found


def candidates(extra_queries=(), log=print):
    """Every repo any search turns up."""
    pool = {}
    for q in list(QUERIES) + list(extra_queries):
        hits = search_repos(q)
        new = [r for r in hits if r not in pool]
        pool.update(hits)
        log("  search %-48s %4d hits, %4d new" % (q, len(hits), len(new)))
    return pool


def owner_sweep(owners, log=print):
    """Every repo of the given makers (catches plugins with unusual names)."""
    pool = {}
    for owner in sorted(owners):
        hits = search_repos("user:%s" % owner, max_pages=3)
        pool.update(hits)
        log("  maker %-30s %4d repos" % (owner, len(hits)))
    return pool
