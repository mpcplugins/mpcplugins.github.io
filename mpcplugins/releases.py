"""Reads a GitHub repo's releases from its public pages (no sign-in, no API quota).

- releases.atom gives the newest release tags in order.
- releases/expanded_assets/<tag> gives each download file with its sha256.
"""
import html
import os
import re
import time
from urllib.parse import quote, unquote

from .net import fetch_json, fetch_text

ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)
TAG_LINK_RE = re.compile(r'href="https://github\.com/[^"]+/releases/tag/([^"]+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
UPDATED_RE = re.compile(r"<updated>(.*?)</updated>")
DOWNLOAD_RE = re.compile(r'href="(/[^"]+/releases/download/[^"]+)"')
DIGEST_RE = re.compile(r'aria-label="Copy to clipboard digest for ([^"]+)"[^>]*value="sha256:([0-9a-f]{64})"')

PRERELEASE_WORDS = ("alpha", "beta", "-rc", ".rc", "rc1", "rc2", "rc3", "preview", "pre-release", "prerelease", "nightly")

# Download names that mark a file as built for an MPC or Force.
MPC_MARKERS = ("mpc-armv7", "mpc-aarch64", "mpc-arm64", "mpc-sdk", "akai-vst2", "-mpc.zip", "_mpc.zip",
               "mpc-force", "force-armv7", "-force.zip", "mpcos", "mpc_os", "mpc-plugin")


def release_list(repo, limit=8):
    """Newest-first list of {tag, title, updated} for a repo, from its Atom feed."""
    status, text = fetch_text("https://github.com/%s/releases.atom" % repo)
    if status != 200:
        return []
    out = []
    for block in ENTRY_RE.findall(text):
        tag = TAG_LINK_RE.search(block)
        if not tag:
            continue
        title = TITLE_RE.search(block)
        updated = UPDATED_RE.search(block)
        out.append({
            "tag": unquote(html.unescape(tag.group(1))),
            "title": html.unescape(title.group(1).strip()) if title else "",
            "updated": updated.group(1) if updated else "",
        })
        if len(out) >= limit:
            break
    return out


def release_assets(repo, tag):
    """Download files of one release: [{name, url, sha256}]."""
    url = "https://github.com/%s/releases/expanded_assets/%s" % (repo, quote(tag, safe=""))
    status, text = fetch_text(url)
    if status != 200:
        return []
    digests = {html.unescape(n): d for n, d in DIGEST_RE.findall(text)}
    assets, seen = [], set()
    for path in DOWNLOAD_RE.findall(text):
        path = html.unescape(path)
        if path in seen:
            continue
        seen.add(path)
        name = unquote(path.rsplit("/", 1)[-1])
        assets.append({"name": name, "url": "https://github.com" + path, "sha256": digests.get(name)})
    return assets


def is_prerelease(tag, title):
    words = (tag + " " + title).lower()
    return any(w in words for w in PRERELEASE_WORDS)


def build_of(name):
    """Which MPC build a download file is: gen1, gen2, sdk, or None if it isn't an MPC file."""
    low = name.lower()
    if not low.endswith(".zip"):
        return None
    if not any(m in low for m in MPC_MARKERS):
        return None
    if "aarch64" in low or "arm64" in low:
        return "gen2"
    if "armv7" in low or "armhf" in low:
        return "gen1"
    if "sdk" in low or "akai-vst2" in low:
        return "sdk"
    return "gen1"


VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)")


def version_of(tag):
    """'jn-106-vst-v0.2.0' -> '0.2.0', 'v2.4.2-rc3' -> '2.4.2-rc3'. The first dotted number wins."""
    m = VERSION_RE.search(tag)
    return m.group(1) if m else (re.sub(r"^[^0-9]*", "", tag) or tag)


