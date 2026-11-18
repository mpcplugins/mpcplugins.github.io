"""Small HTTP helper for the MPC Plugins tracker (standard library only).

On a PC it runs with no sign-in at all. On GitHub's own servers (GitHub Actions)
it uses the GITHUB_TOKEN that GitHub hands every workflow run, and only for
api.github.com. It never reads tokens from anywhere else.
"""
import json
import os
import time
import urllib.error
import urllib.request

USER_AGENT = "mpcplugins-tracker"


def fetch(url, accept=None, tries=4, timeout=30):
    """GET a URL. Returns (status, body_bytes, headers). 404 returns (404, b"", {}).
    Waits and retries on rate limits and server errors."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            if err.code in (404, 410, 451):
                return err.code, b"", {}
            if err.code in (403, 429):
                retry_after = err.headers.get("Retry-After")
                reset = err.headers.get("X-RateLimit-Reset")
                if retry_after and retry_after.isdigit():
                    wait = int(retry_after)
                elif reset and reset.isdigit():
                    wait = int(reset) - int(time.time()) + 2
                else:
                    wait = 20 * (attempt + 1)
                time.sleep(min(max(wait, 2), 90))
                continue
            if err.code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(4 * (attempt + 1))
    return 0, b"", {}


def fetch_text(url, **kw):
    status, body, _ = fetch(url, **kw)
    return status, body.decode("utf-8", "replace")


def fetch_json(url, **kw):
    status, body, headers = fetch(url, accept="application/vnd.github+json", **kw)
    if status != 200:
        return status, None, headers
    return status, json.loads(body), headers
