#!/usr/bin/env python3
"""Render the chair history data as a static site.

    python tools/render.py data _site --repo OWNER/NAME

--repo (default: $GITHUB_REPOSITORY) is the GitHub repository whose issue
forms the "Correct this" and "This is right" links open.
"""

import argparse
import html
import os
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
import chairdata as cd  # noqa: E402

SITE_TITLE = "IETF group chair history"
TYPE_NAMES = {"wg": "WG", "rg": "RG", "ag": "AG", "rag": "RAG", "edwg": "EDWG"}
CERTAINTY_HELP = {
    "exact": "Recorded when the change was made.",
    "approximate": "Recorded in an edit that did not log the change itself; probably close.",
    "on-or-before": "The earliest record we have. It may have started earlier.",
    "between": "Changed without a dated record, sometime in this range.",
    "group-closed": "Still listed as chair when the group closed.",
    "evidence-only": "No datatracker record of the role; dated from announcements or session requests.",
    "ongoing": "Current chair.",
}


def e(text):
    return html.escape(str(text) if text is not None else "", quote=True)


def fold(text):
    """Lower-case and strip accents, for filtering."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def surname_key(name):
    parts = (name or "").split()
    return (fold(parts[-1]) if parts else "", fold(name))


class Site:
    def __init__(self, data, out, repo):
        self.data = data
        self.out = Path(out)
        self.repo = repo
        self.by_person = data.chairs_by_person()

    # --- links ---

    def issue_url(self, template, title, **fields):
        params = {"template": template, "title": title}
        params.update({k: v for k, v in fields.items() if v})
        return f"https://github.com/{self.repo}/issues/new?{urlencode(params)}"

    def person_name(self, key, entry=None):
        if isinstance(key, int) and key in self.data.people:
            return self.data.people[key].get("name") or (entry or {}).get("name", "")
        return (entry or {}).get("name") or str(key).removeprefix("name:")

    def person_uuid(self, key):
        """The datatracker primary UUID of a person with an id; validate.py requires one."""
        return str(self.data.people[key]["uuid"]) if isinstance(key, int) else ""

    def person_slug(self, key):
        """A person page's name: their datatracker primary UUID, never the internal id.

        Only people with no datatracker record get a slug of their name.
        """
        if isinstance(key, int):
            return self.person_uuid(key)
        return "n-" + "".join(c if c.isalnum() else "-" for c in fold(str(key).removeprefix("name:"))).strip("-")

    def person_href(self, key, depth):
        return f"{'../' * depth}people/{self.person_slug(key)}.html"

    @staticmethod
    def group_href(acronym, depth):
        return f"{'../' * depth}groups/{acronym}.html"

    # --- page frame ---

    def page(self, path, title, body, depth, scripts=False):
        up = "../" * depth
        script = f'<script src="{up}filter.js" defer></script>' if scripts else ""
        doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · {SITE_TITLE}</title>
<link rel="stylesheet" href="{up}style.css">
{script}
</head>
<body>
<header class="site">
  <a class="home" href="{up}index.html">{SITE_TITLE}</a>
  <nav><a href="{up}people.html">People</a> <a href="{up}groups.html">Groups</a> <a href="{up}index.html#help">How to help</a></nav>
</header>
<main>
{body}
</main>
<footer>
  Seeded from IETF datatracker records and announcements; corrected by contributors.
  <a href="https://github.com/{e(self.repo)}">Source and data</a>.
</footer>
</body>
</html>
"""
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc)

    # --- shared pieces ---

    @staticmethod
    def bound_cell(bound, which):
        text = cd.describe_start(bound) if which == "start" else cd.describe_end(bound)
        c = bound.get("certainty", "")
        if cd.is_uncertain(bound, which):
            return f'<span class="uncertain" title="{e(CERTAINTY_HELP.get(c, c))}">{e(text)}<span class="q" aria-hidden="true">?</span></span>'
        return f'<span title="{e(CERTAINTY_HELP.get(c, c))}">{e(text)}</span>'

    @staticmethod
    def period_text(p):
        return f"{cd.describe_start(p['start'])} to {cd.describe_end(p['end'])}"

    def evidence_html(self, entry, depth):
        items = []
        for ev in entry.get("evidence") or []:
            kind = ev.get("kind")
            if kind in ("WG Action", "WG Review"):
                subject = f"“{e(ev.get('subject'))}”"
                if ev.get("url"):
                    subject = f'<a href="{e(ev["url"])}">{subject}</a>'
                items.append(f"<li>{e(kind)} announcement, {e(ev.get('date'))}: {subject}</li>")
            elif kind == "list message":
                subject = f"“{e(ev.get('subject'))}”"
                if ev.get("url"):
                    subject = f'<a href="{e(ev["url"])}">{subject}</a>'
                said = "joining" if ev.get("says") == "start" else "leaving"
                quote = f"<br><q>{e(ev.get('excerpt'))}</q>" if ev.get("excerpt") else ""
                items.append(f"<li>Group list message about {said}, {e(ev.get('date'))}: {subject}{quote}</li>")
            elif kind == "chair activity":
                examples = ", ".join(
                    f'<a href="{e(x.get("url", ""))}">“{e(x.get("subject"))}”</a> ({e(x.get("date"))})'
                    for x in ev.get("examples") or []
                )
                items.append(
                    f"<li>Started {e(ev.get('messages'))} chair-type threads on the group list "
                    f"(last calls, adoption calls, agendas, minutes), {e(ev.get('first'))} to {e(ev.get('last'))}"
                    + (f", such as {examples}" if examples else "") + "</li>"
                )
            elif kind in ("proceedings", "minutes"):
                examples = ", ".join(
                    f'<a href="{e(x.get("url", ""))}">{e(x.get("subject"))}</a> ({e(x.get("date"))})'
                    for x in ev.get("examples") or []
                )
                what = "the charter snapshots in meeting proceedings" if kind == "proceedings" else "the chair lists of meeting minutes"
                items.append(
                    f"<li>Listed as chair in {e(ev.get('listed_in'))} of {what}, {e(ev.get('first'))} to {e(ev.get('last'))}"
                    + (f": {examples}" if examples else "") + "</li>"
                )
            elif kind == "minutes without them":
                subject = e(ev.get("subject"))
                if ev.get("url"):
                    subject = f'<a href="{e(ev["url"])}">{subject}</a>'
                items.append(f"<li>Not listed among the chairs in {subject}, {e(ev.get('date'))}</li>")
            elif kind == "session requests":
                template = ev.get("url_template", "")
                links = ", ".join(
                    f'<a href="{e(template.replace("{meeting}", str(m)))}">IETF {e(m)}</a>' for m in ev.get("meetings", [])
                )
                items.append(f"<li>Requested sessions for the group at {links}</li>")
            elif kind == "shepherded":
                docs = ev.get("documents", [])
                links = ", ".join(f'<a href="{cd.DATATRACKER}/doc/{e(d)}/">{e(d)}</a>' for d in docs[:12])
                more = f" and {len(docs) - 12} more" if len(docs) > 12 else ""
                items.append(f"<li>Shepherded {links}{more}</li>")
        for s in entry.get("sources") or []:
            if s.startswith(("http://", "https://")):
                items.append(f'<li>Source: <a href="{e(s)}">{e(s)}</a></li>')
            else:
                items.append(f"<li>Source: {e(s)}</li>")
        for p in entry.get("periods") or []:
            for n in p.get("notes") or []:
                items.append(f"<li>Note: {e(n)}</li>")
        if not items:
            return ""
        return f'<details><summary>Evidence</summary><ul class="evidence">{"".join(items)}</ul></details>'

    def actions_html(self, g, entry, period):
        name = self.person_name(cd.person_key(entry), entry)
        recorded = (
            f"{g['acronym']}: {self.period_text(period)} "
            f"({cd.STATUSES.get(entry.get('status'), entry.get('status'))})"
        )
        person = self.person_uuid(cd.person_key(entry))
        correct = self.issue_url(
            "correction.yml", f"Correction: {name}, {g['acronym']}",
            group=g["acronym"], person=person, name=name, recorded=recorded,
        )
        confirm = self.issue_url(
            "confirmation.yml", f"Confirm: {name}, {g['acronym']}",
            group=g["acronym"], person=person, name=name, recorded=recorded,
        )
        return f'<a class="act" href="{e(correct)}">Correct this</a> <a class="act ok" href="{e(confirm)}">This is right</a>'

    @staticmethod
    def status_html(entry):
        status = entry.get("status")
        label = cd.STATUSES.get(status, status)
        if status == "unconfirmed":
            return f'<span class="badge warn">{e(label)}</span>'
        return f'<span class="muted">{e(label)}</span>'

    # --- pages ---

    def person_page(self, key, rows):
        name = self.person_name(key, rows[0][1])
        person = self.data.people.get(key) if isinstance(key, int) else None
        profile = ""
        if person and person.get("uuid"):
            profile = f'<a href="{cd.DATATRACKER}/person/{e(person["uuid"])}">datatracker profile</a>'
        missing = self.issue_url(
            "missing.yml", f"Missing chair role: {name}",
            person=self.person_uuid(key), name=name,
        )
        lines = []
        flat = []
        for g, entry in rows:
            for p in entry.get("periods") or []:
                flat.append((cd.earliest_start(p["start"]) or cd.latest_end(p["end"]), g, entry, p))
        flat.sort(key=lambda r: (r[0] is None, r[0] or 0, r[1]["acronym"]))
        for _, g, entry, p in flat:
            lines.append(f"""<tr>
  <td><a href="{self.group_href(g['acronym'], 1)}">{e(g['acronym'])}</a> <span class="muted">{e(g.get('name'))}</span></td>
  <td>{self.bound_cell(p['start'], 'start')}</td>
  <td>{self.bound_cell(p['end'], 'end')}</td>
  <td>{self.status_html(entry)}{self.evidence_html(entry, 1)}</td>
  <td class="actions">{self.actions_html(g, entry, p)}</td>
</tr>""")
        body = f"""<h1>{e(name)}</h1>
<p class="lede">Groups {e(name)} chaired, as far as we know. {profile}</p>
<p>Is this list complete, and are the dates right? Use the links on each row, or
<a class="act" href="{e(missing)}">tell us about a missing group</a>.
Dates marked <span class="uncertain">?</span> are uncertain; hover over them for why.</p>
<div class="scroll"><table>
<thead><tr><th>Group</th><th>Chair from</th><th>Chair until</th><th>Basis</th><th><span class="sr">Actions</span></th></tr></thead>
<tbody>
{''.join(lines)}
</tbody></table></div>
{self.glossary()}"""
        self.page(f"people/{self.person_slug(key)}.html", name, body, depth=1)

    def group_page(self, g):
        acronym = g["acronym"]
        missing = self.issue_url("missing.yml", f"Missing chair: {acronym}", group=acronym)
        rows = []
        for entry in g.get("chairs") or []:
            key = cd.person_key(entry)
            name = self.person_name(key, entry)
            for p in entry.get("periods") or []:
                rows.append((cd.earliest_start(p["start"]) or cd.latest_end(p["end"]), name, key, entry, p))
        rows.sort(key=lambda r: (r[0] is None, r[0] or 0, surname_key(r[1])))
        lines = [f"""<tr>
  <td><a href="{self.person_href(key, 1)}">{e(name)}</a></td>
  <td>{self.bound_cell(p['start'], 'start')}</td>
  <td>{self.bound_cell(p['end'], 'end')}</td>
  <td>{self.status_html(entry)}{self.evidence_html(entry, 1)}</td>
  <td class="actions">{self.actions_html(g, entry, p)}</td>
</tr>""" for _, name, key, entry, p in rows]
        state = g.get("state")
        life = " to ".join(x for x in (g.get("started"), g.get("closed")) if x)
        empty = "" if lines else "<p>No chairs recorded yet.</p>"
        table = "" if not lines else f"""<div class="scroll"><table>
<thead><tr><th>Chair</th><th>From</th><th>Until</th><th>Basis</th><th><span class="sr">Actions</span></th></tr></thead>
<tbody>{''.join(lines)}</tbody></table></div>"""
        body = f"""<h1>{e(acronym)} <span class="muted">{e(g.get('name'))}</span></h1>
<p class="lede">{e(TYPE_NAMES.get(g.get('type'), g.get('type')))} in {e(g.get('parent') or 'no area')},
{e(state)}{(', ' + e(life)) if life else ''}.
<a href="{cd.DATATRACKER}/group/{e(acronym)}/about/">About</a> ·
<a href="{e(g.get('history_url') or '')}">datatracker history</a></p>
<p>Know who chaired {e(acronym)} and when? <a class="act" href="{e(missing)}">Tell us about a missing chair</a>,
or use the links on each row.</p>
{empty}{table}
{self.glossary()}"""
        self.page(f"groups/{acronym}.html", acronym, body, depth=1)

    def people_index(self):
        items = []
        for key in sorted(self.by_person, key=lambda k: surname_key(self.person_name(k, self.by_person[k][0][1]))):
            rows = self.by_person[key]
            name = self.person_name(key, rows[0][1])
            groups = sorted({g["acronym"] for g, _ in rows})
            flag = ' <span class="badge warn">unconfirmed</span>' if any(en.get("status") == "unconfirmed" for _, en in rows) else ""
            items.append(
                f'<li data-filter="{e(fold(name + " " + " ".join(groups)))}"><a href="{self.person_href(key, 0)}">{e(name)}</a>'
                f' <span class="muted">{e(", ".join(groups))}</span>{flag}</li>'
            )
        body = f"""<h1>People</h1>
<p>Everyone recorded or suggested as a chair. Find your name, then check the list of groups and the dates.</p>
{self.filter_box("people-list", "Filter by name or group")}
<ul id="people-list" class="list">{''.join(items)}</ul>"""
        self.page("people.html", "People", body, depth=0, scripts=True)

    def groups_index(self):
        by_parent = defaultdict(list)
        for g in self.data.groups.values():
            by_parent[g.get("parent") or "(none)"].append(g)
        sections = []
        for parent in sorted(by_parent):
            items = "".join(
                f'<li data-filter="{e(fold(g["acronym"] + " " + (g.get("name") or "")))}"><a href="{self.group_href(g["acronym"], 0)}">{e(g["acronym"])}</a>'
                f' <span class="muted">{e(g.get("name"))} · {e(TYPE_NAMES.get(g.get("type"), g.get("type")))}, {e(g.get("state"))}</span></li>'
                for g in sorted(by_parent[parent], key=lambda g: g["acronym"])
            )
            sections.append(f'<section data-filter-section><h2>{e(parent)}</h2><ul class="list">{items}</ul></section>')
        body = f"""<h1>Groups</h1>
<p>Working groups, research groups and similar groups, by area or parent.</p>
{self.filter_box("groups-list", "Filter by acronym or name")}
<div id="groups-list">{''.join(sections)}</div>"""
        self.page("groups.html", "Groups", body, depth=0, scripts=True)

    def overview(self):
        n_people = len(self.by_person)
        status = Counter(en.get("status") for g in self.data.groups.values() for en in g.get("chairs") or [])
        uncertain = Counter()
        for g in self.data.groups.values():
            for en in g.get("chairs") or []:
                for p in en.get("periods") or []:
                    uncertain[g["acronym"]] += cd.is_uncertain(p["start"], "start") + cd.is_uncertain(p["end"], "end")
        candidates = sorted(
            {(cd.person_key(en), g["acronym"]) for g in self.data.groups.values() for en in g.get("chairs") or [] if en.get("status") == "unconfirmed"},
            key=lambda kg: (surname_key(self.person_name(kg[0])), kg[1]),
        )
        cand_items = "".join(
            f'<li><a href="{self.person_href(k, 0)}">{e(self.person_name(k))}</a> for '
            f'<a href="{self.group_href(a, 0)}">{e(a)}</a>?</li>' for k, a in candidates
        )
        top = "".join(
            f'<li><a href="{self.group_href(a, 0)}">{e(a)}</a> <span class="muted">{n} uncertain dates</span></li>'
            for a, n in uncertain.most_common(30) if n
        )
        body = f"""<h1>Who chaired which IETF group, and when?</h1>
<p class="lede">The datatracker has dated records of chair changes only from 2012, and partial records from
late 2011. This site starts from those records and from IETF announcements and meeting records,
and asks the people who were there to fill in the rest.</p>
<p class="stats">{len(self.data.groups)} groups · {n_people} people ·
{status.get('confirmed', 0)} roles from datatracker records ·
{status.get('unconfirmed', 0)} suggested roles waiting for confirmation ·
{status.get('contributed', 0)} contributed</p>

<h2 id="help">How to help</h2>
<ol>
<li>Find yourself on the <a href="people.html">people list</a>, or a group you know on the <a href="groups.html">groups list</a>.</li>
<li>Check that every group you chaired is listed, and that the dates are right. Uncertain dates are marked <span class="uncertain">?</span>.</li>
<li>Use <b>This is right</b> to confirm a row, <b>Correct this</b> to fix one, or the link at the top of the page to add a missing group.
Each opens a short GitHub issue form, already filled in with the row you clicked. A link to an announcement, minutes or a mailing list message helps the reviewers.</li>
</ol>
<p>If you're comfortable with git, you can instead edit the group's file under <code>data/groups/</code> and open a pull request; see the README.</p>

<h2>Were these people chairs?</h2>
<p>Announcements and meeting records suggest these people chaired these groups, but the datatracker has no record of it.</p>
<ul class="columns">{cand_items}</ul>

<h2>Groups with the most uncertain dates</h2>
<ul class="columns">{top}</ul>
{self.glossary()}"""
        self.page("index.html", "Overview", body, depth=0)

    @staticmethod
    def filter_box(target, label):
        return (
            f'<p><label class="filter">{e(label)} <input type="search" data-filter-target="{target}" '
            f'data-filter-count="{target}-count" autocomplete="off"></label> '
            f'<span id="{target}-count" class="muted" aria-live="polite"></span></p>'
        )

    @staticmethod
    def glossary():
        rows = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in CERTAINTY_HELP.items())
        return f'<details class="glossary"><summary>How certain is each date?</summary><dl>{rows}</dl></details>'

    def build(self, assets):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        for asset in Path(assets).iterdir():
            shutil.copy(asset, self.out / asset.name)
        for key, rows in self.by_person.items():
            self.person_page(key, rows)
        for g in self.data.groups.values():
            self.group_page(g)
        self.people_index()
        self.groups_index()
        self.overview()
        (self.out / ".nojekyll").write_text("")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO"))
    args = ap.parse_args(argv)
    data = cd.load(args.data_dir)
    if data.problems:
        for path, msg in data.problems:
            print(f"{path}: {msg}", file=sys.stderr)
        return 1
    Site(data, args.out_dir, args.repo).build(Path(__file__).parent.parent / "site")
    print(f"Wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
