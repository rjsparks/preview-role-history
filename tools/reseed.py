#!/usr/bin/env python3
"""Replace the extracted data with a new seed without losing contributions.

    python tools/reseed.py <seed dir> data

The seed directory is the extractor's output (groups/*.yaml and
reference/people.yaml). Contributions survive:

- chair entries with status `contributed` are kept, and replace the seed's
  entry for the same person;
- groups with `datatracker: false` are kept. If the datatracker has since
  learned of the group (same acronym and name), its seed file is used and the
  contributed chairs and sources are merged in. A seed group with the same
  acronym but a different name is a clash for a maintainer to resolve, and
  nothing is written;
- people contributors added to people.yaml are kept.
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


def merge_chairs(seed_chairs, kept):
    """The seed's chairs with contributed entries in place of the seed's for the same person, then the rest."""
    out = [kept.pop(cd.person_key(e), e) for e in seed_chairs or []]
    return out + list(kept.values())


def reseed(seed_dir, data_dir):
    """Return a list of clashes; write nothing if there are any."""
    seed_dir, data_dir = Path(seed_dir), Path(data_dir)
    groups_dir = data_dir / "groups"
    current = {p.stem: load_yaml(p) for p in sorted(groups_dir.glob("*.yaml"))}
    seeded = {p.stem: load_yaml(p) for p in sorted((seed_dir / "groups").glob("*.yaml"))}

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
        seed["chairs"] = merge_chairs(seed.get("chairs"), kept)
        result[acronym] = seed
    for acronym, mine in current.items():
        if acronym not in result and mine and mine.get("datatracker") is False:
            result[acronym] = mine  # still unknown to the datatracker
    if clashes:
        return clashes

    for path in groups_dir.glob("*.yaml"):
        if path.stem not in result:
            path.unlink()
    for acronym, data in result.items():
        dump(groups_dir / f"{acronym}.yaml", data)

    people = {p["id"]: p for p in load_yaml(seed_dir / "reference" / "people.yaml") or []}
    for p in load_yaml(data_dir / "people.yaml") or []:
        people.setdefault(p["id"], p)
    dump(data_dir / "people.yaml", [people[k] for k in sorted(people)])
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed_dir")
    ap.add_argument("data_dir")
    args = ap.parse_args(argv)
    clashes = reseed(args.seed_dir, args.data_dir)
    for c in clashes:
        print(c, file=sys.stderr)
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
