"""Writes the static parts of the site from catalog.json:

  p/<id>/index.html     a full page per plugin (Google reads it: real text, no script needed)
  c/<id>/index.html     a page per collection
  feed.xml, feed/<id>.xml   Atom feeds (all releases, and one per plugin)
  sitemap.xml, robots.txt

Every value comes from other people's repos, so everything is escaped, and links must be https.
"""
import html
import json
import os
import re
from datetime import datetime, timezone

BASE = "https://mpcplugins.github.io/"
STORE = "https://thediskking.com/"
# Google should rank the thediskking.com copy of each page (same content, Jason's store), so canonicals point there.
CANON = "https://thediskking.com/plugins/"
e = html.escape

KIND_LABEL = {"instrument": "Instrument", "effect": "Effect", "addin": "Addin"}
DRUM_STYLES = ("drum-machine", "sampler", "sequencer", "tape", "saturation")


def https(url):
    return url if isinstance(url, str) and url.startswith("https://") and not re.search(r"[\s\"'<>]", url) else None


def size_text(n):
    if not n:
        return ""
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, n // 1024)


def date_text(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return ""


def json_ld(data):
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canon}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="MPC Plugins Manager">
<meta property="og:url" content="{canon}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
{og_image}
<meta name="twitter:card" content="{card}">
{extra_head}
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;800;900&display=swap" rel="stylesheet">
<style>
body {{ font-family: 'Inter', sans-serif; }}
.feature-tag {{ background: #ea861a; color: white; padding: 4px 10px; border-radius: 99px; font-size: 10px; font-weight: 900; letter-spacing: 0.1em; text-transform: uppercase; display: inline-block; }}
.tag-dark {{ background: #4b3621; }} .tag-blue {{ background: #3b82f6; }} .tag-green {{ background: #15803d; }} .tag-gray {{ background: #9ca3af; }}
html {{ -webkit-text-size-adjust: 100%; }} body {{ overflow-x: hidden; overflow-wrap: anywhere; }} #views {{ scrollbar-width: none; }} #views::-webkit-scrollbar {{ display: none; }} @media (max-width: 640px) {{ .clamp {{ -webkit-line-clamp: 3; }} }}
.notes {{ white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body class="bg-[#f5f5dc] text-[#4b3621] min-h-screen selection:bg-[#ea861a] selection:text-white">
<header class="bg-[#f5f5dc]/80 backdrop-blur-md shadow-sm sticky top-0 z-50 border-b border-[#4b3621]/5">
  <div class="container mx-auto px-4 md:px-6 py-3 md:py-4 flex justify-between items-center gap-4">
    <a href="/" class="leading-none text-[#4b3621] text-lg sm:text-2xl md:text-3xl font-black tracking-tighter whitespace-nowrap">MPC <span class="text-[#ea861a]">PLUGINS</span> MANAGER</a>
    <div class="flex items-center gap-4 md:gap-8">
      <a href="/" class="text-[10px] sm:text-xs md:text-sm font-bold uppercase tracking-widest hover:text-[#ea861a] whitespace-nowrap">&larr; All plugins</a>
    </div>
  </div>
</header>
"""

FOOT = """
<section class="container mx-auto px-4 md:px-6 py-10 md:py-16 border-t border-[#4b3621]/5">
  <div class="bg-white/60 border border-[#ea861a]/40 rounded-[2rem] md:rounded-[3rem] p-6 md:p-12 shadow-2xl text-center max-w-4xl mx-auto" style="box-shadow:0 0 50px rgba(234,134,26,.25)">
    <h2 class="text-2xl md:text-4xl font-black uppercase tracking-tighter mb-4">{pitch_head}</h2>
    <p class="opacity-70 font-medium text-base md:text-lg mb-6 md:mb-8 max-w-2xl mx-auto">{pitch_body}</p>
    <a href="{store}" class="inline-flex h-[52px] items-center bg-[#ea861a] text-white hover:bg-[#d97706] px-8 rounded-xl font-black text-sm uppercase tracking-widest shadow-lg">Shop MPC Expansions</a>
  </div>
</section>
<footer class="bg-[#4b3621] text-white py-12 md:py-20">
  <div class="container mx-auto px-4 md:px-6 text-center">
    <h4 class="text-2xl md:text-4xl font-black tracking-tighter mb-4">MPC PLUGINS MANAGER</h4>
    <div class="flex flex-wrap justify-center gap-x-6 md:gap-x-12 gap-y-3 text-xs font-bold uppercase tracking-widest opacity-60">
      <a href="/" class="hover:text-[#ea861a]">All plugins</a>
      <a href="{store}" class="hover:text-[#ea861a]">The Disk King</a>
      <a href="/install/" class="hover:text-[#ea861a]">How to install</a>
      <a href="/feed.xml" class="hover:text-[#ea861a]">Updates feed</a>
    </div>
    <p class="mt-12 text-[10px] opacity-40 uppercase tracking-[0.2em] max-w-3xl mx-auto leading-relaxed">Plugins are made and shared by independent developers; downloads come from each developer's GitHub. Provided as is, with no warranty. The Disk King is not responsible or liable for any damage or loss from any plugin. Download and install at your own risk. <a href="https://thediskking.com/policies.html#plugins" class="underline">Full disclaimer</a>. Not affiliated with Akai Professional or inMusic.</p>
    <p class="mt-6 text-[10px] opacity-20 uppercase tracking-[0.2em]">&copy; 2026 The Disk King. All rights reserved.</p>
  </div>
</footer>
</body>
</html>
"""


def pitch(p):
    if p.get("style") in DRUM_STYLES or any(t in (p.get("tags") or []) for t in ("drums", "breaks", "boom-bap", "808", "909", "lo-fi")):
        return ("Need drums for %s?" % e(p["name"]),
                "The Disk King makes boom bap, street and soul drum kits and chops for the MPC, ready to load in standard .XPN format.")
    return ("Load the plugins. <span class=\"text-[#ea861a]\">Load the sounds.</span>",
            "Plugins give your MPC new instruments. The Disk King's MPC Expansions give it the drums and chops: boom bap, street and soul kits.")


def badges(p):
    out = ['<span class="feature-tag">%s</span>' % e(KIND_LABEL.get(p["kind"], p["kind"]))]
    for g, label in (("gen1", "Verified Gen1"), ("gen2", "Verified Gen2"), ("sample", "Verified MPC Sample")):
        if g in p.get("verified_on", []):
            out.append('<span class="feature-tag tag-green">%s</span>' % label)
    if p["tier"] == "experimental":
        out.append('<span class="feature-tag tag-blue">Beta only</span>')
    if p.get("archived"):
        out.append('<span class="feature-tag tag-gray">Archived</span>')
    return " ".join(out)


DISCLAIMER = """
<div class="bg-white/70 border-2 border-[#4b3621]/30 rounded-2xl p-5 mb-4 text-sm leading-relaxed">
  <p class="font-black uppercase tracking-widest text-xs mb-2">Disclaimer: use entirely at your own risk</p>
  <p class="opacity-80 mb-2">This plugin is made, owned and shared by an independent developer, <strong>not</strong> by The Disk King, and not by Akai Professional or inMusic. We only list it; the download comes directly from the developer's GitHub. We did not make, test, review or check it for safety and make no promise that it works, is safe, or is free of bugs or harmful code.</p>
  <p class="opacity-80 mb-2">Plugins install into your MPC's system and can crash it, corrupt or lose projects and samples, or require reinstalling MPC OS. <strong>Save your work and back up your MPC before installing anything.</strong></p>
  <p class="opacity-80">Everything is provided "as is", with no warranty of any kind. To the fullest extent the law allows, The Disk King is not responsible or liable for any damage, data loss, device failure, lost income or any other harm from downloading, installing or using any plugin listed here. <strong>By downloading or installing, you accept all risk and full responsibility.</strong> <a href="https://thediskking.com/policies.html#plugins" class="underline font-bold">Full disclaimer</a>.</p>
</div>
"""


def status_box(p):
    if p["tier"] == "experimental":
        return ('<div class="bg-red-600 text-white rounded-2xl p-6 mb-4 shadow-xl border-4 border-red-800">'
                '<p class="text-2xl md:text-3xl font-black uppercase tracking-tighter mb-2">&#9888; Beta / unfinished: not tested</p>'
                '<p class="font-bold leading-relaxed">This plugin has no finished release yet. Expect bugs, crashes and missing features. '
                'Only install it if you know how to restore your MPC, and never on a device you need for a show or an important project. '
                'Use entirely at your own risk.</p></div>')
    if p["tier"] == "verified":
        seen = []
        for g in ("gen1", "gen2", "sample"):
            for t in (p.get("tested") or {}).get(g, []):
                os_ = str(t.get("os") or "")
                line = (t.get("device") or "") + ("" if not os_ or os_ == "not recorded" else ", MPC OS " + re.sub(r"(?i)^MPC OS\s*", "", os_))
                if line not in seen:
                    seen.append(line)
        return ('<div class="bg-green-700 text-white rounded-2xl p-5 mb-4"><p class="text-xl font-black uppercase tracking-tighter mb-1">&#10003; Tested &amp; working</p>'
                '<p class="font-medium opacity-90">The creator reports testing this exact version on real hardware: %s. This is the creator\'s own report, '
                'not a guarantee. Still back up first.</p></div>' % e("; ".join(seen) or "a real MPC"))
    return ('<div class="bg-amber-400 text-[#4b3621] rounded-2xl p-5 mb-4 border-2 border-amber-600">'
            '<p class="text-xl font-black uppercase tracking-tighter mb-1">&#9888; Not yet tested on hardware</p>'
            '<p class="font-bold leading-relaxed">This is a finished release, but the creator hasn\'t recorded a test of this version on a real MPC or '
            'Force. It may work fine; it may not. Back up first and try it on a project that doesn\'t matter.</p></div>')


SAFETY_WORDS = {"web server": "runs a small web page on your Wi-Fi (often its phone or browser screen)",
                "internet": "connects to the internet", "network": "uses the network",
                "runs programs": "starts other programs", "stops programs": "can stop other programs (often to restart MPC)",
                "loads code": "loads extra code while running", "system changes": "can change system settings"}


def safety_box(p):
    s = p.get("safety")
    if p.get("blocked"):
        pulled = p.get("pulled") or {}
        return ('<div class="bg-red-700 text-white rounded-2xl p-5 mb-4 border-4 border-red-900"><p class="text-xl font-black uppercase '
                'tracking-tighter mb-1">&#10007; Download removed by our safety check</p><p class="font-bold text-sm">Version %s failed: %s. '
                'No working version is offered until the creator fixes it.</p></div>' % (e(pulled.get("version", "")), e("; ".join(pulled.get("problems", [])))))
    if not s or not s.get("checked"):
        return ('<div class="bg-white/60 border border-[#4b3621]/15 rounded-2xl p-4 mb-4 text-sm font-bold opacity-80">Safety check: pending. '
                'Each new release is checked in the nightly build.</div>')
    names = {"gen1": "Gen1 (32-bit ARM)", "gen2": "Gen2 (64-bit ARM)", "sdk": "Akai SDK"}
    flags = [SAFETY_WORDS.get(r, r) for r in s.get("risky", [])]
    inst = s.get("installer_flags", [])
    clash = [c.get("id", "") for c in p.get("clashes_with", [])]
    same = p.get("same_file_as", [])
    uid = p.get("same_uid_as", [])
    warn = bool(flags or inst or clash or same or uid or p.get("pulled"))
    os_ = sorted(set(v for v in (s.get("os") or {}).values() if v))
    items = ["&#10003; Download matches the checksum GitHub lists",
             "&#10003; Built for: %s" % e(", ".join(names.get(k, k) for k in s.get("builds_checked", [])))]
    if os_:
        items.append("&#10003; Runs on: %s" % e(" / ".join(os_)))
    if flags:
        items += ["&#9873; The plugin %s." % e(f) for f in flags]
        items.append('<span class="text-xs opacity-70">These can be completely normal for what the plugin does, but know them before installing.</span>')
    else:
        items.append("&#10003; No internet, web server, program-launching or system-changing functions found")
    items.append("&#9873; Its installer %s." % e(", ".join(inst)) if inst else "&#10003; Nothing risky found in its installer")
    if clash:
        items.append("&#9888; May clash with these addins if installed together: %s" % e(", ".join(clash)))
    if same:
        items.append("&#9888; Uses the same library file name as: %s. Installing both may overwrite one." % e(", ".join(same)))
    if uid:
        items.append("&#9888; Uses the same plugin ID as: %s. If you install both, MPC may load one in place of the other, "
                     "and projects can open the wrong plugin." % ", ".join('<a href="/p/%s/" class="underline">%s</a>' % (e(o), e(o)) for o in uid))
    pulled = ""
    if p.get("pulled"):
        pulled = ('<p class="font-bold text-amber-800 mb-2">&#9888; Version %s was pulled (%s). The download below is the last version that passed.</p>'
                  % (e(p["pulled"]["version"]), e("; ".join(p["pulled"].get("problems", [])))))
    return ('<div class="%s rounded-2xl p-5 mb-4 text-sm leading-relaxed"><p class="font-black uppercase tracking-widest text-xs mb-3">%s</p>%s'
            '<ul class="space-y-1 font-medium">%s</ul><p class="text-[11px] opacity-60 mt-3">An automatic look at the files, not a guarantee: it '
            'can\'t see everything a program does. Always back up first.</p></div>'
            % ("bg-amber-50 border-2 border-amber-500" if warn else "bg-white/70 border-2 border-green-700/40",
               "&#9873; Safety check: review the notes below" if warn else "&#10003; Safety check passed", pulled,
               "".join("<li>%s</li>" % i for i in items)))


def needs_box(p):
    rows = []
    if "mpc-sample" in (p.get("devices") or []):
        rows.append(("Only for", "MPC Sample. It does nothing on other MPCs."))
    if p.get("min_os"):
        rows.append(("MPC OS", e(p["min_os"]) + " or later"))
    if p.get("needs"):
        rows.append(("Needs", e(p["needs"])))
    if p.get("user_files"):
        rows.append(("Your own files", e(", ".join(p["user_files"])) + " (not included: you supply them)"))

    def links(items):
        return ", ".join('<a href="/p/%s/" class="underline font-bold">%s</a>' % (e(d["id"]), e(d["text"])) if d.get("id") else e(d["text"])
                         for d in items)
    if p.get("depends"):
        rows.append(("Install with", links(p["depends"])))
    if p.get("conflicts"):
        rows.append(("Don't install with", links(p["conflicts"])))
    if p.get("needed_by"):
        rows.append(("Used by", links([{"id": i, "text": i} for i in p["needed_by"]])))
    if not rows:
        return ""
    return ('<div class="bg-white/70 border-2 border-[#ea861a]/50 rounded-2xl p-5 mb-4 text-sm"><p class="font-black uppercase tracking-widest '
            'text-xs mb-3">Before you install</p><dl class="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2">%s</dl></div>'
            % "".join('<dt class="font-black">%s</dt><dd class="font-medium">%s</dd>' % (e(a), b) for a, b in rows))


def copy_box(p):
    """MPC OS 3.10.1 by-hand install: the exact folder to copy into 'VST2 Plugins'."""
    copy = (p.get("safety") or {}).get("copy") or {}
    if not copy or p.get("kind") == "addin" or p.get("blocked"):
        return ""
    names = {"sdk": "Works-on-both download", "gen1": "Gen1 download", "gen2": "Gen2 download"}
    code = '<code class="bg-[#4b3621]/10 px-1 rounded font-bold break-all">%s</code>'
    ok = {k: c for k, c in copy.items() if c.get("ok") and c.get("folder")}
    if ok:
        items = "".join(
            "<li><strong>%s:</strong> unzip it and copy %s%s into %s on your drive.</li>"
            % (names[k], code % e(ok[k]["folder"]),
               (" (inside %s)" % (code % e(ok[k]["inside"] + "/"))) if ok[k].get("inside") else "", code % "VST2 Plugins")
            for k in ("sdk", "gen1", "gen2") if k in ok)
        return ('<div class="bg-green-50 border-2 border-green-700/40 rounded-2xl p-5 mb-4 text-sm">'
                '<p class="font-black uppercase tracking-widest text-xs mb-3 text-green-800">&#10003; Easy install on MPC OS 3.10.1: copy one folder</p>'
                '<ul class="space-y-2 font-medium">%s</ul><p class="mt-3 text-xs opacity-80">Turn on External Plugin Support first. '
                '<a href="/install/" class="underline font-bold">Full step-by-step guide</a>.</p></div>' % items)
    return ('<div class="bg-amber-100 border-2 border-amber-500 rounded-2xl p-5 mb-4 text-sm">'
            '<p class="font-black uppercase tracking-widest text-xs mb-2">Can\'t be copied by hand on MPC OS 3.10.1</p>'
            '<p class="font-medium">This release\'s plugin folder has no %s, which 3.10.1 needs to list it. Use the creator\'s installer '
            '(see INSTALL.md in the zip), or ask the creator for a 3.10.1 release. <a href="/install/#folder" class="underline font-bold">Why?</a></p></div>'
            % (code % "plugin.json"))


def build_rows(version):
    rows = []
    labels = {"sdk": "Works on both Gen1 and Gen2: MPC OS 3.10.1 or later (Akai SDK)", "gen1": "Gen1: Live, Live II, One, X, Key, Force",
              "gen2": "Gen2: Live III, One G2, Key G2, XL"}
    for kind in ("sdk", "gen1", "gen2"):
        b = version.get("builds", {}).get(kind)
        if not b or not https(b.get("url")):
            continue
        sha = b.get("sha256") or ""
        rows.append(
            '<div class="bg-white/60 rounded-2xl p-4 border border-[#4b3621]/10 flex flex-col md:flex-row md:items-center gap-3">'
            '<div class="flex-1"><p class="font-black">%s</p><p class="text-xs opacity-60 break-all">%s %s</p>%s</div>'
            '<a href="%s" rel="nofollow noopener" class="bg-[#ea861a] hover:bg-[#d97706] text-white px-5 py-3 rounded-xl font-black text-xs uppercase tracking-widest text-center">Download</a></div>'
            % (e(labels[kind]), e(b.get("name", "")), e(size_text(b.get("size"))),
               '<p class="text-[10px] opacity-50 break-all mt-1">sha256: %s</p>' % e(sha) if sha else "",
               e(b["url"])))
    return "\n".join(rows)


def plugin_page(p, cat, collections):
    url = BASE + "p/%s/" % p["id"]
    desc = p.get("description") or p.get("about") or "%s for Akai MPC and Force." % p["name"]
    title = "%s by %s: Free %s for Akai MPC & Force | MPC Plugins Manager" % (p["name"], p["maker"], KIND_LABEL.get(p["kind"], "Plugin"))
    shot = https(p.get("screenshot"))
    latest = p["latest"]
    repo_url = "https://github.com/%s" % p["repo"]
    head = HEAD.format(
        title=e(title), desc=e(desc[:300]), url=e(url), canon=e(CANON + p["id"] + "/"),
        og_image='<meta property="og:image" content="%s">' % e(shot) if shot else "",
        card="summary_large_image" if shot else "summary",
        extra_head='<link rel="alternate" type="application/atom+xml" title="%s updates" href="/feed/%s.xml">\n'
                   '<script type="application/ld+json">%s</script>' % (e(p["name"]), e(p["id"]), json_ld({
                       "@context": "https://schema.org", "@type": "SoftwareApplication", "name": p["name"],
                       "applicationCategory": "MultimediaApplication", "operatingSystem": "Akai MPC OS, Akai Force",
                       "softwareVersion": latest["version"], "description": desc[:300], "url": url,
                       "author": {"@type": "Person", "name": p["maker"]},
                       "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                       **({"image": shot} if shot else {}),
                       **({"downloadUrl": repo_url + "/releases"}),
                   })))
    tested_lines = []
    for g in ("gen1", "gen2", "sample"):
        for t in (p.get("tested") or {}).get(g, []):
            tested_lines.append("<li>%s, MPC OS %s%s</li>" % (e(t.get("device", "")), e(t.get("os", "")),
                                                               " (%s)" % e(date_text(t.get("date"))) if t.get("date") else ""))
    links = ['<a href="%s" rel="noopener" class="underline font-bold hover:text-[#ea861a]">Source on GitHub</a>' % e(repo_url)]
    if https(p.get("youtube")):
        links.append('<a href="%s" rel="noopener nofollow" class="underline font-bold hover:text-[#ea861a]">Video</a>' % e(p["youtube"]))
    if https(p.get("tip")):
        links.append('<a href="%s" rel="noopener nofollow" class="underline font-bold hover:text-[#ea861a]">Tip the creator</a>' % e(p["tip"]))
    if https(p.get("homepage")):
        links.append('<a href="%s" rel="noopener nofollow" class="underline font-bold hover:text-[#ea861a]">Homepage</a>' % e(p["homepage"]))
    links.append('<a href="/feed/%s.xml" class="underline font-bold hover:text-[#ea861a]">Follow updates</a>' % e(p["id"]))
    coll = collections.get(p.get("collection") or "")
    hist = []
    for v in p.get("versions", [])[:10]:
        notes = (v.get("notes") or "").strip()
        hist.append('<details class="bg-white/40 rounded-2xl p-4 border border-[#4b3621]/10"><summary class="cursor-pointer font-black">'
                    'v%s%s <span class="opacity-50 font-bold text-xs ml-2">%s%s</span></summary>%s</details>'
                    % (e(v["version"]), ' <span class="feature-tag tag-blue">beta</span>' if v.get("prerelease") else "",
                       e(date_text(v.get("updated"))), (" &middot; %s downloads" % format(v["downloads"], ",")) if v.get("downloads") else "",
                       '<p class="notes text-sm opacity-80 mt-3">%s</p>' % e(notes[:3000]) if notes else ""))
    bar = [cat["bar"].get(b, b) for b in p.get("bar_missing", [])]
    ph, pb = pitch(p)
    body = """
<main class="container mx-auto px-4 md:px-6 py-12 max-w-5xl">
  <p class="text-xs font-bold uppercase tracking-widest opacity-50 mb-4"><a href="/" class="hover:text-[#ea861a]">MPC Plugins</a> / {kind_label}s{coll_crumb}</p>
  <div class="flex flex-wrap gap-2 mb-4">{badges}</div>
  <h1 class="text-4xl md:text-7xl font-black tracking-tighter leading-none italic mb-3">{name}</h1>
  <p class="text-sm font-black uppercase tracking-[0.3em] text-[#ea861a] mb-8">by {maker} &middot; v{version} &middot; {date}{dl}</p>
  {formerly}
  {stats}
  {shot}
  <p class="text-lg font-medium leading-relaxed opacity-80 mb-4">{desc}</p>
  {about}
  <div class="flex flex-wrap gap-x-6 gap-y-2 text-sm mb-10">{links}</div>
  <h2 class="text-3xl font-black uppercase tracking-tighter mb-4">Download <span class="text-[#ea861a]">v{version}</span></h2>
  {status}
  {disclaimer}
  <div class="space-y-3 mb-4">{builds}</div>
  <p class="text-xs opacity-60 mb-4">Downloads come straight from the creator's GitHub. Check the sha256 matches before installing. New to plugins? <a href="/install/" class="underline font-bold">How to install plugins on MPC OS 3.10.1</a>.</p>
  {copy}
  {beta_note}
  <div class="mb-10"></div>
  {tested}
  <h2 class="text-3xl font-black uppercase tracking-tighter mb-4">Version <span class="text-[#ea861a]">history</span></h2>
  <div class="space-y-3 mb-10">{history}</div>
  {bar}
  <details class="mb-10 bg-white/60 rounded-2xl p-5 border border-[#4b3621]/10"><summary class="cursor-pointer font-black uppercase tracking-widest text-xs">Made this plugin? Add our badge to your README</summary>
    <p class="mt-3 text-sm opacity-80"><img src="/badge/{pid}.svg" alt="MPC Plugins badge" class="inline"> Paste this into your README. It updates itself when your plugin gets the Tested &amp; Working badge.</p>
    <pre class="bg-[#111] text-white/90 text-xs rounded-xl p-3 mt-3 overflow-x-auto">{snippet}</pre></details>
</main>
""".format(
        kind_label=e(KIND_LABEL.get(p["kind"], "Plugin")),
        coll_crumb=(' / <a href="/c/%s/" class="hover:text-[#ea861a]">%s</a>' % (e(coll["id"]), e(coll["title"]))) if coll else "",
        badges=badges(p), name=e(p["name"]), maker=e(p["maker"]), version=e(latest["version"]),
        date=e(date_text(latest.get("updated"))),
        dl=(" &middot; %s downloads" % format(p["downloads"], ",")) if p.get("downloads") else "",
        shot=('<div class="rounded-[2rem] overflow-hidden bg-black mb-8 border border-[#ea861a]/30 shadow-2xl"><img src="%s" alt="%s plugin screen on an Akai MPC" class="w-full max-h-[520px] object-contain" loading="lazy"></div>'
              % (e(shot), e(p["name"]))) if shot else "",
        desc=e(desc),
        about=('<p class="font-medium leading-relaxed opacity-70 mb-6">%s</p>' % e(p["about"])) if p.get("about") and p.get("about") != desc else "",
        links=" ".join(links),
        builds=('<p class="opacity-60">Download removed by our safety check.</p>' if p.get("blocked")
                else build_rows(latest) or '<p class="opacity-60">No download in this release.</p>'),
        status=status_box(p) + needs_box(p) + safety_box(p), disclaimer=DISCLAIMER, copy=copy_box(p),
        pid=e(p["id"]), snippet=e(badge_snippet(p)),
        stats='<div class="grid grid-cols-2 md:grid-cols-4 gap-3 -mt-4 mb-8">%s</div>' % "".join(
            '<div class="bg-white/60 border border-[#4b3621]/10 rounded-2xl p-4 text-center"><p class="text-2xl md:text-3xl font-black text-[#ea861a] leading-none">%s</p>'
            '<p class="text-[10px] font-black uppercase tracking-widest opacity-60 mt-2">%s</p></div>' % (e(v), e(l)) for v, l in (
                (format(p.get("downloads") or 0, ","), "Downloads"), (format(p.get("stars") or 0, ","), "GitHub stars"),
                ("v" + latest["version"], "Latest version"), (date_text(latest.get("updated")), "Updated"))),
        formerly=('<p class="text-sm font-bold opacity-70 -mt-6 mb-8">Formerly called %s. Same plugin, new name.</p>'
                  % e(", ".join(p["renamed_from"]))) if p.get("renamed_from") else "",
        beta_note=('<div class="bg-red-600 text-white rounded-2xl p-5 border-4 border-red-800"><p class="font-black uppercase tracking-tighter text-lg">'
                   '&#9888; Beta v%s is out: unfinished, not tested</p><p class="font-bold text-sm">Betas can crash or break projects. The download '
                   'above is the finished version. Get the beta from the creator\'s GitHub only if you accept that risk.</p></div>'
                   % e(p["beta"]["version"])) if p.get("beta") else "",
        tested=('<h2 class="text-3xl font-black uppercase tracking-tighter mb-4">Tested <span class="text-[#ea861a]">working</span> on</h2>'
                '<ul class="list-disc pl-6 mb-10 font-medium opacity-80">%s</ul>' % "".join(tested_lines)) if tested_lines else
               '<p class="mb-10 font-medium opacity-70">No hardware test recorded by the creator for this version yet.</p>',
        history="\n".join(hist),
        bar=('<details class="mb-10"><summary class="cursor-pointer font-black uppercase tracking-widest text-xs opacity-60">To improve this listing</summary>'
             '<ul class="list-disc pl-6 mt-3 text-sm opacity-70">%s</ul></details>' % "".join("<li>%s</li>" % e(b) for b in bar)) if bar else "",
    )
    return head + body + FOOT.format(pitch_head=ph, pitch_body=pb, store=STORE)


def collection_page(c, members):
    url = BASE + "c/%s/" % c["id"]
    kinds = {}
    for m in members:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    summary = "%s by %s: %d MPC plugins (%s)." % (c["title"], c["maker"], len(members),
                                                 ", ".join("%d %ss" % (n, k) for k, n in sorted(kinds.items())))
    shot = next((https(m.get("screenshot")) for m in members if https(m.get("screenshot"))), None)
    head = HEAD.format(title=e("%s by %s | MPC Plugins Manager" % (c["title"], c["maker"])), desc=e(summary), url=e(url),
                       canon=e(CANON + "collection/" + c["id"] + "/"),
                       og_image='<meta property="og:image" content="%s">' % e(shot) if shot else "",
                       card="summary_large_image" if shot else "summary", extra_head="")
    cards = []
    for m in sorted(members, key=lambda x: x["name"].lower()):
        cards.append('<a href="/p/%s/" class="bg-[#111] rounded-2xl border border-white/10 p-4 hover:border-[#ea861a] block">'
                     '<span class="feature-tag">%s</span><h3 class="text-lg font-black text-white italic mt-3">%s</h3>'
                     '<p class="text-white/60 text-xs mt-2">%s</p></a>'
                     % (e(m["id"]), e(KIND_LABEL.get(m["kind"], m["kind"])), e(m["name"]), e((m.get("description") or "")[:140])))
    body = """
<main class="container mx-auto px-4 md:px-6 py-12 max-w-6xl">
  <p class="text-xs font-bold uppercase tracking-widest opacity-50 mb-4"><a href="/" class="hover:text-[#ea861a]">MPC Plugins</a> / Collections</p>
  <span class="feature-tag tag-dark">Collection</span>
  <h1 class="text-4xl md:text-7xl font-black tracking-tighter leading-none italic mt-4 mb-3">{title}</h1>
  <p class="text-sm font-black uppercase tracking-[0.3em] text-[#ea861a] mb-8">by {maker} &middot; {n} plugins</p>
  <p class="text-lg font-medium opacity-80 mb-10">{summary}</p>
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">{cards}</div>
</main>
""".format(title=e(c["title"]), maker=e(c["maker"]), n=len(members), summary=e(summary), cards="\n".join(cards))
    return head + body + FOOT.format(pitch_head="Load the plugins. <span class=\"text-[#ea861a]\">Load the sounds.</span>",
                                     pitch_body="The Disk King's MPC Expansions give your MPC the drums and chops: boom bap, street and soul kits.",
                                     store=STORE)


BADGE_LOOK = {"verified": ("tested &amp; working", "#15803d"), "listed": ("listed", "#ea861a"),
              "experimental": ("beta", "#dc2626"), None: ("listed", "#ea861a")}


def badge_svg(right, color, left="MPC Plugins"):
    """A small README badge, drawn by hand (no outside service)."""
    plain = right.replace("&amp;", "&")
    lw, rw = 12 + 7 * len(left), 12 + 7 * len(plain)
    w = lw + rw
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="20" role="img" aria-label="%s: %s">'
            '<title>%s: %s</title><clipPath id="r"><rect width="%d" height="20" rx="4"/></clipPath><g clip-path="url(#r)">'
            '<rect width="%d" height="20" fill="#4b3621"/><rect x="%d" width="%d" height="20" fill="%s"/></g>'
            '<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" font-weight="bold" text-anchor="middle">'
            '<text x="%d" y="14">%s</text><text x="%d" y="14">%s</text></g></svg>'
            % (w, left, right, left, right, w, lw, lw, rw, color, lw // 2, left, lw + rw // 2, right))


def badge_snippet(p):
    return "[![MPC Plugins](%sbadge/%s.svg)](%s%s/)" % (BASE, p["id"], CANON, p["id"])


GUIDE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guide", "install.html")


def install_page():
    """The install guide. Same body as thediskking.com/plugins/install/ (canonical there)."""
    try:
        with open(GUIDE, encoding="utf-8") as f:
            body = f.read()
    except OSError:
        return None
    body = (body.replace('href="/plugins/"', 'href="/"')
                .replace('href="/policies.html', 'href="https://thediskking.com/policies.html'))
    head = HEAD.format(title=e("How to Install Plugins on Akai MPC OS 3.10.1: Full Step-by-Step Guide | MPC Plugins Manager"),
                       desc=e("How to install and load free plugins on the Akai MPC and Force with MPC OS 3.10.1: turn on External "
                              "Plugin Support, pick Gen1 or Gen2, copy to the VST2 Plugins folder, load it on a track."),
                       url=e(BASE + "install/"), canon=e(CANON + "install/"), og_image="", card="summary", extra_head="")
    main = """
<main class="container mx-auto px-4 md:px-6 py-12 max-w-4xl">
  <p class="text-xs font-bold uppercase tracking-widest opacity-50 mb-4"><a href="/" class="hover:text-[#ea861a]">MPC Plugins</a> / How to install</p>
  <span class="feature-tag">MPC OS 3.10.1 &middot; Step by step</span>
  <h1 class="text-4xl md:text-7xl font-black tracking-tighter leading-none mt-5 mb-4">HOW TO INSTALL <span class="text-[#ea861a]">MPC PLUGINS</span></h1>
  <p class="text-lg font-medium opacity-80 mb-10">The complete guide to installing and loading free plugins on your Akai MPC or Force with MPC OS 3.10.1: switch plugins on, pick the right download, copy it over, and play it on a track.</p>
  %s
  <div class="flex flex-wrap gap-3 mt-12">
    <a href="/" class="inline-flex h-[52px] items-center bg-green-700 text-white hover:bg-green-800 px-6 rounded-xl font-black text-sm uppercase tracking-widest shadow-lg">&#10003; Browse tested plugins</a>
    <a href="https://thediskking.com/plugins/submit/" class="inline-flex h-[52px] items-center border-2 border-dashed border-[#ea861a] text-[#ea861a] bg-white/60 hover:bg-[#ea861a] hover:text-white px-6 rounded-xl font-black text-sm uppercase tracking-widest">+ Submit your plugin</a>
  </div>
  <p class="text-xs opacity-50 mt-8">Last checked against Akai's MPC 3.10.1 release notes on November 18, 2026. Menu names can change in later updates.</p>
</main>
""" % body
    return head + main + FOOT.format(pitch_head="Load the plugins. <span class=\"text-[#ea861a]\">Load the sounds.</span>",
                                     pitch_body="The Disk King's MPC Expansions give your MPC the drums and chops: boom bap, street and soul kits.",
                                     store=STORE)


def atom(title, self_url, entries, updated):
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>%s</title>" % e(title), '<link rel="self" href="%s"/>' % e(self_url), '<link href="%s"/>' % e(BASE),
           "<id>%s</id>" % e(self_url), "<updated>%s</updated>" % e(updated), "<author><name>MPC Plugins Manager</name></author>"]
    for p, v in entries:
        link = BASE + "p/%s/" % p["id"]
        out.append("<entry><title>%s</title><id>%s</id><updated>%s</updated><link href=\"%s\"/>"
                   "<author><name>%s</name></author><summary>%s</summary></entry>"
                   % (e("%s %s%s" % (p["name"], v["version"], " (beta)" if v.get("prerelease") else "")),
                      e("tag:mpcplugins.github.io,2026:%s@%s" % (p["id"], v["version"])), e(v.get("updated") or updated),
                      e(link), e(p["maker"]), e(((v.get("notes") or "").strip() or p.get("description") or "")[:600])))
    out.append("</feed>")
    return "\n".join(out)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


TSV_COLUMNS = ["id", "name", "maker", "kind", "tier", "version", "tested_on", "downloads", "user_files", "summary",
               "style", "screenshot", "updated", "featured", "notes", "history", "needs", "rating", "rating_count"]
for _k in ("sdk", "gen1", "gen2"):
    TSV_COLUMNS += [_k + "_url", _k + "_sha256", _k + "_size", _k + "_folder", _k + "_inside", _k + "_copy_ok"]


def catalog_tsv(cat):
    """The plugin list for MPC Plugins Manager on the MPC: one plain line per plugin, Tested & Working first.
    A tab-separated file is quick to read with very little code on the device. Line 1 says the format version."""
    def clean(v, limit=300):
        return " ".join(str(v if v is not None else "").split())[:limit]

    def notes(p):            # the newest stable version's release notes, without Markdown symbols
        v = next((v for v in p.get("versions") or [] if not v.get("prerelease")), None)
        text = (v or {}).get("notes") or ""
        for ch in "#*`>_":
            text = text.replace(ch, "")
        return clean(text, 600)

    def history(p):          # up to 6 versions: version|date|downloads;...
        return ";".join("%s|%s|%d" % (v["version"], (v.get("updated") or "")[:10], v.get("downloads") or 0)
                        for v in (p.get("versions") or [])[:6])
    rows = ["#mpcplugins-tsv\t1\t%s" % cat.get("generated", ""), "\t".join(TSV_COLUMNS)]
    order = sorted(cat["plugins"], key=lambda p: (p.get("featured") or 999, p.get("tier") != "verified", -(p.get("downloads") or 0), p["name"].lower()))
    for p in order:
        if p.get("blocked"):
            continue
        b = (p.get("latest") or {}).get("builds") or {}
        copy = (p.get("safety") or {}).get("copy") or {}
        cells = [p["id"], p["name"], p.get("maker", ""), p.get("kind", ""), p.get("tier", ""),
                 (p.get("latest") or {}).get("version", ""), ",".join(p.get("verified_on") or []), p.get("downloads") or 0,
                 ";".join(p.get("user_files") or []), p.get("description") or p.get("about") or "",
                 p.get("style") or "", https(p.get("screenshot")) or "", ((p.get("latest") or {}).get("updated") or "")[:10],
                 p.get("featured") or 0, notes(p), history(p), p.get("needs") or "",
                 (p.get("rating") or {}).get("avg") or "", (p.get("rating") or {}).get("count") or 0]
        for k in ("sdk", "gen1", "gen2"):
            x, c = b.get(k) or {}, copy.get(k) or {}
            cells += [x.get("url", ""), x.get("sha256") or "", x.get("size") or "", c.get("folder") or "",
                      c.get("inside") or "", 1 if c.get("ok") else 0]
        rows.append("\t".join(clean(v, 600) for v in cells))
    return "\n".join(rows) + "\n"


def write(cat, out, log=print):
    plugins = cat["plugins"]
    collections = {c["id"]: c for c in cat.get("collections", [])}
    by_id = {p["id"]: p for p in plugins}
    now = cat.get("generated") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for p in plugins:
        _write(os.path.join(out, "p", p["id"], "index.html"), plugin_page(p, cat, collections))
        _write(os.path.join(out, "feed", p["id"] + ".xml"),
               atom("%s updates | MPC Plugins Manager" % p["name"], BASE + "feed/%s.xml" % p["id"],
                    [(p, v) for v in p.get("versions", [])[:30]], now))
    for p in plugins:              # a renamed plugin's old page address sends people to its page
        for old in p.get("old_ids", []):
            if old not in by_id:
                target = "/p/%s/" % p["id"]
                _write(os.path.join(out, "p", old, "index.html"),
                       '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>%s</title>'
                       '<link rel="canonical" href="%s%s/"><meta http-equiv="refresh" content="0; url=%s"></head>'
                       '<body><p>%s has a new name: <a href="%s">%s</a>.</p></body></html>'
                       % (e(p["name"]), CANON, e(p["id"]), target, e(old), target, e(p["name"])))
    for c in collections.values():
        _write(os.path.join(out, "c", c["id"], "index.html"),
               collection_page(c, [by_id[m] for m in c["members"] if m in by_id]))
    for p in plugins:
        _write(os.path.join(out, "badge", p["id"] + ".svg"), badge_svg(*BADGE_LOOK.get(p.get("tier"), BADGE_LOOK[None])))
    _write(os.path.join(out, "badge.svg"), badge_svg("listed", "#ea861a"))
    guide = install_page()
    if guide:
        _write(os.path.join(out, "install", "index.html"), guide)
    recent = sorted(((p, v) for p in plugins for v in p.get("versions", [])),
                    key=lambda pv: pv[1].get("updated") or "", reverse=True)[:50]
    _write(os.path.join(out, "catalog.tsv"), catalog_tsv(cat))
    _write(os.path.join(out, "feed.xml"), atom("MPC Plugins Manager: new releases", BASE + "feed.xml", recent, now))
    urls = [BASE]      # plugin pages are canonical on thediskking.com, whose own sitemap lists them
    _write(os.path.join(out, "sitemap.xml"),
           '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join("  <url><loc>%s</loc><lastmod>%s</lastmod></url>" % (e(u), now[:10]) for u in urls) + "\n</urlset>\n")
    _write(os.path.join(out, "robots.txt"), "User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % BASE)
    log("   %d plugin pages, %d collection pages, %d feeds, sitemap" % (len(plugins), len(collections), len(plugins) + 1))
