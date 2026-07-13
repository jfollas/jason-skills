#!/usr/bin/env python3
"""
clockify_log.py — derive Clockify time entries from Claude Code session transcripts.

Mines ~/.claude/projects/<repo>/*.jsonl, groups each session, computes active
time (idle gaps > GAP minutes removed), extracts GitHub PR/issue references,
generates a description, rounds to 15 min, caps autonomous-inflated sessions,
and either previews (default) or POSTs the entries to Clockify.

Usage:
  python3 clockify_log.py                      # dry-run preview, last 7 days
  python3 clockify_log.py --days 14            # different window
  python3 clockify_log.py --since 2026-06-23 --until 2026-06-27
  python3 clockify_log.py --post               # actually create the entries
  python3 clockify_log.py --post --from-file entries.json   # post a curated file
  python3 clockify_log.py --json-out entries.json           # write entries JSON

Config:
  ~/.config/clockify/api-key          required, chmod 600
  ~/.config/clockify/project-map.json required, e.g. {"my-repo":"My Project"}
                                       maps a substring of the transcript repo dir
                                       to a Clockify project NAME. Run --list-projects
                                       to see the workspace's project names.
"""
import json, glob, os, sys, re, argparse, datetime, urllib.request, urllib.error

HOME = os.path.expanduser("~")
PROJ_BASE = os.path.join(HOME, ".claude", "projects")
KEY_FILE = os.path.join(HOME, ".config", "clockify", "api-key")
MAP_FILE = os.path.join(HOME, ".config", "clockify", "project-map.json")
API = "https://api.clockify.me/api/v1"

GAP_SECONDS = 30 * 60        # gaps longer than this are idle, not counted
CAP_MIN = 120               # autonomous-inflated sessions capped to this many minutes
CAP_TRIGGER_MIN = 150       # sessions over this (or using an autonomous skill) get capped
AUTONOMOUS_SKILLS = ("implement-epic", "next-task")
ROUND_TO = 15
CROSS_CHECK = " Cross-checked for security, architecture, and project standards compliance."

# ---------- helpers ----------
def die(msg):
    print("ERROR:", msg, file=sys.stderr); sys.exit(1)

def api_key():
    if not os.path.exists(KEY_FILE):
        die(f"no API key at {KEY_FILE}. Create it (chmod 600) with your Clockify key.")
    return open(KEY_FILE).read().strip()

