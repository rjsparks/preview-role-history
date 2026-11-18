#!/usr/bin/env python3
"""Check the chair history data.

    python tools/validate.py data                       # check everything
    python tools/validate.py data --base origin/main    # also require sources on changes

With --base, every chair entry that a pull request adds or changes must carry a
non-empty `sources` list, so that reviewers can check the claim.

Problems are printed as GitHub Actions annotations when GITHUB_ACTIONS is set.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import chairdata as cd  # noqa: E402

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
GROUP_KEYS = ("acronym", "name", "type", "state", "chairs")
GROUP_TYPES = ("wg", "rg", "edwg", "bof")
PERSON_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def check(data):
    """Return a list of (path, message)."""
    problems = list(data.problems)
    for pid, person in data.people.items():
        if isinstance(pid, int):
            if not UUID.match(str(person.get("uuid") or "")):
                problems.append((data.people_path, f"person {pid} needs `uuid`, their datatracker primary UUID"))
            continue
        if cd.is_uuid(pid):
            # Someone the datatracker knows, added by a contributor before the seed has them.
            if not person.get("name"):
                problems.append((data.people_path, f"person {pid} needs a `name`"))
            continue
        # Someone the datatracker doesn't know about yet.
        if not PERSON_KEY.match(str(pid)):
            problems.append((data.people_path, f"person key {pid!r} must be lower-case letters, digits and hyphens"))
        if person.get("datatracker") is not False:
            problems.append((data.people_path, f"person {pid!r} has no datatracker `id`, so needs `datatracker: false`"))
        if not person.get("name"):
            problems.append((data.people_path, f"person {pid!r} needs a `name`"))
        sources = person.get("sources")
        if not (isinstance(sources, list) and sources and all(isinstance(x, str) and x.strip() for x in sources)):
            problems.append((data.people_path, f"person {pid!r} needs a `sources` list saying how we know of them"))
    for acronym, g in data.groups.items():
        path = g["_path"]

        def bad(msg, path=path):
            problems.append((path, msg))

        for key in GROUP_KEYS:
            if key not in g:
                bad(f"missing `{key}`")
        if g.get("datatracker") is False:
            # A group the datatracker never knew about rests on what contributors tell us.
            sources = g.get("sources")
            if not (isinstance(sources, list) and sources and all(isinstance(x, str) and x.strip() for x in sources)):
                bad("a group with `datatracker: false` needs a `sources` list saying how we know it existed")
            if g.get("type") not in GROUP_TYPES:
                bad(f"`type` must be one of {', '.join(GROUP_TYPES)}")
        elif "datatracker" in g and g["datatracker"] is not True:
            bad("`datatracker` must be true or false")
        if g.get("acronym") != acronym:
            bad(f"`acronym` is {g.get('acronym')!r} but the file is named {acronym}.yaml")
        for flag in ("bof", "never_chartered"):
            if flag in g and not isinstance(g[flag], bool):
                bad(f"`{flag}` must be true or false")
        if g.get("chartered") is not None and not cd.valid_date(cd.norm_date(g["chartered"])):
            bad("`chartered` must be a date written YYYY-MM-DD, YYYY-MM or YYYY")
        closed = g.get("state") in cd.CLOSED_STATES
        seen = set()
        for i, e in enumerate(g.get("chairs") or []):
            where = f"chairs[{i}] ({e.get('name', '?')})" if isinstance(e, dict) else f"chairs[{i}]"
            if not isinstance(e, dict):
                bad(f"{where}: must be a mapping")
                continue
            pid = e.get("person")
            if pid is None:
                if not e.get("name"):
                    bad(f"{where}: needs `person` (datatracker id) or, for someone with no datatracker record, `name`")
            elif not isinstance(pid, (int, str)):
                bad(f"{where}: `person` must be a datatracker person id, or the key of someone added to people.yaml")
            elif pid not in data.people:
                bad(f"{where}: person {pid!r} is not in data/people.yaml; add them there too")
            key = cd.person_key(e)
            if key in seen:
                bad(f"{where}: this person appears twice; put all their periods in one entry")
            seen.add(key)
            if e.get("status") not in cd.STATUSES:
                bad(f"{where}: `status` must be one of {', '.join(cd.STATUSES)}")
            sources = e.get("sources")
            if sources is not None and not (isinstance(sources, list) and all(isinstance(s, str) and s.strip() for s in sources)):
                bad(f"{where}: `sources` must be a list of non-empty strings (links or citations)")
            periods = e.get("periods")
            if not isinstance(periods, list) or not periods:
                bad(f"{where}: needs at least one period")
                continue
            spans = []
            for j, p in enumerate(periods):
                pw = f"{where} period {j + 1}"
                if not isinstance(p, dict) or "start" not in p or "end" not in p:
                    bad(f"{pw}: needs `start` and `end`")
                    continue
                ok = True
                for which in ("start", "end"):
                    for msg in check_bound(p[which], which):
                        bad(f"{pw} {which}: {msg}")
                        ok = False
                if not ok:
                    continue
                if p["end"].get("certainty") == "ongoing" and closed:
                    bad(f"{pw}: end is `ongoing` but the group is {g.get('state')}")
                s, t = cd.earliest_start(p["start"]), cd.latest_end(p["end"])
                if s and t and t < s:
                    bad(f"{pw}: ends before it starts")
                spans.append((p, s, t))
            # Only certain overlaps: the later period's latest possible start
            # falls before the earlier period's earliest possible end.
            firm = sorted(
                (cd.firm_start(p["start"]), cd.firm_end(p["end"])) for p, _, _ in spans
                if cd.firm_start(p["start"])
            )
            for (a1, b1), (a2, _) in zip(firm, firm[1:]):
                if b1 is not None and a2 < b1:
                    shown = "present" if b1 == datetime.date.max else b1
                    bad(f"{where}: periods overlap (one runs {a1} to {shown}, the next starts {a2}); merge them")
    return problems


def check_bound(b, which):
    if not isinstance(b, dict):
        return ["must be a mapping with `certainty`"]
    c = b.get("certainty")
    if c not in cd.CERTAINTIES:
        return [f"`certainty` must be one of {', '.join(cd.CERTAINTIES)}"]
    msgs = []
    if which == "start" and c in ("ongoing", "group-closed"):
        msgs.append(f"`{c}` only makes sense for an end")
    f = cd.bound_fields(b)
    needed = list(cd.CERTAINTIES[c])
    if c == "evidence-only":
        needed.append("not_after" if which == "start" else "not_before")
    for k in needed:
        if not f[k]:
            msgs.append(f"`{c}` needs `{k}`")
    for k, v in f.items():
        if v is not None and not cd.valid_date(v):
            msgs.append(f"`{k}` must be a date written YYYY-MM-DD, YYYY-MM or YYYY, not {v!r}")
    return msgs


def changed_without_sources(data, base, repo_root):
    """Entries a change adds or alters that carry no sources."""
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "data/groups"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.split()
    problems = []
    for name in out:
        acronym = Path(name).stem
        g = data.groups.get(acronym)
        if g is None:
            continue  # deleted; reviewers see that in the diff
        show = subprocess.run(["git", "show", f"{base}:{name}"], cwd=repo_root, capture_output=True, text=True)
        before = {}
        if show.returncode == 0:
            for e in (yaml.safe_load(show.stdout) or {}).get("chairs") or []:
                before[cd.person_key(e)] = e
        for e in g.get("chairs") or []:
            if not isinstance(e, dict):
                continue
            old = before.get(cd.person_key(e))
            if old is not None and strip_sources(old) == strip_sources(e):
                continue
            if not e.get("sources"):
                verb = "adds" if old is None else "changes"
                problems.append((g["_path"], f"this change {verb} the entry for {e.get('name', '?')}; "
                                             f"add a `sources` list saying where the information comes from"))
    return problems


def strip_sources(e):
    return {k: v for k, v in e.items() if k != "sources"}


def report(problems, repo_root):
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    for path, msg in problems:
        rel = os.path.relpath(path, repo_root)
        print(f"::error file={rel}::{msg}" if gha else f"{rel}: {msg}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir")
    ap.add_argument("--base", help="git ref to compare with; changed entries must then have sources")
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    repo_root = data_dir.parent
    data = cd.load(data_dir)
    problems = check(data)
    if args.base:
        problems += changed_without_sources(data, args.base, repo_root)
    report(problems, repo_root)
    if problems:
        print(f"{len(problems)} problem(s) found.")
        return 1
    print(f"OK: {len(data.groups)} groups, {len(data.people)} people.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
