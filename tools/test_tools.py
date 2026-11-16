"""Tests for validate.py and render.py: python -m unittest discover tools"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import chairdata as cd  # noqa: E402
import render  # noqa: E402
import validate  # noqa: E402

PEOPLE = [{"id": 1, "name": "Ada Chair", "uuid": "00000000-0000-4000-8000-000000000001"}]


def group(**overrides):
    g = {
        "acronym": "abc", "name": "A Big Charter", "type": "wg", "parent": "art",
        "state": "active", "started": "2010-01-01", "closed": None,
        "history_url": "https://datatracker.ietf.org/group/abc/history/",
        "chairs": [{
            "person": 1, "name": "Ada Chair", "status": "confirmed",
            "periods": [{"start": {"certainty": "exact", "date": "2012-03-04"}, "end": {"certainty": "ongoing"}}],
        }],
    }
    g.update(overrides)
    return g


class DataDirMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        (self.data / "groups").mkdir(parents=True)
        self.write_people(PEOPLE)

    def tearDown(self):
        self.tmp.cleanup()

    def write_people(self, people):
        (self.data / "people.yaml").write_text(yaml.safe_dump(people))

    def write_group(self, g, name=None):
        (self.data / "groups" / f"{name or g['acronym']}.yaml").write_text(yaml.safe_dump(g, sort_keys=False))

    def problems(self):
        return [msg for _, msg in validate.check(cd.load(self.data))]


class ValidateTests(DataDirMixin, unittest.TestCase):
    def test_valid_data_passes(self):
        self.write_group(group())
        self.assertEqual(self.problems(), [])

    def test_unquoted_and_partial_dates_are_accepted(self):
        g = group()
        g["chairs"][0]["periods"][0]["start"] = {"certainty": "approximate", "date": "2012-03"}
        text = yaml.safe_dump(g, sort_keys=False).replace("'2012-03'", "2012-03")
        (self.data / "groups" / "abc.yaml").write_text(text.replace("date: 2012-03\n", "date: 2012-03-04\n"))
        self.assertEqual(self.problems(), [])

    def test_file_name_must_match_acronym(self):
        self.write_group(group(), name="xyz")
        self.assertTrue(any("file is named xyz.yaml" in m for m in self.problems()))

    def test_unknown_person(self):
        g = group()
        g["chairs"][0]["person"] = 99
        self.write_group(g)
        self.assertTrue(any("person 99 is not in data/people.yaml" in m for m in self.problems()))

    def test_person_without_id_needs_name(self):
        g = group()
        g["chairs"][0]["person"] = None
        g["chairs"][0]["name"] = ""
        self.write_group(g)
        self.assertTrue(any("needs `person`" in m for m in self.problems()))

    def test_ongoing_needs_open_group(self):
        self.write_group(group(state="conclude", closed="2015-01-01"))
        self.assertTrue(any("end is `ongoing` but the group is conclude" in m for m in self.problems()))

    def test_period_must_not_end_before_it_starts(self):
        g = group()
        g["chairs"][0]["periods"][0]["end"] = {"certainty": "exact", "date": "2011-01-01"}
        self.write_group(g)
        self.assertTrue(any("ends before it starts" in m for m in self.problems()))

    def test_bad_dates_and_certainties(self):
        g = group()
        g["chairs"][0]["periods"][0]["start"] = {"certainty": "exact", "date": "2012-13-01"}
        g["chairs"][0]["periods"][0]["end"] = {"certainty": "sometime"}
        self.write_group(g)
        problems = self.problems()
        self.assertTrue(any("must be a date" in m for m in problems))
        self.assertTrue(any("`certainty` must be one of" in m for m in problems))

    def test_overlapping_firm_periods(self):
        g = group()
        g["chairs"][0]["periods"] = [
            {"start": {"certainty": "exact", "date": "2012-01-01"}, "end": {"certainty": "exact", "date": "2014-01-01"}},
            {"start": {"certainty": "exact", "date": "2013-01-01"}, "end": {"certainty": "ongoing"}},
        ]
        self.write_group(g)
        self.assertTrue(any("periods overlap" in m for m in self.problems()))

    def test_duplicate_person(self):
        g = group()
        g["chairs"].append(dict(g["chairs"][0]))
        self.write_group(g)
        self.assertTrue(any("appears twice" in m for m in self.problems()))


class SourcesRequiredTests(DataDirMixin, unittest.TestCase):
    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def setUp(self):
        super().setUp()
        self.write_group(group())
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "add", ".")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed")
        self.git("checkout", "-q", "-b", "change")

    def commit(self):
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "change")

    def sources_problems(self):
        return validate.changed_without_sources(cd.load(self.data), "main", self.root)

    def test_changed_entry_needs_sources(self):
        g = group()
        g["chairs"][0]["periods"][0]["start"]["date"] = "2011-05-06"
        self.write_group(g)
        self.commit()
        self.assertEqual(len(self.sources_problems()), 1)
        g["chairs"][0]["sources"] = ["https://mailarchive.ietf.org/arch/msg/ietf-announce/example"]
        self.write_group(g)
        self.commit()
        self.assertEqual(self.sources_problems(), [])

    def test_unchanged_entries_need_nothing(self):
        g = group()
        g["chairs"].append({
            "person": None, "name": "Old Timer", "status": "contributed",
            "periods": [{"start": {"certainty": "approximate", "date": "1995"}, "end": {"certainty": "approximate", "date": "1998"}}],
            "sources": ["IETF 35 proceedings"],
        })
        self.write_group(g)
        self.commit()
        self.assertEqual(self.sources_problems(), [])


class RenderTests(DataDirMixin, unittest.TestCase):
    def test_pages_and_prefilled_issue_links(self):
        g = group()
        g["chairs"].append({
            "person": None, "name": "Old Timer", "status": "contributed",
            "periods": [{"start": {"certainty": "approximate", "date": "1995"}, "end": {"certainty": "approximate", "date": "1998"}}],
            "sources": ["IETF 35 proceedings"],
        })
        g["chairs"][0]["evidence"] = [{
            "kind": "WG Action", "date": "2001-03-12", "subject": "WG ACTION: A Big Charter (abc)",
            "url": "https://mailarchive.ietf.org/arch/msg/ietf-announce-old/example/",
        }, {
            "kind": "list message", "date": "2013-06-08", "says": "start", "subject": "[abc] New co-chair",
            "url": "https://mailarchive.ietf.org/arch/msg/abc/example/", "excerpt": "Please welcome Ada <Chair>.",
        }, {
            "kind": "chair activity", "first": "2013-07-01", "last": "2015-02-03", "messages": 12,
            "examples": [{"date": "2014-01-02", "subject": "[abc] WGLC: draft-ietf-abc-foo",
                          "url": "https://mailarchive.ietf.org/arch/msg/abc/wglc/"}],
        }]
        self.write_group(g)
        out = self.root / "site"
        site = render.Site(cd.load(self.data), out, "example/chairs")
        site.build(Path(__file__).parent.parent / "site")
        for page in ("index.html", "people.html", "groups.html", "groups/abc.html", "people/1.html", "people/n-old-timer.html"):
            self.assertTrue((out / page).exists(), page)
        person = (out / "people" / "1.html").read_text()
        self.assertIn("https://datatracker.ietf.org/person/00000000-0000-4000-8000-000000000001", person)
        link = next(part.split('"')[0] for part in person.split('href="') if "correction.yml" in part)
        query = parse_qs(urlparse(link.replace("&amp;", "&")).query)
        self.assertEqual(query["group"], ["abc"])
        self.assertEqual(query["person"], ["1"])
        self.assertIn("2012-03-04 to present", query["recorded"][0])
        self.assertIn('<a href="https://mailarchive.ietf.org/arch/msg/ietf-announce-old/example/">', person)
        self.assertIn("Group list message about joining, 2013-06-08", person)
        self.assertIn("<q>Please welcome Ada &lt;Chair&gt;.</q>", person)
        self.assertIn('Started 12 chair-type threads', person)
        self.assertIn('<a href="https://mailarchive.ietf.org/arch/msg/abc/wglc/">', person)
        self.assertIn("about 1995", (out / "people" / "n-old-timer.html").read_text())


class DescribeTests(unittest.TestCase):
    def test_partial_date_ranges(self):
        self.assertEqual(str(cd.latest("2024-02")), "2024-02-29")
        self.assertEqual(str(cd.earliest("1998")), "1998-01-01")
        self.assertEqual(str(cd.latest("1998")), "1998-12-31")

    def test_descriptions(self):
        self.assertEqual(cd.describe_start({"certainty": "on-or-before", "date": "2011-12-09"}), "by 2011-12-09")
        self.assertEqual(cd.describe_end({"certainty": "between", "not_before": "2011-12-09"}), "after 2011-12-09")
        self.assertEqual(cd.describe_end({"certainty": "group-closed", "date": "2003-12-10"}), "2003-12-10 (group closed)")


if __name__ == "__main__":
    unittest.main()