def marked_prerelease(repo, tag):
    """GitHub's own Pre-release mark, from the release's public page."""
    status, text = fetch_text("https://github.com/%s/releases/tag/%s" % (repo, quote(tag, safe="")))
    return status == 200 and bool(PRE_LABEL_RE.search(text))


PRE_LABEL_RE = re.compile(r"Label--(?:warning|attention)[^>]*>\s*Pre-release\s*<")


PRODUCT_RE = re.compile(r"^(.*?)[-_ .]v?\d+(?:[._]\d+)+")


def product_of(filename):
    """Plugin name from a download name: 'Potential1200-1.0.2-mpc-armv7.zip' -> 'Potential1200'."""
    stem = filename[:-4] if filename.lower().endswith(".zip") else filename
    m = PRODUCT_RE.match(stem)
    if m and m.group(1):
        return m.group(1).strip("-_ .")
    for marker in MPC_MARKERS:     # no version in the name: cut at the MPC marker
        i = stem.lower().find(marker.replace(".zip", ""))
        if i > 0:
            return stem[:i].strip("-_ .")
    return stem


def _canon(name, seen):
    """One spelling per plugin: 'setBfree-Organ' and 'SetBfree-Organ' are the same plugin (first spelling wins)."""
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return seen.setdefault(key, name)


def _api_releases(repo, max_releases):
    """Same shape as the public-page reader, plus notes, sizes and download counts (needs GITHUB_TOKEN)."""
    status, data, _ = fetch_json("https://api.github.com/repos/%s/releases?per_page=%d" % (repo, max(max_releases, 10)))
    if status != 200 or not isinstance(data, list):
        return None
    products, seen = {}, {}
    for rel in [r for r in data if not r.get("draft")][:max_releases]:
        per_product = {}
        for a in rel.get("assets", []):
            kind = build_of(a.get("name", ""))
            if not kind:
                continue
            digest = a.get("digest") or ""
            builds = per_product.setdefault(_canon(product_of(a["name"]), seen), {})
            builds.setdefault(kind, {
                "name": a["name"],
                "url": a.get("browser_download_url"),
                "sha256": digest[7:] if digest.startswith("sha256:") else None,
                "size": a.get("size"),
                "downloads": a.get("download_count", 0),
            })
        tag = rel.get("tag_name", "")
        for product, builds in per_product.items():
            products.setdefault(product, []).append({
                "version": version_of(tag),
                "tag": tag,
                "title": rel.get("name") or tag,
                "updated": rel.get("published_at") or rel.get("created_at") or "",
                "prerelease": bool(rel.get("prerelease")) or is_prerelease(tag, rel.get("name") or ""),
                "notes": (rel.get("body") or "")[:4000],
                "downloads": sum(b.get("downloads", 0) for b in builds.values()),
                "builds": builds,
            })
    return products


def mpc_releases(repo, max_releases=10, pause=0.4):
    """MPC builds in a repo, grouped by plugin, newest release first:
    {product_name: [{version, tag, title, updated, prerelease, builds: {gen1|gen2|sdk: {name,url,sha256}}}]}"""
    if os.environ.get("GITHUB_TOKEN"):
        api = _api_releases(repo, max_releases)
        if api is not None:
            return api
    products, seen = {}, {}
    for rel in release_list(repo, limit=max_releases):
        time.sleep(pause)
        per_product = {}
        for asset in release_assets(repo, rel["tag"]):
            kind = build_of(asset["name"])
            if not kind:
                continue
            builds = per_product.setdefault(_canon(product_of(asset["name"]), seen), {})
            builds.setdefault(kind, asset)
        if not per_product:
            continue
        pre = is_prerelease(rel["tag"], rel["title"]) or marked_prerelease(repo, rel["tag"])
        for product, builds in per_product.items():
            products.setdefault(product, []).append({
                "version": version_of(rel["tag"]),
                "tag": rel["tag"],
                "title": rel["title"],
                "updated": rel["updated"],
                "prerelease": pre,
                "builds": builds,
            })
    return products
