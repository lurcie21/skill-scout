#!/usr/bin/env python
"""Fetch, scan and (optionally) install one GitHub skill repo.

Default behaviour = REVIEW ONLY. It downloads the tarball, extracts it into a
staging dir, scans it, prints what it found and STOPS. Nothing reaches your
skills directory until you pass --apply.

  python install.py owner/repo                 # review: download + scan + report
  python install.py owner/repo --apply         # copy the whitelisted files
  python install.py --from _staging/x-main     # reuse an earlier extraction
  python install.py owner/repo --apply --name my-skill --dest "%USERPROFILE%/.agents/skills"

It never runs code from the repo. Copy step is a whitelist, not a mirror.
"""
import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import ssl
import sys
import tarfile
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "dsh-skill-scout"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEST = os.path.join(os.path.expanduser("~"), ".agents", "skills")

# copied when --apply is used (paths relative to the repo root)
INCLUDE_FILES = ["SKILL.md", "License", "LICENSE", "LICENSE.md", "LICENSE.txt",
                 "NOTICE", "NOTICE.md", "pyproject.toml", "requirements.txt"]
INCLUDE_DIRS = ["scripts", "references", "assets", "templates", "bin"]
EXCLUDE_ANY = [".git", ".github", "node_modules", "__pycache__", ".venv", "venv",
               ".mypy_cache", ".pytest_cache", ".DS_Store", ".idea", ".vscode"]
EXCLUDE_DIR_NAMES = ["tests", "test", "evals", "eval", "docs", "doc"]

# (regex, severity, why)
RULES = [
    (r"curl\s+[^\n|]{0,200}\|\s*(ba)?sh",            "HIGH", "pipe-to-shell"),
    (r"wget\s+[^\n|]{0,200}\|\s*(ba)?sh",            "HIGH", "pipe-to-shell"),
    (r"Invoke-Expression|\biex\b",                   "HIGH", "powershell exec of string"),
    (r"Invoke-WebRequest[^\n]{0,120}\|\s*Invoke",    "HIGH", "download-and-run"),
    (r"\beval\s*\(\s*(?:input|sys\.stdin|requests)", "HIGH", "eval of remote input"),
    (r"\bexec\s*\(\s*(?:base64|decode|compile)",     "HIGH", "exec of decoded blob"),
    (r"os\.system\s*\(|subprocess\.(?:run|call|Popen)", "MED", "shells out"),
    (r"\brm\s+-rf\s+/",                              "HIGH", "destructive delete"),
    (r"base64\s+-d[^\n]{0,80}\|\s*(ba)?sh",          "HIGH", "obfuscated payload"),
    (r"\burlopen\s*\(|\brequests\.(?:get|post)\s*\(", "MED", "network call"),
    (r"\bchmod\s+(?:\+x|777)",                       "LOW", "makes files executable"),
    (r"\bpip\s+install\b|\bnpm\s+(?:i|install)\b",   "LOW", "installs deps"),
    (r"keyring|api_key|API_KEY|SECRET",              "LOW", "credentials mentioned"),
]
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip",
              ".gz", ".tgz", ".mp4", ".mp3", ".wav", ".woff", ".woff2", ".ttf",
              ".onnx", ".pt", ".bin", ".exe", ".dll", ".so", ".dylib"}


def token():
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def ssl_ctx():
    return ssl.create_default_context()


