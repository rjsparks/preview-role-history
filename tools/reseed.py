#!/usr/bin/env python3
"""Replace the extracted data with a new seed without losing contributions.

    python tools/reseed.py <seed dir> data

The seed directory is the extractor's output (groups/*.yaml and
reference/people.yaml). Contributions survive, and nothing that carries one is
deleted:

- chair entries with status `contributed` are kept, and replace the seed's
  entry for the same person;
- groups with `datatracker: false` are kept. If the datatracker has since
  learned of the group (same acronym and name), its seed file is used and the
  contributed chairs and sources are merged in. A seed group with the same
  acronym but a different name is a clash for a maintainer to resolve, and
  nothing is written;
- `confirmations` ("This is right") move to the seed's entry for that
  person, which keeps updating from new evidence; a confirmed person the new
  seed no longer has is kept as a contributed entry;
- `rejected` people stay rejected: the seed's entries for them are dropped;
- `overrides` (corrected group fields) are applied over the seed's values;
- a group file the new seed no longer has is kept if it carries any of these;
- people contributors added to people.yaml are kept: people the datatracker
  knows, added by `uuid` (folded into the seed's entry once it has them by
  id, along with chair entries naming them by UUID), and people it doesn't
  know, added by `key`.
"""

import argparse
import sys
import unicodedata
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import chairdata as cd  # noqa: E402


def fold(text):
    plain = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))
    return " ".join(plain.lower().replace("bof", "").split())


def load_yaml(path):
    return yaml.safe_load(path.read_text()) if path.exists() else None


def dump(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))


def contributed(entries):
    return {cd.person_key(e): e for e in entries or [] if isinstance(e, dict) and e.get("status") == "contributed"}


def merge_chairs(seed_chairs, kept, by_uuid):
    """The seed's chairs with contributed entries in place of the seed's for the same person, then the rest.

    A contributed entry that names someone by UUID is the seed's entry for
    them once the seed has them by id; it then names them by id.
    """
    kept = {by_uuid.get(k, k): ({**e, "person": by_uuid[k]} if k in by_uuid else e) for k, e in kept.items()}
    out = [kept.pop(cd.person_key(e), e) for e in seed_chairs or []]
    return out + list(kept.values())


def has_contributions(group):
    chairs = group.get("chairs") or []
    return bool(
        group.get("datatracker") is False or group.get("rejected") or group.get("overrides")
        or any(isinstance(e, dict) and (e.get("status") == "contributed" or e.get("confirmations")) for e in chairs)
    )


def overlay(seed, mine, by_uuid, notes, acronym):
    """The seed's group with the contributions in mine applied."""
    for field in ("overrides", "rejected"):
        if mine.get(field):
            seed[field] = mine[field]
    for k, v in (mine.get("overrides") or {}).items():
        seed[k] = v
    rejected = {r.get("person") for r in mine.get("rejected") or [] if isinstance(r, dict)}
    seed["chairs"] = [e for e in seed.get("chairs") or [] if e.get("person") not in rejected]
    by_key = {cd.person_key(e): e for e in seed["chairs"]}
    for e in mine.get("chairs") or []:
        if not isinstance(e, dict) or e.get("status") == "contributed" or not e.get("confirmations"):
            continue
        key = by_uuid.get(cd.person_key(e), cd.person_key(e))
        if key in by_key:
            by_key[key]["confirmations"] = list(dict.fromkeys((by_key[key].get("confirmations") or []) + e["confirmations"]))
        else:
            notes.append(f"{acronym}: {e.get('name')} was confirmed but the new seed no longer has them; kept as contributed")
            seed["chairs"].append({**e, "status": "contributed"})
    return seed


def reseed(seed_dir, data_dir, notes=None):
    """Return a list of clashes; write nothing if there are any. Messages for the maintainer go in notes."""
    notes = [] if notes is None else notes
    seed_dir, data_dir = Path(seed_dir), Path(data_dir)
    groups_dir = data_dir / "groups"
    current = {p.stem: load_yaml(p) for p in sorted(groups_dir.glob("*.yaml"))}
    seeded = {p.stem: load_yaml(p) for p in sorted((seed_dir / "groups").glob("*.yaml"))}
    seed_people = load_yaml(seed_dir / "reference" / "people.yaml") or []
    by_uuid = {str(p["uuid"]): p["id"] for p in seed_people if p.get("uuid")}

    clashes = []
    result = {}
    for acronym, seed in seeded.items():
        mine = current.get(acronym) or {}
        kept = contributed(mine.get("chairs"))
        if mine.get("datatracker") is False:
            if fold(mine.get("name")) != fold(seed.get("name")):
                clashes.append(f"{acronym}: contributed group {mine.get('name')!r} and datatracker group "
                               f"{seed.get('name')!r} share an acronym; rename the contributed file")
                continue
            # Every chair of a contributed group came from contributors, whatever its status says.
            kept = {cd.person_key(e): {**e, "status": "contributed"} for e in mine.get("chairs") or [] if isinstance(e, dict)}
            seed["sources"] = list(dict.fromkeys((seed.get("sources") or []) + (mine.get("sources") or [])))
        seed = overlay(seed, mine, by_uuid, notes, acronym)
        seed["chairs"] = merge_chairs(seed.get("chairs"), kept, by_uuid)
        result[acronym] = seed
    for acronym, mine in current.items():
        if acronym in result or not mine:
            continue
        if mine.get("datatracker") is False:
            mine["chairs"] = merge_chairs([], {cd.person_key(e): e for e in mine.get("chairs") or []}, by_uuid)
            result[acronym] = mine  # still unknown to the datatracker
        elif has_contributions(mine):
            notes.append(f"{acronym}: not in the new seed (renamed or out of scope?); kept for its contributions")
            result[acronym] = mine
    if clashes:
        return clashes

    for path in groups_dir.glob("*.yaml"):
        if path.stem not in result:
            path.unlink()
    for acronym, data in result.items():
        dump(groups_dir / f"{acronym}.yaml", data)

    people = {p["id"]: p for p in seed_people}
    for p in load_yaml(data_dir / "people.yaml") or []:
        # People contributors added: by UUID (dropped once the seed has them by id) or by key.
        if p.get("id") is None and p.get("uuid") and str(p["uuid"]) in by_uuid:
            continue
        people.setdefault(cd.people_entry_key(p), p)
    dump(data_dir / "people.yaml", [people[k] for k in sorted(people, key=lambda k: (isinstance(k, str), str(k).zfill(12)))])
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed_dir")
    ap.add_argument("data_dir")
    args = ap.parse_args(argv)
    notes = []
    clashes = reseed(args.seed_dir, args.data_dir, notes)
    for c in clashes:
        print(c, file=sys.stderr)
    for n in notes:
        print(n)
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
