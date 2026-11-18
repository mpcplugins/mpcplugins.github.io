"""Safety check of a plugin's release zip. Our own code: zip + ELF reading with the standard library only.

For each download file (checked once, remembered by its sha256):
  - the file's sha256 matches what GitHub lists
  - the zip opens; what's in it (plugin library, skin, metadata, installer)
  - every ELF library inside: CPU (32-bit ARM for Gen1, 64-bit ARM for Gen2), newest glibc it needs
    (decides which MPC OS can load it), libraries it links, functions it imports
  - risky imports: network, running programs, loading code at runtime, system changes
  - installer script lines that do risky things
It is a careful look, not a guarantee: a determined author can hide behavior.
"""
import hashlib
import io
import re
import struct
import zipfile

from .net import fetch

MAX_ZIP = 300 * 1024 * 1024          # skip anything bigger than 300 MB

EM_ARM, EM_AARCH64 = 40, 183
SHT_DYNAMIC, SHT_DYNSYM, SHT_VERNEED = 6, 11, 0x6FFFFFFE
DT_NEEDED = 1

RISKY = {
    "network": {"socket", "connect", "bind", "listen", "accept", "accept4", "getaddrinfo", "gethostbyname", "sendto",
                "recvfrom", "curl_easy_init", "curl_easy_perform", "SSL_connect", "inet_pton"},
    "runs programs": {"system", "popen", "execv", "execve", "execvp", "execl", "execlp", "execle", "fork", "vfork",
                      "posix_spawn", "posix_spawnp", "daemon"},
    "loads code": {"dlopen", "dlmopen"},
    "system changes": {"mount", "umount", "umount2", "reboot", "setuid", "setgid", "seteuid", "chroot", "ptrace",
                       "init_module", "delete_module", "sethostname", "settimeofday", "swapon", "kill"},
}
INSTALLER_RISK = [
    ("deletes outside its folder", re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|/\*|/usr|/etc|/bin|/lib|/data\b|\$HOME|~)(\s|$)")),
    ("downloads and runs code", re.compile(r"(curl|wget)[^\n|]*\|\s*(ba|da)?sh\b")),
    ("downloads files", re.compile(r"\b(curl|wget)\s")),
    ("writes disks", re.compile(r"\b(dd\s+if=|mkfs\.|fdisk|parted)\b")),
    ("changes passwords or SSH keys", re.compile(r"\b(passwd|chpasswd|authorized_keys)\b")),
    ("adds services or startup jobs", re.compile(r"\b(systemctl\s+(enable|mask)|crontab|/etc/init\.d|rc\.local)\b")),
    ("remounts system read-write", re.compile(r"mount\s+-o\s*[^\n]*\brw\b")),
    ("opens permissions wide", re.compile(r"chmod\s+(-R\s+)?777\b")),
]


def _glibc_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def read_elf(data):
    """Facts about one ELF file, or None if it isn't ELF."""
    if len(data) < 64 or data[:4] != b"\x7fELF":
        return None
    is64 = data[4] == 2
    end = "<" if data[5] == 1 else ">"
    machine = struct.unpack_from(end + "H", data, 18)[0]
    try:
        if is64:
            shoff = struct.unpack_from(end + "Q", data, 0x28)[0]
            shentsize, shnum = struct.unpack_from(end + "HH", data, 0x3A)
        else:
            shoff = struct.unpack_from(end + "I", data, 0x20)[0]
            shentsize, shnum = struct.unpack_from(end + "HH", data, 0x2E)
        sections = []
        for i in range(shnum):
            off = shoff + i * shentsize
            if is64:
                name, typ, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(end + "IIQQQQIIQQ", data, off)
            else:
                name, typ, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(end + "IIIIIIIIII", data, off)
            sections.append((typ, offset, size, link, entsize))
    except struct.error:
        return {"machine": machine, "bits": 64 if is64 else 32, "broken": True}

    def cstr(table, pos):
        typ, offset, size, link, entsize = sections[table]
        start = offset + pos
        stop = data.find(b"\0", start, offset + size)
        return data[start:stop if stop >= 0 else offset + size].decode("utf-8", "replace")

    imports, exports, needed, glibc = set(), set(), [], []
    for typ, offset, size, link, entsize in sections:
        if link >= len(sections):
            continue
        if typ == SHT_DYNSYM:
            step = 24 if is64 else 16
            for p in range(offset + step, offset + size, step):       # entry 0 is the null symbol
                try:
                    if is64:
                        st_name, st_info, st_other, st_shndx = struct.unpack_from(end + "IBBH", data, p)
                    else:
                        st_name, = struct.unpack_from(end + "I", data, p)
                        st_info, st_other, st_shndx = struct.unpack_from(end + "BBH", data, p + 12)
                except struct.error:
                    break
                nm = cstr(link, st_name)
                if not nm:
                    continue
                if st_shndx == 0:
                    imports.add(nm.split("@")[0])
                elif (st_info >> 4) in (1, 2) and (st_info & 0xF) == 2:   # global/weak functions
                    exports.add(nm)
        elif typ == SHT_DYNAMIC:
            step = 16 if is64 else 8
            for p in range(offset, offset + size, step):
                tag, val = struct.unpack_from(end + ("qQ" if is64 else "iI"), data, p)
                if tag == 0:
                    break
                if tag == DT_NEEDED:
                    needed.append(cstr(link, val))
        elif typ == SHT_VERNEED:
            p = offset
            for _ in range(256):
                try:
                    vn_version, vn_cnt, vn_file, vn_aux, vn_next = struct.unpack_from(end + "HHIII", data, p)
                except struct.error:
                    break
                a = p + vn_aux
                for _ in range(vn_cnt):
                    vna_hash, vna_flags, vna_other, vna_name, vna_next = struct.unpack_from(end + "IHHII", data, a)
                    v = cstr(link, vna_name)
                    if v.startswith("GLIBC_"):
                        glibc.append(v[6:])
                    if not vna_next:
                        break
                    a += vna_next
                if not vn_next:
                    break
                p += vn_next
    risky = sorted(cat for cat, names in RISKY.items() if imports & names)
    if risky == ["loads code"]:
        risky = []                    # dlopen alone is normal for C++ toolchains; it only counts next to other flags
    return {
        "machine": machine,
        "bits": 64 if is64 else 32,
        "chains": bool(imports & {"dlsym", "dlvsym"}),   # passes hooked calls on (matters for addins)
        "glibc": max(glibc, key=_glibc_key) if glibc else None,
        "needed": needed,
        "risky": risky,
        "risky_calls": sorted(set().union(*[imports & RISKY[c] for c in risky])) if risky else [],
        "exports": sorted(exports)[:400],
    }