def get_json(url):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if token():
        headers["Authorization"] = "Bearer " + token()
    req = urllib.request.Request(url, headers=headers)
    for ctx in (ssl_ctx(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except ssl.SSLError:
            continue
        except Exception as e:
            raise SystemExit("API error: %s" % e)
    raise SystemExit("TLS failed for " + url)


def download(url, dest):
    headers = {"User-Agent": UA}
    if token():
        headers["Authorization"] = "Bearer " + token()
    req = urllib.request.Request(url, headers=headers)
    for ctx in (ssl_ctx(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=120, context=ctx) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return os.path.getsize(dest)
        except ssl.SSLError:
            continue
    raise SystemExit("download failed: " + url)


def safe_extract(tar, path):
    path = os.path.abspath(path)
    for m in tar.getmembers():
        target = os.path.abspath(os.path.join(path, m.name))
        if not (target == path or target.startswith(path + os.sep)):
            raise SystemExit("unsafe path in tarball: " + m.name)
        if m.issym() or m.islnk():
            continue
    try:
        tar.extractall(path, filter="data")   # py3.12+: refuse links, devices, odd modes
    except TypeError:
        tar.extractall(path)


def walk(root):
    files = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_ANY]
        for n in names:
            p = os.path.join(base, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                files.append((rel, os.path.getsize(p)))
            except OSError:
                pass
    return files


def scan(root, files):
    hits = []
    for rel, size in files:
        ext = os.path.splitext(rel)[1].lower()
        if ext in BINARY_EXT or size > 900_000:
            continue
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for pat, sev, why in RULES:
                if re.search(pat, line):
                    hits.append({"file": rel, "line": i, "severity": sev, "why": why,
                                 "text": line.strip()[:160]})
                    break
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    hits.sort(key=lambda h: (order[h["severity"]], h["file"], h["line"]))
    return hits


def frontmatter(root):
    p = os.path.join(root, "SKILL.md")
    if not os.path.isfile(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    name = re.search(r"(?m)^name:\s*(.+)$", text)
    desc = re.search(r"(?m)^description:\s*(.+)$", text)
    body = len(text.splitlines())
    return {
        "name": (name.group(1).strip() if name else ""),
        "description": (desc.group(1).strip() if desc else ""),
        "description_chars": len(desc.group(1).strip()) if desc else 0,
        "bytes": len(text.encode("utf-8")),
        "lines": body,
    }


def pick(root, files):
    """Return (chosen, skipped) lists of relative paths per the whitelist."""
    chosen, skipped = [], []
    for rel, size in files:
        parts = rel.split("/")
        if any(p in EXCLUDE_ANY for p in parts):
            skipped.append(rel)
            continue
        if len(parts) > 1 and parts[0] in EXCLUDE_DIR_NAMES:
            skipped.append(rel)          # tests/ docs/ evals/ ...
            continue
        keep = False
        if "/" not in rel:
            keep = any(fnmatch.fnmatch(rel, pat) for pat in INCLUDE_FILES)
        else:
            keep = parts[0] in INCLUDE_DIRS
        (chosen if keep else skipped).append(rel)
    return chosen, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", help="owner/repo")
    ap.add_argument("--from", dest="from_dir", help="reuse an already extracted tree")
    ap.add_argument("--branch", help="branch to fetch (default: repo default branch)")
    ap.add_argument("--name", help="target skill folder name (default: repo name)")
    ap.add_argument("--skill", help="for collection repos: which sub-folder to install")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--apply", action="store_true", help="actually copy the whitelist")
    ap.add_argument("--force", action="store_true", help="overwrite existing target, ignore HIGH findings")
    ap.add_argument("--staging", default=os.path.join(HERE, "_staging"))
    a = ap.parse_args()

    if not a.repo and not a.from_dir:
        raise SystemExit("need a repo (owner/repo) or --from <dir>")

    if a.from_dir:
        root = os.path.abspath(a.from_dir)
        repo_full = os.path.basename(root)
        meta = {}
        print("[1/4] using existing tree: %s" % root)
    else:
        repo_full = a.repo.strip().strip("/")
        meta = get_json("%s/repos/%s" % (API, repo_full))
        branch = a.branch or meta.get("default_branch") or "main"
        url = "https://codeload.github.com/%s/tar.gz/refs/heads/%s" % (repo_full, branch)
        os.makedirs(a.staging, exist_ok=True)
        tgz = os.path.join(a.staging, "%s-%s.tar.gz" % (repo_full.replace("/", "__"), branch))
        print("[1/4] %s  branch=%s  license=%s  pushed=%s" % (
            repo_full, branch, (meta.get("license") or {}).get("spdx_id", "-"),
            (meta.get("pushed_at") or "")[:10]))
        size = download(url, tgz)
        print("      downloaded %d KB -> %s" % (size // 1024, tgz))
        root = os.path.join(a.staging, "%s-%s" % (repo_full.replace("/", "__"), branch))
        if os.path.isdir(root):
            shutil.rmtree(root)
        with tarfile.open(tgz, "r:gz") as tar:
            safe_extract(tar, root)
        inner = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        if len(inner) == 1 and not os.path.isfile(os.path.join(root, "SKILL.md")):
            root = os.path.join(root, inner[0])

    # collection repos: the root has no SKILL.md, each skill lives in its own folder
    if not os.path.isfile(os.path.join(root, "SKILL.md")):
        subs = sorted(d for d in os.listdir(root)
                      if os.path.isdir(os.path.join(root, d))
                      and os.path.isfile(os.path.join(root, d, "SKILL.md")))
        if a.skill:
            if a.skill not in subs:
                raise SystemExit("no such skill %r\nfound: %s" % (a.skill, ", ".join(subs) or "none"))
            root = os.path.join(root, a.skill)
        elif len(subs) == 1:
            root = os.path.join(root, subs[0])
        elif subs:
            print("[!] collection repo: %d skills, no SKILL.md at the top" % len(subs))
            for s in subs:
                print("        " + s)
            raise SystemExit("pick one:  --skill <name>       (browse: %s)" % root)

    files = walk(root)
    total = sum(s for _, s in files)
    fm = frontmatter(root)
    print("[2/4] tree: %d files, %d KB" % (len(files), total // 1024))
    for rel, size in sorted(files, key=lambda x: -x[1])[:12]:
        print("        %7d KB  %s" % (max(1, size // 1024), rel))
    if fm:
        warn = "  <-- over budget" if fm["description_chars"] > 400 else ""
        print("      SKILL.md: name=%r  desc=%d chars%s  (%d lines, %d B)" % (
            fm["name"], fm["description_chars"], warn, fm["lines"], fm["bytes"]))
    else:
        print("      !! no SKILL.md at repo root - this may not be a skill at all")

    hits = scan(root, files)
    high = [h for h in hits if h["severity"] == "HIGH"]
    print("[3/4] scan: %d findings (HIGH=%d MED=%d LOW=%d)" % (
        len(hits), len(high), len([h for h in hits if h["severity"] == "MED"]),
        len([h for h in hits if h["severity"] == "LOW"])))
    for h in hits[:25]:
        print("        %-4s %s:%d  %s" % (h["severity"], h["file"], h["line"], h["why"]))
        print("             | %s" % h["text"])
    if len(hits) > 25:
        print("        ... %d more" % (len(hits) - 25))

    chosen, skipped = pick(root, files)
    name = a.name or (fm["name"] if fm and fm.get("name")
                      else re.sub(r"-(main|master)$", "", os.path.basename(root)))
    target = os.path.join(os.path.expanduser(a.dest), name)
    print("[4/4] whitelist: copy %d files (%d KB), skip %d" % (
        len(chosen), sum(s for r, s in files if r in set(chosen)) // 1024, len(skipped)))
    print("      target: %s" % target)

    report = {
        "repo": repo_full, "time": dt.datetime.now().isoformat(timespec="seconds"),
        "license": (meta.get("license") or {}).get("spdx_id", "-"),
        "pushed_at": meta.get("pushed_at"), "stars": meta.get("stargazers_count"),
        "root": root, "files": len(files), "kb": total // 1024,
        "frontmatter": fm, "findings": hits,
        "copy": chosen, "skipped": skipped, "target": target, "applied": False,
    }

    if not a.apply:
        print("\n      REVIEW ONLY. Nothing was copied.")
        print("      run again with --apply to install, or inspect: %s" % root)
    else:
        if os.path.isdir(target) and not a.force:
            raise SystemExit("target exists, refusing to overwrite: %s  (use --force)" % target)
        if high and not a.force:
            raise SystemExit("HIGH findings present, refusing to copy without --force")
        os.makedirs(target, exist_ok=True)
        for rel in chosen:
            src = os.path.join(root, rel)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        report["applied"] = True
        print("\n      INSTALLED %d files -> %s" % (len(chosen), target))
        print("      next: smoke-test it with a real file, then append an 'On this machine' section")

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    rp = os.path.join(HERE, "reports", "%s__%s-%s.json" % (
        repo_full.replace("/", "__"), os.path.basename(target),
        dt.datetime.now().strftime("%Y%m%d-%H%M%S")))
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("      report: %s" % rp)


if __name__ == "__main__":
    main()