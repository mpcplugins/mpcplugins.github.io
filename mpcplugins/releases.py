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


def is_prerelease(tag, title=""):
    """Beta words in the version TAG only. Titles hold plugin names (a synth called ALPHA is not an alpha),
    so GitHub's own Pre-release mark covers the rest."""
    low = tag.lower()
    ver = version_of(tag).lower()
    return any(w in ver for w in PRERELEASE_WORDS) or bool(re.search(r"(?:^|[-_.])(alpha|beta|rc\d*|pre|preview|nightly)(?:[-_.\d]|$)", low))


STANDARD_NAMES = ("mpc-armv7", "mpc-aarch64", "mpc-arm64", "mpc-sdk", "akai-vst2")


def _key(n):
    return re.sub(r"[^a-z0-9]", "", n.lower())


def _common(a, b):
    """Length of the longest run of letters two names share."""
    best = 0
    for i in range(len(a)):
        for j in range(i + best + 1, len(a) + 1):
            if a[i:j] in b:
                best = j - i
            else:
                break
    return best


def merge_renames(products):
    """A plugin renamed between releases ('Euclidier' -> 'Euclid', 'Early-Refl' -> 'Early-Reflections') shows up as
    two names whose releases never overlap in time. Fold the old name into the new one, keeping all versions.
    Two names released together in the same release are different plugins (XXL-STRIP and XXL-STRIP-BUS), never a rename."""
    names = sorted(products, key=lambda n: max(v["updated"] for v in products[n]), reverse=True)   # newest first
    merged = dict(products)
    for new in names:
        if new not in merged:
            continue
        first_new = min(v["updated"] for v in merged[new])
        for old in names:
            if old == new or old not in merged:
                continue
            a, b = _key(old), _key(new)
            similar = len(a) >= 4 and len(b) >= 4 and (a.startswith(b[:4]) or b.startswith(a[:4]))
            together = {v["tag"] for v in merged[old]} & {v["tag"] for v in merged[new]}
            if similar and not together and max(v["updated"] for v in merged[old]) <= first_new:
                merged[new] = sorted(merged[new] + merged.pop(old), key=lambda v: v["updated"], reverse=True)
    return merge_packagings(merged)


def one_per_version(products):
    """A plugin left unchanged in a newer release ('0.5.1' in both v0.2.2 and v0.2.3) is one version, not two:
    keep the newest release's entry and add the older one's downloads to it."""
    out = {}
    for name, vers in products.items():
        kept, by_v = [], {}
        for v in sorted(vers, key=lambda x: x["updated"], reverse=True):
            first = by_v.get(v["version"])
            if first is None:
                by_v[v["version"]] = v
                kept.append(v)
                continue
            if "downloads" in v:
                first["downloads"] = first.get("downloads", 0) + v.get("downloads", 0)
                for kind, b in v["builds"].items():
                    if kind in first["builds"] and "downloads" in b:
                        first["builds"][kind]["downloads"] = first["builds"][kind].get("downloads", 0) + b.get("downloads", 0)
            for kind, b in v["builds"].items():
                first["builds"].setdefault(kind, b)
        out[name] = kept
    return out


def drop_bundles(products, repo):
    """'NOXED-MPC-Plugins-0.2.3.zip' in repo noxed-mpc-plugins is every plugin zipped together, not a plugin of its own."""
    if len(products) < 2:
        return products
    rk = _key(repo.split("/")[-1])

    def bundle(name):
        if _key(name) != rk:
            return False
        names = [b["name"].lower() for v in products[name] for b in v["builds"].values()]
        return not any(m in n for n in names for m in STANDARD_NAMES)    # a real plugin build is never a bundle
    return {n: v for n, v in products.items() if not bundle(n)}


