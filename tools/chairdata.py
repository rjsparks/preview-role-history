"""Load the chair history data and describe it in words.

Shared by validate.py and render.py.
"""

import datetime
import re
from pathlib import Path

import yaml

STATUSES = {
    "confirmed": "from datatracker records",
    "unconfirmed": "unconfirmed: suggested by indirect evidence",
    "contributed": "added or corrected by a contributor",
}

# Which date fields each certainty label needs, for a start and for an end.
CERTAINTIES = {
    "exact": ("date",),
    "approximate": ("date",),
    "on-or-before": ("date",),
    "between": ("not_before",),
    "group-closed": ("date",),
    "evidence-only": (),  # start needs not_after, end needs not_before (checked separately)
    "ongoing": (),
}
CLOSED_STATES = {"conclude", "bof-conc", "abandon", "replaced"}
DATATRACKER = "https://datatracker.ietf.org"

_PARTIAL_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def norm_date(value):
    """Return a date field as a string, whatever YAML made of it."""
    if value is None:
        return None
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()[:10]
    return str(value)


def valid_date(value):
    """True for YYYY, YYYY-MM or YYYY-MM-DD that names a real date."""
    if not _PARTIAL_DATE.match(value):
        return False
    parts = [int(p) for p in value.split("-")]
    try:
        datetime.date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError:
        return False
    return True


def earliest(value):
    """The first day a partial date could mean."""
    parts = value.split("-")
    return datetime.date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1)


def latest(value):
    """The last day a partial date could mean."""
    parts = value.split("-")
    year = int(parts[0])
    if len(parts) == 1:
        return datetime.date(year, 12, 31)
    month = int(parts[1])
    if len(parts) == 2:
        following = datetime.date(year + (month == 12), month % 12 + 1, 1)
        return following - datetime.timedelta(days=1)
    return datetime.date(year, month, int(parts[2]))


def bound_fields(bound):
    return {k: norm_date(bound.get(k)) for k in ("date", "not_before", "not_after")}


def earliest_start(start):
    f = bound_fields(start)
    value = f["not_before"] or f["date"] or f["not_after"]
    return earliest(value) if value and valid_date(value) else None


def latest_end(end):
    f = bound_fields(end)
    if end.get("certainty") == "ongoing":
        return datetime.date.max
    value = f["not_after"] or f["date"]
    return latest(value) if value and valid_date(value) else None


def firm_start(start):
    """The latest day a firmly dated start could be, or None if it is not firm."""
    f = bound_fields(start)
    if start.get("certainty") in ("exact", "approximate") and f["date"] and valid_date(f["date"]):
        return latest(f["date"])
    return None


def firm_end(end):
    """The earliest day a firmly dated end could be, or None if it is not firm."""
    f = bound_fields(end)
    if end.get("certainty") == "ongoing":
        return datetime.date.max
    if end.get("certainty") in ("exact", "approximate", "group-closed") and f["date"] and valid_date(f["date"]):
        return earliest(f["date"])
    return None


def describe_start(b):
    f, c = bound_fields(b), b.get("certainty")
    if c in ("exact", "group-closed"):
        return f["date"]
    if c == "approximate":
        return f"about {f['date']}"
    if c == "on-or-before":
        return f"by {f['date']}"
    if c == "between":
        return f"between {f['not_before']} and {f['not_after']}" if f["not_after"] else f"after {f['not_before']}"
    if c == "evidence-only":
        return f"by {f['not_after']}" if f["not_after"] else "unknown"
    return "unknown"


def describe_end(b):
    f, c = bound_fields(b), b.get("certainty")
    if c == "ongoing":
        return "present"
    if c == "exact":
        return f["date"]
    if c == "approximate":
        return f"about {f['date']}"
    if c == "group-closed":
        return f"{f['date']} (group closed)"
    if c == "between":
        return f"between {f['not_before']} and {f['not_after']}" if f["not_after"] else f"after {f['not_before']}"
    if c == "evidence-only":
        return f"after {f['not_before']}" if f["not_before"] else "unknown"
    if c == "on-or-before":
        return f"by {f['date']}"
    return "unknown"


BOF_STATES = {"bof", "bof-conc"}
CHARTER_MARGIN = datetime.timedelta(days=30)  # chairs named at chartering can predate the state change by days


def latest_start(start):
    """The latest day a start could be, or None if nothing bounds it."""
    f = bound_fields(start)
    value = f["date"] if start.get("certainty") in ("exact", "approximate", "on-or-before") else f["not_after"]
    return latest(value) if value and valid_date(value) else None


def earliest_end(end):
    """The earliest day an end could be, or None if nothing bounds it."""
    if end.get("certainty") == "ongoing":
        return datetime.date.max
    f = bound_fields(end)
    value = f["date"] if end.get("certainty") in ("exact", "approximate", "group-closed") else f["not_before"]
    return earliest(value) if value and valid_date(value) else None


def bof_phase(group, period):
    """"bof" for chairing only the BOF, "bof-wg" for the BOF and then the WG, or None.

    None also covers periods whose dates are too uncertain to place against
    the chartering date.
    """
    if not group.get("bof"):
        return None
    if group.get("state") in BOF_STATES:
        return "bof"
    chartered = group.get("chartered")
    if not chartered or not valid_date(norm_date(chartered)):
        return None
    chartered = earliest(norm_date(chartered))
    end = latest_end(period["end"])
    if end is not None and end < chartered:
        return "bof"
    start, finish = latest_start(period["start"]), earliest_end(period["end"])
    if start is not None and finish is not None and start < chartered - CHARTER_MARGIN and finish >= chartered:
        return "bof-wg"
    return None


def is_uncertain(bound, which):
    """Whether a boundary is worth asking someone about."""
    c = bound.get("certainty")
    if which == "end" and c == "ongoing":
        return False
    return c not in ("exact",)


class Data:
    def __init__(self, groups, people, problems, people_path=None):
        self.people_path = people_path
        self.groups = groups  # acronym -> group dict
        self.people = people  # id -> person dict
        self.problems = problems  # load errors: (path, message)

    def chairs_by_person(self):
        """person key -> list of (group, entry). Key is the id, or "name:<name>" for people without one."""
        result = {}
        for g in self.groups.values():
            for e in g.get("chairs") or []:
                result.setdefault(person_key(e), []).append((g, e))
        return result


def person_key(entry):
    return entry["person"] if entry.get("person") is not None else f"name:{entry.get('name', '')}"


def load(data_dir):
    data_dir = Path(data_dir)
    problems = []
    groups = {}
    for path in sorted((data_dir / "groups").glob("*.yaml")):
        try:
            g = yaml.safe_load(path.read_text())
        except yaml.YAMLError as err:
            problems.append((path, f"not valid YAML: {err}"))
            continue
        if not isinstance(g, dict):
            problems.append((path, "must be a mapping"))
            continue
        g["_path"] = path
        groups[path.stem] = g
    people = {}
    people_path = data_dir / "people.yaml"
    try:
        for p in yaml.safe_load(people_path.read_text()) or []:
            people[p["id"]] = p
    except (yaml.YAMLError, KeyError, TypeError) as err:
        problems.append((people_path, f"could not be read: {err}"))
    return Data(groups, people, problems, people_path)