def http(method, path, key, body=None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
            headers={"X-Api-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(f"{method} {url} -> {e.code}: {e.read().decode()[:300]}")

def project_map():
    if not os.path.exists(MAP_FILE):
        die(f"no project map at {MAP_FILE}. Create it as JSON mapping a substring of "
            f"each transcript repo dir under {PROJ_BASE} to an exact Clockify project "
            f'name, e.g. {{"my-repo": "My Project"}}. Run --list-projects to see names.')
    pmap = json.load(open(MAP_FILE))
    if not pmap:
        die(f"project map {MAP_FILE} is empty; add at least one repo->project mapping.")
    return pmap

def repo_dir_to_path(dirname):
    # "-home-me-dev-my-repo" -> "/home/me/dev/my/repo"
    return "/" + dirname.lstrip("-").replace("-", "/")

def round15(m):
    return max(ROUND_TO, int(round(m / float(ROUND_TO)) * ROUND_TO))

# ---------- idempotency: skip entries this skill already created ----------
def to_epoch(iso):
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())

def fetch_existing(key, ws, me_id, since, until):
    """Set of (projectId, start-epoch) for the user's existing entries in [since, until)."""
    url = (f"/workspaces/{ws}/user/{me_id}/time-entries"
           f"?start={since}T00:00:00Z&end={until}T00:00:00Z&page-size=5000")
    out = http("GET", url, key)
    seen = set()
    if isinstance(out, list):
        for e in out:
            ti = e.get("timeInterval", {}) or {}
            st = ti.get("start")
            if st:
                seen.add((e.get("projectId"), to_epoch(st)))
    return seen

def mark_dups(entries, existing):
    """A proposed entry is a dup iff an existing entry shares its project + exact start second."""
    for e in entries:
        e["_dup"] = (e["projectId"], to_epoch(e["start"])) in existing

# ---------- transcript mining ----------
def parse_session(path):
    ts, usermsgs, skills = [], [], set()
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("timestamp")
                if t:
                    try:
                        ts.append(datetime.datetime.fromisoformat(t.replace("Z", "+00:00")))
                    except Exception:
                        pass
                if o.get("type") == "user":
                    m = o.get("message", {}); c = m.get("content")
                    if isinstance(c, str):
                        txt = c
                    elif isinstance(c, list):
                        txt = " ".join(p.get("text", "") for p in c
                                       if isinstance(p, dict) and p.get("type") == "text")
                    else:
                        txt = ""
                    txt = txt.strip()
                    if not txt or txt.startswith("<") or "local-command" in txt:
                        continue
                    sk = re.search(r"skills/([\w-]+)", txt)
                    if sk:
                        skills.add(sk.group(1)); continue
                    if txt.lower().startswith("caveat"):
                        continue
                    usermsgs.append(txt)
    except Exception:
        return None
    if not ts:
        return None
    ts.sort()
    active = sum((ts[i] - ts[i - 1]).total_seconds()
                 for i in range(1, len(ts))
                 if (ts[i] - ts[i - 1]).total_seconds() <= GAP_SECONDS)
    refpat = re.compile(
        r"(?:#|\b(?:prs?|pull\s*requests?|issues?|review|re-review|close|closes|approve|"
        r"reopen|merge|analyze)\s+#?)(\d{2,5})\b", re.I)
    refs = sorted(set(int(n) for msg in usermsgs for n in refpat.findall(msg)))
    return {"start": ts[0], "active_min": active / 60.0, "refs": refs,
            "skills": skills, "usermsgs": usermsgs}

_meta_cache = {}
def gh_meta(repo_path, num):
    """Return {kind: 'PR'|'ISS'|'#', num, title, author} for a GitHub PR/issue."""
    ck = (repo_path, num)
    if ck in _meta_cache:
        return _meta_cache[ck]
    meta = {"kind": "#", "num": num, "title": "", "author": None}
    if os.path.isdir(repo_path):
        import subprocess
        try:
            out = subprocess.run(
                ["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{num}",
                 "--jq", '(if .pull_request then "PR" else "ISS" end)+"\t"+.title+"\t"+(.user.login // "")'],
                cwd=repo_path, capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                p = out.stdout.strip().split("\t")
                meta = {"kind": p[0], "num": num,
                        "title": p[1] if len(p) > 1 else "",
                        "author": (p[2] if len(p) > 2 and p[2] else None)}
        except Exception:
            pass
    _meta_cache[ck] = meta
    return meta

def gh_title(repo_path, num):
    m = gh_meta(repo_path, num)
    if not m["title"]:
        return f"#{num}"
    pre = f"PR {num}: " if m["kind"] == "PR" else f"Issue {num}: " if m["kind"] == "ISS" else f"#{num} "
    return pre + m["title"]

_own_login = {}
def own_login(repo_path):
    """The authenticated gh user's login (your own), cached per repo."""
    if repo_path in _own_login:
        return _own_login[repo_path]
    login = None
    if os.path.isdir(repo_path):
        import subprocess
        try:
            out = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                 cwd=repo_path, capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                login = out.stdout.strip() or None
        except Exception:
            pass
    _own_login[repo_path] = login
    return login

def review_kind(refs, repo_path):
    """'peer' if the lead referenced PR is authored by someone else, 'own' if by you,
    else 'n/a' (no PR refs or author/login unknown)."""
    me = own_login(repo_path)
    pr_metas = [gh_meta(repo_path, n) for n in refs[:3]]
    pr_metas = [m for m in pr_metas if m["kind"] == "PR" and m["author"]]
    if not (me and pr_metas):
        return "n/a"
    return "peer" if pr_metas[0]["author"] != me else "own"

def classify(skills, usermsgs):
    if "pr-self-review" in skills:
        return "Self-review"
    if "pr-review" in skills:
        return "Reviewing"
    if skills & set(AUTONOMOUS_SKILLS) or "pr" in skills:
        return "Authoring"
    blob = " ".join(usermsgs[:3]).lower()
    if "review" in blob and "pr" in blob:
        return "Reviewing"
    if any(w in blob for w in ("create an epic", "create issue", "create a skill",
                               "implement", "add ", "build")):
        return "Authoring"
    return "Work"

def describe(proj, sess, repo_path):
    # Invoice format: "<Project>: PR/Issue NNN: <succinct>".  When refs are known we lead
    # with the GitHub title; otherwise fall back to the first prompt. The agent (--draft)
    # rewrites these into 1-2 brief sentences with an optional value-prop.
    if sess["refs"]:
        titles = "; ".join(gh_title(repo_path, n) for n in sess["refs"][:3])
        desc = f"{proj}: {titles}"
        # Peer review of a teammate's PR -> append the cross-check value statement.
        # Your own PRs read as continued development (just the title), no cross-check.
        if review_kind(sess["refs"], repo_path) == "peer":
            if not desc.rstrip().endswith("."):
                desc = desc.rstrip() + "."
            desc += CROSS_CHECK
        return desc
    typ = classify(sess["skills"], sess["usermsgs"])
    if sess["usermsgs"]:
        return f"{proj}: {typ} - {sess['usermsgs'][0][:120]}"
    return f"{proj}: {typ}"

# ---------- build entries ----------
def build(since, until, pmap, name_to_id, no_cap):
    entries = []
    for d in sorted(glob.glob(os.path.join(PROJ_BASE, "*"))):
        if not os.path.isdir(d):
            continue
        dirname = os.path.basename(d)
        target = None
        for substr, pname in pmap.items():
            if substr.lower() in dirname.lower():
                target = pname; break
        if not target:
            continue
        pid = name_to_id.get(target)
        if not pid:
            print(f"  ! no Clockify project named '{target}' (repo {dirname}); skipping",
                  file=sys.stderr)
            continue
        repo_path = repo_dir_to_path(dirname)
        for path in glob.glob(os.path.join(d, "*.jsonl")):
            s = parse_session(path)
            if not s:
                continue
            local = s["start"].astimezone()
            if not (since <= local.date() < until):
                continue
            active = s["active_min"]
            autonomous = bool(s["skills"] & set(AUTONOMOUS_SKILLS))
            capped = active
            if (not no_cap) and (autonomous or active > CAP_TRIGGER_MIN):
                capped = min(active, CAP_MIN)
            dur = round15(capped)
            end = s["start"] + datetime.timedelta(minutes=dur)
            entries.append({
                "start": s["start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "projectId": pid, "description": describe(target, s, repo_path),
                "_project": target, "_local": local, "_dur": dur,
                "_active": active, "_capped": capped != active,
                "_prompts": s["usermsgs"][:8],
                "_titles": [gh_title(repo_path, n) for n in s["refs"][:8]],
                "_authors": {m["num"]: m["author"] for m in
                             (gh_meta(repo_path, n) for n in s["refs"][:8]) if m["author"]},
                "_review_kind": review_kind(s["refs"], repo_path),
                "_me": own_login(repo_path),
                "_skills": sorted(s["skills"]), "_repo": repo_path,
            })
    entries.sort(key=lambda e: e["_local"])
    return entries

def preview(entries):
    cur = None; total = 0; dups = 0
    for e in entries:
        l = e["_local"]; day = f"{l:%a %m-%d}"
        if day != cur:
            print(f"\n--- {day} ---"); cur = day
        flags = []
        if e.get("_capped"): flags.append("capped")
        if e.get("_dup"):    flags.append("DUP-skip")
        tag = (" (" + ", ".join(flags) + ")") if flags else ""
        if e.get("_dup"):
            dups += 1
        else:
            total += e["_dur"]
        print(f"  {l:%H:%M}  {e['_dur']:>4}m  [{e['_project']}]  {e['description'][:90]}{tag}")
    new = len(entries) - dups
    msg = f"\nTOTAL: {total} min = {total/60:.1f} h across {new} new entries"
    if dups:
        msg += f"  ({dups} already in Clockify — will be skipped)"
    print(msg)

def post_all(entries, key, ws, billable=True):
    ok = 0; skipped = 0
    for e in entries:
        if e.get("_dup"):
            skipped += 1
            print(f"  skip  {e['_local']:%m-%d %H:%M} (already in Clockify) {e['description'][:50]}")
            continue
        body = {"start": e["start"], "end": e["end"], "billable": billable,
                "projectId": e["projectId"], "description": e["description"]}
        http("POST", f"/workspaces/{ws}/time-entries", key, body)
        ok += 1
        print(f"  post  {e['_local']:%m-%d %H:%M} ({e['_dur']}m) {e['description'][:50]}")
    tail = f" ({skipped} skipped as duplicates)" if skipped else ""
    print(f"\nDONE: created {ok} entries{tail}.")

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--since"); ap.add_argument("--until")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--no-cap", action="store_true")
    ap.add_argument("--no-dedup", action="store_true",
                    help="do not skip entries already present in Clockify")
    ap.add_argument("--not-billable", action="store_true",
                    help="create entries as non-billable (default is billable)")
    ap.add_argument("--json-out")
    ap.add_argument("--draft", metavar="FILE",
                    help="write per-session context to FILE for the agent to summarize, "
                         "then exit (no posting). Edit each 'description' to a 1-2 sentence "
                         "summary and post with --from-file.")
    ap.add_argument("--from-file", help="POST a curated entries JSON instead of mining")
    ap.add_argument("--list-projects", action="store_true",
                    help="print the workspace's Clockify project names (for building "
                         "project-map.json) and the transcript repo dirs, then exit")
    args = ap.parse_args()

    key = api_key()
    ws = http("GET", "/workspaces", key)[0]["id"]
    me_id = http("GET", "/user", key)["id"]

    if args.list_projects:
        projects = http("GET", f"/workspaces/{ws}/projects?page-size=500&archived=false", key)
        print("Clockify projects in workspace:")
        for p in sorted(p["name"] for p in projects):
            print(f"  {p}")
        print(f"\nTranscript repo dirs under {PROJ_BASE}:")
        for d in sorted(glob.glob(os.path.join(PROJ_BASE, "*"))):
            if os.path.isdir(d):
                print(f"  {os.path.basename(d)}")
        print(f"\nMap them in {MAP_FILE}, e.g. {{\"my-repo\": \"My Project\"}}")
        return

    if args.from_file:
        entries = json.load(open(args.from_file))
        for e in entries:
            e.setdefault("_local", datetime.datetime.fromisoformat(
                e["start"].replace("Z", "+00:00")).astimezone())
            e.setdefault("_dur", int((datetime.datetime.fromisoformat(e["end"].replace("Z","+00:00"))
                         - datetime.datetime.fromisoformat(e["start"].replace("Z","+00:00"))).total_seconds()/60))
            e["_project"] = e.get("project", e.get("_project", ""))
            e["_capped"] = e.get("capped", e.get("_capped", False)); e["_dup"] = False
        if not args.no_dedup and entries:
            lo = min(e["_local"].date() for e in entries)
            hi = max(e["_local"].date() for e in entries) + datetime.timedelta(days=1)
            mark_dups(entries, fetch_existing(key, ws, me_id, lo, hi))
        preview(entries)
        if args.post:
            print("\nPOSTing...\n"); post_all(entries, key, ws, billable=not args.not_billable)
        return

    today = datetime.date.today()
    until = datetime.date.fromisoformat(args.until) if args.until else today + datetime.timedelta(days=1)
    since = datetime.date.fromisoformat(args.since) if args.since else today - datetime.timedelta(days=args.days - 1)

    pmap = project_map()
    projects = http("GET", f"/workspaces/{ws}/projects?page-size=500&archived=false", key)
    name_to_id = {p["name"]: p["id"] for p in projects}

    print(f"Window: {since} .. {until}  (exclusive end)")
    print(f"Mapping: {pmap}")
    entries = build(since, until, pmap, name_to_id, args.no_cap)
    if not entries:
        print("No sessions found in window."); return
    for e in entries:
        e["_dup"] = False
    if not args.no_dedup:
        mark_dups(entries, fetch_existing(key, ws, me_id, since, until))
    preview(entries)

    if args.draft:
        draft = []
        for e in entries:
            draft.append({
                "start": e["start"], "end": e["end"], "projectId": e["projectId"],
                "description": e["description"],            # <-- agent rewrites this to 1-2 sentences
                "project": e["_project"], "local": f"{e['_local']:%a %Y-%m-%d %H:%M}",
                "minutes": e["_dur"], "capped": e["_capped"], "duplicate": e.get("_dup", False),
                "github": e["_titles"], "pr_authors": e["_authors"],
                "review_kind": e["_review_kind"], "my_login": e["_me"],
                "skills_used": e["_skills"], "user_prompts": e["_prompts"], "repo": e["_repo"],
            })
        json.dump(draft, open(args.draft, "w"), indent=2)
        print(f"\nwrote draft -> {args.draft}")
        print("Next: rewrite each 'description' to a 1-2 sentence summary of what was done, "
              "then: clockify_log.py --post --from-file " + args.draft)
        return

    if args.json_out:
        clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]
        json.dump(clean, open(args.json_out, "w"), indent=2)
        print(f"\nwrote {args.json_out}")

    if args.post:
        print("\nPOSTing...\n"); post_all(entries, key, ws, billable=not args.not_billable)
    else:
        print("\n(dry-run; re-run with --post to create these in Clockify)")

if __name__ == "__main__":
    main()
