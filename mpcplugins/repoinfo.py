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
        "readme_summary": summary_from(text) if text else "",
        "youtube": yt.group(0) if yt else None,
        "tip": tip.group(0).rstrip(".,)") if tip else None,
    })
    return info