def os_support(kind, glibc):
    """Which MPC OS can load a library needing this glibc (facts from MPC OS releases)."""
    if not glibc:
        return "any"
    g = _glibc_key(glibc)
    if kind == "gen2":
        return "too new for MPC OS" if g > (2, 39) else "MPC OS 3.x"
    if g > (2, 36):
        return "too new for MPC OS"
    return "MPC OS 3.x only" if g > (2, 32) else "MPC OS 2.x and 3.x"


def check_zip(url, sha256, kind):
    """Download one release file and check it. Returns a result dict (never raises)."""
    res = {"sha256": sha256, "kind": kind, "problems": [], "warnings": []}
    status, body, _ = fetch(url, timeout=180, tries=3)
    if status != 200 or not body:
        res["problems"].append("download failed (HTTP %s)" % status)
        return res
    if len(body) > MAX_ZIP:
        res["warnings"].append("file over 300 MB, not inspected")
        return res
    actual = hashlib.sha256(body).hexdigest()
    res["size"] = len(body)
    if sha256 and actual != sha256:
        res["problems"].append("checksum does not match GitHub's listing")
    res["sha256"] = actual
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        res["problems"].append("not a valid zip file")
        return res
    names = [n for n in z.namelist() if not n.endswith("/")]
    res["files"] = len(names)
    low = [n.lower() for n in names]
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        res["problems"].append("zip contains paths that escape its folder")
    libs, inst_flags = [], set()
    for n in names:
        nl = n.lower()
        info = z.getinfo(n)
        if nl.endswith(".so") or ".so." in nl or info.file_size > 4096 and nl.split("/")[-1].find(".") < 0:
            data = z.read(n)
            elf = read_elf(data)
            if elf:
                elf["file"] = n
                libs.append(elf)
        if nl.endswith(".sh") or nl.split("/")[-1] in ("install", "uninstall"):
            text = z.read(n).decode("utf-8", "replace")
            for label, rx in INSTALLER_RISK:
                if rx.search(text):
                    inst_flags.add(label)
    want_machine = {"gen1": EM_ARM, "gen2": EM_AARCH64}.get(kind)
    plugin_libs = [l for l in libs if l["machine"] in (EM_ARM, EM_AARCH64)]
    if not plugin_libs:
        res["problems"].append("no MPC plugin library (ARM .so) found inside")
    if want_machine and plugin_libs and not any(l["machine"] == want_machine for l in plugin_libs):
        res["problems"].append("built for the wrong MPC: expected %s" % ("32-bit ARM (Gen1)" if kind == "gen1" else "64-bit ARM (Gen2)"))
    if any(l.get("broken") for l in libs):
        res["warnings"].append("a library inside could not be fully read")
    newest = max((l["glibc"] for l in plugin_libs if l.get("glibc")), key=_glibc_key, default=None)
    res["glibc"] = newest
    res["os"] = os_support("gen2" if kind == "gen2" else "gen1", newest)
    if res["os"] == "too new for MPC OS":
        res["problems"].append("needs a newer system library (glibc %s) than MPC OS has" % newest)
    res["risky"] = sorted({c for l in plugin_libs for c in l.get("risky", [])})
    res["risky_calls"] = sorted({c for l in plugin_libs for c in l.get("risky_calls", [])})
    res["installer_flags"] = sorted(inst_flags)
    res["has_skin"] = any("skin" in n or n.endswith("tui.json") for n in low)
    res["has_meta"] = any(n.endswith(("plugin-meta.xml", "plugin.json", "mpc-plugin.json", "version.xml")) for n in low)
    res["has_installer"] = any(n.endswith("install.sh") for n in low)
    res["libraries"] = [{"file": l["file"], "cpu": "arm64" if l["machine"] == EM_AARCH64 else ("arm32" if l["machine"] == EM_ARM else str(l["machine"])),
                         "glibc": l.get("glibc"), "links": l.get("needed", [])[:20]} for l in libs][:12]
    res["exports"] = sorted({x for l in plugin_libs for x in l.get("exports", [])})[:400]
    res["chains"] = any(l.get("chains") for l in plugin_libs)
    res["so_names"] = sorted({l["file"].rsplit("/", 1)[-1] for l in plugin_libs})
    res["ok"] = not res["problems"]
    return res
