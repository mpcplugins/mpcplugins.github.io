"""Facts about a plugin's GitHub repo: details, activity, README screenshot, links.

The README is read from raw.githubusercontent.com (no sign-in). Repo details (stars, topics,
archived, last push, open issues) come from GitHub's API when GITHUB_TOKEN is set.
"""
import os
import re
from urllib.parse import urljoin

from .net import fetch_json, fetch_text

IMG_MD = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
IMG_HTML = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
YOUTUBE = re.compile(r"https://(?:www\.)?(?:youtube\.com/(?:watch\?v=[\w-]{6,}|playlist\?list=[\w-]+|@[\w.-]+)|youtu\.be/[\w-]{6,})")
TIP = re.compile(r"https://(?:ko-fi\.com|buymeacoffee\.com|www\.buymeacoffee\.com|github\.com/sponsors|patreon\.com|"
                 r"www\.patreon\.com|liberapay\.com|paypal\.me|www\.paypal\.me|opencollective\.com)/[\w./-]+")
BADGE_HINTS = ("shields.io", "badge", "badgen", "travis-ci", "circleci", "codecov", "/actions/workflows/", "img.youtube.com",
               "contrib.rocks", "star-history", "visitor", "hits.", "ko-fi.com/img", "buymeacoffee.com/button")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def readme(repo):
    for name in ("README.md", "readme.md", "Readme.md", "README.MD", "README"):
        status, text = fetch_text("https://raw.githubusercontent.com/%s/HEAD/%s" % (repo, name))
        if status == 200 and text.strip():
            return name, text
    return None, ""


def _clean_url(u):
    return u.strip().split("#")[0]


ALT_MD = re.compile(r"!\[([^\]]*)\]")
ALT_HTML = re.compile(r"\balt\s*=\s*[\"']([^\"']*)[\"']", re.I)


def images_from(repo, readme_name, text):
    """Every real picture in the README, in order: [(alt text, https URL)]."""
    out = []
    base = "https://raw.githubusercontent.com/%s/HEAD/%s" % (repo, readme_name or "README.md")
    for m in sorted(list(IMG_MD.finditer(text)) + list(IMG_HTML.finditer(text)), key=lambda m: m.start()):
        url = _picture_url(base, m.group(1))
        if url:
            snippet = text[m.start():m.end()]
            alt = (ALT_MD.match(snippet) or ALT_HTML.search(snippet))
            out.append((alt.group(1) if alt else "", url))
    return out


def repo_images(repo):
    """Picture files in the repo itself (needs GITHUB_TOKEN; one request). [(path, raw URL)]"""
    if not os.environ.get("GITHUB_TOKEN"):
        return []
    status, d, _ = fetch_json("https://api.github.com/repos/%s/git/trees/HEAD?recursive=1" % repo)
    if status != 200 or not d:
        return []
    return [(x["path"], "https://raw.githubusercontent.com/%s/HEAD/%s" % (repo, x["path"]))
            for x in d.get("tree", []) if x.get("type") == "blob" and x["path"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            and not any(h in x["path"].lower() for h in ("icon", "logo", "badge", "knob", "button", "/skins/", "plugin skins"))][:4000]


def _key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def picture_for(product, readme_images, files):
    """The picture that names this plugin: README picture whose alt text or file name says it, else a repo file
    named after it. None if nothing names it (the caller then uses the project's first picture, shared)."""
    keys = [_key(product)]
    words = [w for w in re.split(r"[^A-Za-z0-9]+", product) if w]
    if len(words) > 1 and len(_key("".join(words[1:]))) >= 5:
        keys.append(_key("".join(words[1:])))         # "noxed-acidline": its pictures are named "acidline..."
    for k in keys:
        if len(k) < 3:
            continue
        for alt, url in readme_images:
            stem = _key(url.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            if k == _key(alt) or (len(stem) >= 3 and (stem == k or stem.endswith(k) or (k.endswith(stem) and len(stem) >= 5))):
                return url
        best = None
        for path, url in files:
            stem = _key(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            if stem == k or (stem.startswith(k) and len(stem) - len(k) <= 12) or ("/" in path and _key(path.split("/")[-2]) == k):
                if best is None or len(path) < len(best[0]):
                    best = (path, url)
        if best:
            return best[1]
    return None


def _picture_url(base, raw):
    url = _clean_url(raw)
    low = url.lower()
    if any(h in low for h in BADGE_HINTS) or low.endswith(".svg") or ".svg?" in low:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = urljoin(base, url.lstrip("./") if url.startswith("./") else url)
    url = re.sub(r"^https://github\.com/([^/]+/[^/]+)/blob/", r"https://raw.githubusercontent.com/\1/", url)
    low = url.lower()
    if url.startswith("https://") and (any(low.split("?")[0].endswith(e) for e in IMG_EXT)
                                     or "user-images.githubusercontent.com" in url or "/assets/" in url):
        return url
    return None


def screenshot_from(repo, readme_name, text):
    """First real picture in the README (not a badge), as an https URL."""
    base = "https://raw.githubusercontent.com/%s/HEAD/%s" % (repo, readme_name or "README.md")
    for m in sorted(list(IMG_MD.finditer(text)) + list(IMG_HTML.finditer(text)), key=lambda m: m.start()):
        url = _clean_url(m.group(1))
        low = url.lower()
        if any(h in low for h in BADGE_HINTS) or low.endswith(".svg") or ".svg?" in low:
            continue
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            url = urljoin(base, url.lstrip("./") if url.startswith("./") else url)
        # github.com/<repo>/blob/<ref>/<path> -> raw file
        url = re.sub(r"^https://github\.com/([^/]+/[^/]+)/blob/", r"https://raw.githubusercontent.com/\1/", url)
        if url.startswith("https://") and (any(low.split("?")[0].endswith(e) for e in IMG_EXT)
                                         or "user-images.githubusercontent.com" in url or "/assets/" in url):
            return url
    return None


def summary_from(text):
    """First plain paragraph of the README (fallback description)."""
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b[0] in "#!<[|>`-*" or b.startswith("```") or re.match(r"^\d+[.)]\s", b):
            continue
        b = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", b)        # links -> their text
        b = re.sub(r"[*_`]", "", b)
        b = re.sub(r"\s+", " ", b).strip()
        if len(b) > 40:
            return b[:350]
    return ""


def details(repo):
    """Repo facts. Uses the API only with a token; otherwise returns {}."""
    if not os.environ.get("GITHUB_TOKEN"):
        return {}
    status, d, _ = fetch_json("https://api.github.com/repos/%s" % repo)
    if status != 200 or not d:
        return {"missing": status in (404, 410, 451)}
    return {
        "description": d.get("description") or "",
        "topics": d.get("topics") or [],
        "stars": d.get("stargazers_count", 0),
        "archived": d.get("archived", False),
        "pushed": d.get("pushed_at"),
        "created": d.get("created_at"),
        "open_issues": d.get("open_issues_count", 0),
        "homepage": d.get("homepage") or "",
        "license": (d.get("license") or {}).get("spdx_id"),
    }


def gather(repo):
    """Everything we learn from the repo page and README."""
    info = details(repo)
    name, text = readme(repo)
    yt = YOUTUBE.search(text)
    tip = TIP.search(text)
    info.update({
        "screenshot": screenshot_from(repo, name, text) if text else None,
        "readme_images": images_from(repo, name, text) if text else [],
        "readme_summary": summary_from(text) if text else "",
        "youtube": yt.group(0) if yt else None,
        "tip": tip.group(0).rstrip(".,)") if tip else None,
    })
    return info
