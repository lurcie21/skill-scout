#!/usr/bin/env python
"""GitHub skill search - compact output, low token cost.

Modes (pick one):
  --topic  TOPIC           repos carrying a GitHub topic        (e.g. agent-skills)
  --repo-query QUERY       raw GitHub repository search query
  --code QUERY             GitHub CODE search (needs GH_TOKEN); best way to
                           find real skills: --code 'path:SKILL.md pdf'
  --skill-of OWNER/REPO    inspect one repo: SKILL.md paths, license, size

Common options:
  --limit N        how many rows (default 8)
  --sort KEY       stars (default) | updated | forks
  --min-stars N    drop rows below N stars
  --check-skill    ask the trees API whether each repo really ships SKILL.md
                   (costs 1 request per repo, capped at 8)
  --json           machine-readable output instead of a table

Auth: set GH_TOKEN (or GITHUB_TOKEN) to raise rate limits and enable --code.
"""
import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "dsh-skill-scout"


def token():
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _ctx():
    try:
        import certifi  # noqa: F401
        return ssl.create_default_context()
    except Exception:
        pass
    return ssl.create_default_context()


def get(url, timeout=30):
    """GET with a one-shot fallback to unverified TLS (this box's cert chain)."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if token():
        headers["Authorization"] = "Bearer " + token()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            body = r.read()
            return json.loads(body.decode("utf-8")), dict(r.headers)
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise SystemExit("HTTP %s %s\n%s" % (e.code, url, detail))
    except (ssl.SSLError, urllib.error.URLError) as e:
        if "CERTIFICATE" not in str(e).upper() and "SSL" not in str(e).upper():
            raise SystemExit("network error: %s" % e)
        insecure = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=insecure) as r:
            body = r.read()
            return json.loads(body.decode("utf-8")), dict(r.headers)


def age_days(iso):
    if not iso:
        return "-"
    t = dt.datetime.strptime(iso[:10], "%Y-%m-%d")
    return "%dd" % max(0, (dt.date.today() - t.date()).days)


def lic(repo):
    return ((repo.get("license") or {}).get("spdx_id") or "-")


def skills_in_repo(full_name, branch):
    tree, _ = get("%s/repos/%s/git/trees/%s?recursive=1" % (API, full_name, branch))
    paths = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob"
             and e["path"].split("/")[-1].lower() == "skill.md"]
    return paths


def print_table(rows, with_skill):
    head = "%-44s %8s %-13s %5s %s" % ("repo", "stars", "license", "pushed", "desc")
    if with_skill:
        head += "  skill.md"
    print(head)
    print("-" * len(head))
    for r in rows:
        line = "%-44s %8d %-13s %5s %s" % (
            r["repo"][:44], r["stars"], r["license"][:13], r["pushed"], r["desc"][:58])
        if with_skill:
            line += "  " + ("yes(%d)" % r["skill_count"] if r.get("skill_count") else "NO")
        print(line)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--topic")
    g.add_argument("--repo-query")
    g.add_argument("--code")
    g.add_argument("--skill-of")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--sort", default="stars", choices=["stars", "updated", "forks"])
    ap.add_argument("--min-stars", type=int, default=0)
    ap.add_argument("--check-skill", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    # --- single repo inspection -------------------------------------------------
    if a.skill_of:
        r, _ = get("%s/repos/%s" % (API, a.skill_of))
        branch = r.get("default_branch") or "main"
        paths = skills_in_repo(a.skill_of, branch)
        out = {
            "repo": r["full_name"], "stars": r["stargazers_count"], "license": lic(r),
            "default_branch": branch, "pushed": age_days(r.get("pushed_at")),
            "size_kb": r.get("size"), "skill_md": paths, "skill_count": len(paths),
            "archive": "https://codeload.github.com/%s/tar.gz/refs/heads/%s" % (r["full_name"], branch),
        }
        if a.json:
            print(json.dumps(out, indent=2))
        else:
            print("repo      : %s" % out["repo"])
            print("stars     : %d" % out["stars"])
            print("license   : %s" % out["license"])
            print("branch    : %s   (last push %s, repo %s KB)" % (branch, out["pushed"], out["size_kb"]))
            print("skill.md  : %d" % out["skill_count"])
            for p in paths[:20]:
                print("            " + p)
            print("archive   : %s" % out["archive"])
        return

    # --- code search ------------------------------------------------------------
    if a.code:
        if not token():
            raise SystemExit(
                "code search requires GH_TOKEN.\n"
                "  set it:  setx GH_TOKEN <token>   (then reopen the shell)\n"
                "  or search in the browser while signed in:\n"
                "  https://github.com/search?q=%s&type=code" % urllib.parse.quote(a.code))
        data, hdr = get("%s/search/code?per_page=%d&q=%s" % (API, a.limit, urllib.parse.quote(a.code)))
        for it in data.get("items", []):
            print("%-52s %s" % (it["repository"]["full_name"], it["path"]))
        print("total: %s   remaining: %s" % (data.get("total_count"), hdr.get("X-RateLimit-Remaining", "?")))
        return

    # --- repo search ------------------------------------------------------------
    if a.topic:
        q = "topic:" + a.topic
    else:
        q = a.repo_query
    url = "%s/search/repositories?q=%s&sort=%s&order=desc&per_page=%d" % (
        API, urllib.parse.quote(q), a.sort, min(a.limit * 2, 50))
    data, hdr = get(url)

    rows = []
    for r in data.get("items", []):
        if r["stargazers_count"] < a.min_stars:
            continue
        rows.append({
            "repo": r["full_name"], "stars": r["stargazers_count"], "license": lic(r),
            "pushed": age_days(r.get("pushed_at")),
            "desc": re.sub(r"\s+", " ", r.get("description") or ""),
            "branch": r.get("default_branch") or "main",
            "archived": bool(r.get("archived")),
        })
        if len(rows) >= a.limit:
            break

    if a.check_skill:
        for r in rows[:8]:
            try:
                r["skill_count"] = len(skills_in_repo(r["repo"], r["branch"]))
            except SystemExit:
                r["skill_count"] = None

    if a.json:
        print(json.dumps({"query": q, "rows": rows}, indent=2, ensure_ascii=False))
        return

    print("query: %s   (sort=%s, shown=%d, remaining ratelimit=%s)\n" % (
        q, a.sort, len(rows), hdr.get("X-RateLimit-Remaining", "?")))
    print_table(rows, a.check_skill)
    print("\nnext: inspect one with  --skill-of <owner/repo>")
    print("      review  it with    install.py <owner/repo>          (downloads + scans, copies nothing)")
    print("      install it with    install.py <owner/repo> --apply")


if __name__ == "__main__":
    main()