def merge_packagings(products):
    """The same plugin shipped twice in each release: properly named builds ('noxed-acidline-0.3.0-mpc-armv7.zip')
    plus an extra zip with a looser name ('acidline-0.3.0-mpc.zip'). Fold the loose one into the proper one when
    have the same version in every release they share, and the names clearly match. Releases from before the
    proper names existed come along as older versions."""
    def standard(name):
        return all(any(m in b["name"].lower() for m in STANDARD_NAMES)
                   for v in products[name] for b in v["builds"].values())

    def history(name):
        return {v["tag"]: v["version"] for v in products[name]}

    def fits(loose_name, proper):
        a, b = history(loose_name), history(proper)
        shared = set(a) & set(b)
        if not shared or any(a[t] != b[t] for t in shared):
            return False
        if not (set(b) <= set(a) or set(a) <= set(b)):
            return False
        ka, kb = _key(loose_name), _key(proper)
        return ka in kb or kb in ka or _common(ka, kb) >= 8
    merged = dict(products)
    loose = [n for n in products if not standard(n)]
    for old in loose:
        matches = [n for n in merged if n != old and n not in loose and fits(old, n)]
        if len(matches) > 1:             # 'mpc-overwitch' fits 'noxed-mpc-overwitch' and '...-send': take the one it ends
            ends = [n for n in matches if _key(n).endswith(_key(old))]
            matches = ends if len(ends) == 1 else matches
        if len(matches) != 1:
            continue                     # none, or ambiguous: leave both alone
        into = matches[0]
        by_tag = {v["tag"]: v for v in merged[into]}
        for v in merged.pop(old):
            if v["tag"] in by_tag:
                for kind, b in v["builds"].items():
                    by_tag[v["tag"]]["builds"].setdefault(kind, b)    # only fills a build the proper one lacks
            else:
                merged[into].append(v)                                 # an older release, before the proper names
        merged[into].sort(key=lambda v: v["updated"], reverse=True)
    return merged


def build_of(name):
    """Which MPC build a download file is: gen1, gen2, sdk, or None if it isn't an MPC file."""
    low = name.lower()
    if not low.endswith(".zip"):
        return None
    if not any(m in low for m in MPC_MARKERS):
        return None
    if "aarch64" in low or "arm64" in low or re.search(r"[-_]gen2\.zip$", low):
        return "gen2"
    if "armv7" in low or "armhf" in low or re.search(r"[-_]gen1\.zip$", low):
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


ASSET_VERSION_RE = re.compile(r"^.*?[-_ .]v?(\d+(?:[._]\d+)+)")


def asset_version(builds, tag, shared=True):
    """A plugin's version. In a release that holds several plugins, each has its own version in its download names
    ('noxed-acidline-0.3.0-mpc-armv7.zip' in release 'v0.2.3' is 0.3.0). A release of one plugin goes by its tag
    (tag v1.1.0 with a file still named 1.0.0 is version 1.1.0), unless the tag has no version at all."""
    tag_has = bool(VERSION_RE.search(tag))
    if not shared and tag_has:
        return version_of(tag)
    found = set()
    for b in builds.values():
        stem = b["name"][:-4] if b["name"].lower().endswith(".zip") else b["name"]
        m = ASSET_VERSION_RE.match(stem)
        found.add(m.group(1).replace("_", ".") if m else None)
    tag_v = version_of(tag)
    if len(found) == 1 and None not in found:
        v = found.pop()
        if tag_v.startswith(v + "-"):       # keep the tag's beta marker: '1.2.0' in tag 'v1.2.0-beta1'
            return tag_v
        return v
    return tag_v


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
                "version": asset_version(builds, tag, len(per_product) > 1),
                "tag": tag,
                "title": rel.get("name") or tag,
                "updated": rel.get("published_at") or rel.get("created_at") or "",
                "prerelease": bool(rel.get("prerelease")) or is_prerelease(tag),
                "notes": (rel.get("body") or "")[:4000],
                "downloads": sum(b.get("downloads", 0) for b in builds.values()),
                "builds": builds,
            })
    return one_per_version(merge_renames(drop_bundles(products, repo)))


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
        pre = is_prerelease(rel["tag"]) or marked_prerelease(repo, rel["tag"])
        for product, builds in per_product.items():
            products.setdefault(product, []).append({
                "version": asset_version(builds, rel["tag"], len(per_product) > 1),
                "tag": rel["tag"],
                "title": rel["title"],
                "updated": rel["updated"],
                "prerelease": pre,
                "builds": builds,
            })
    return one_per_version(merge_renames(drop_bundles(products, repo)))
