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
import reseed  # noqa: E402
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
        self.assertTrue(any("end is `ongoing` but the group is concluded" in m for m in self.problems()))

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

    def test_people_need_a_uuid(self):
        self.write_people([{"id": 1, "name": "Ada Chair"}])
        self.write_group(group())
        self.assertTrue(any("person 1 needs `uuid`" in m for m in self.problems()))

    def test_links_must_be_https(self):
        g = group()
        g["chairs"][0]["evidence"] = [{"kind": "list message", "url": "javascript:alert(1)"}]
        g["chairs"][0]["sources"] = ["javascript:alert(2)"]
        self.write_group(g)
        self.assertEqual(sum("links must start with https://" in m for m in self.problems()), 2)

    def test_ranges_and_starts_after_closing(self):
        g = group(state="conclude", closed="2009-05-01")
        g["chairs"][0]["periods"] = [{"start": {"certainty": "between", "not_before": "2010-07-25", "not_after": "2010-01-01"},
                                       "end": {"certainty": "group-closed"}}]
        self.write_group(g)
        problems = self.problems()
        self.assertTrue(any("`not_after` is before `not_before`" in m for m in problems))
        self.assertTrue(any("starts after the group closed" in m for m in problems))

    def test_rejections(self):
        g = group(rejected=[{"person": 1, "sources": ["issue #5: never chaired it"]}])
        self.write_group(g)
        self.assertTrue(any("listed under `rejected`" in m for m in self.problems()))
        g = group(rejected=[{"person": 2}])
        self.write_group(g)
        self.assertTrue(any("each `rejected` item needs" in m for m in self.problems()))

    def test_duplicate_person(self):
        g = group()
        g["chairs"].append(dict(g["chairs"][0]))
        self.write_group(g)
        self.assertTrue(any("appears twice" in m for m in self.problems()))


class MissingGroupTests(DataDirMixin, unittest.TestCase):
    def jabber(self, **overrides):
        g = group(acronym="jabber", name="Jabber Protocol BOF", type="bof", state="bof-conc", parent=None,
                  started=None, closed=None, history_url=None, datatracker=False,
                  sources=["https://www.ietf.org/proceedings/54/minutes/jabber.htm"])
        g["chairs"][0]["status"] = "contributed"
        g["chairs"][0]["sources"] = ["https://www.ietf.org/proceedings/54/minutes/jabber.htm"]
        g["chairs"][0]["periods"] = [{"start": {"certainty": "approximate", "date": "2002-07-15"},
                                       "end": {"certainty": "approximate", "date": "2002-07-15"}}]
        g.update(overrides)
        return g

    def test_a_group_unknown_to_the_datatracker(self):
        self.write_group(self.jabber())
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        page = (out / "groups" / "jabber.html").read_text()
        self.assertIn("Not in the datatracker", page)
        self.assertNotIn("datatracker.ietf.org/group/jabber", page)
        self.assertIn("missing-group.yml", (out / "groups.html").read_text())

    def test_it_needs_sources(self):
        self.write_group(self.jabber(sources=[]))
        self.assertTrue(any("needs a `sources` list" in m for m in self.problems()))


class MissingPersonTests(DataDirMixin, unittest.TestCase):
    jane = {"key": "jane-doe", "name": "Jane Doe", "datatracker": False, "sources": ["IETF 54 minutes"]}

    def chair_entry(self):
        return {"person": "jane-doe", "name": "Jane Doe", "status": "contributed", "sources": ["issue #7"],
                "periods": [{"start": {"certainty": "approximate", "date": "2002"}, "end": {"certainty": "approximate", "date": "2003"}}]}

    def test_a_person_unknown_to_the_datatracker_chairs_two_groups(self):
        self.write_people(PEOPLE + [self.jane])
        g = group()
        g["chairs"].append(self.chair_entry())
        self.write_group(g)
        other = group(acronym="xyz", name="Another Group")
        other["chairs"] = [self.chair_entry()]
        self.write_group(other)
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        page = (out / "people" / "c-jane-doe.html").read_text()
        self.assertIn("Not in the datatracker", page)
        self.assertIn("groups/abc.html", page)
        self.assertIn("groups/xyz.html", page)  # one page for both roles

    def test_people_need_sources_and_must_exist(self):
        self.write_people(PEOPLE + [{**self.jane, "sources": []}])
        g = group()
        g["chairs"].append({**self.chair_entry(), "person": "john-roe"})
        self.write_group(g)
        problems = self.problems()
        self.assertTrue(any("'jane-doe' needs a `sources` list" in m for m in problems))
        self.assertTrue(any("'john-roe' is not in data/people.yaml" in m for m in problems))

    def test_reseed_keeps_them(self):
        self.write_people(PEOPLE + [self.jane])
        self.write_group(group())
        seed = self.root / "seed"
        (seed / "groups").mkdir(parents=True)
        (seed / "reference").mkdir()
        (seed / "groups" / "abc.yaml").write_text(yaml.safe_dump(group(), sort_keys=False))
        (seed / "reference" / "people.yaml").write_text(yaml.safe_dump(PEOPLE))
        self.assertEqual(reseed.reseed(seed, self.data), [])
        self.assertIn("jane-doe", [p.get("key") for p in yaml.safe_load((self.data / "people.yaml").read_text())])


class KnownPersonNewChairTests(DataDirMixin, unittest.TestCase):
    uuid = "5f065c18-439d-4462-81b0-7647979d946c"

    def chair_entry(self):
        return {"person": self.uuid, "name": "Lars Example", "status": "contributed", "sources": ["issue #9"],
                "periods": [{"start": {"certainty": "approximate", "date": "1999"}, "end": {"certainty": "approximate", "date": "2001"}}]}

    def test_added_by_uuid_then_seeded_by_id(self):
        self.write_people(PEOPLE + [{"uuid": self.uuid, "name": "Lars Example"}])
        g = group()
        g["chairs"].append(self.chair_entry())
        self.write_group(g)
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        self.assertTrue((out / "people" / f"{self.uuid}.html").exists())  # the same page the seed would give them

        seed = self.root / "seed"
        (seed / "groups").mkdir(parents=True)
        (seed / "reference").mkdir()
        other = group(acronym="xyz", name="Another Group")
        other["chairs"] = [{"person": 77, "name": "Lars Example", "status": "confirmed",
                            "periods": [{"start": {"certainty": "exact", "date": "2012-01-01"}, "end": {"certainty": "ongoing"}}]}]
        for x in (group(), other):
            (seed / "groups" / f"{x['acronym']}.yaml").write_text(yaml.safe_dump(x, sort_keys=False))
        (seed / "reference" / "people.yaml").write_text(yaml.safe_dump(PEOPLE + [{"id": 77, "name": "Lars Example", "uuid": self.uuid}]))
        self.assertEqual(reseed.reseed(seed, self.data), [])
        abc = yaml.safe_load((self.data / "groups" / "abc.yaml").read_text())
        self.assertIn(77, [c["person"] for c in abc["chairs"]])  # the contributed entry now names them by id
        people = yaml.safe_load((self.data / "people.yaml").read_text())
        self.assertEqual([p.get("id") for p in people if p.get("uuid") == self.uuid], [77])  # one entry, not two
        self.assertEqual(self.problems(), [])


class ReseedTests(DataDirMixin, unittest.TestCase):
    def seed(self, groups, people=PEOPLE):
        seed = self.root / "seed"
        (seed / "groups").mkdir(parents=True, exist_ok=True)
        (seed / "reference").mkdir(exist_ok=True)
        for p in (seed / "groups").glob("*.yaml"):
            p.unlink()
        for g in groups:
            (seed / "groups" / f"{g['acronym']}.yaml").write_text(yaml.safe_dump(g, sort_keys=False))
        (seed / "reference" / "people.yaml").write_text(yaml.safe_dump(people))
        return seed

    def entry(self, person, name, status="contributed"):
        return {"person": person, "name": name, "status": status, "sources": ["issue #1"],
                "periods": [{"start": {"certainty": "approximate", "date": "2002"}, "end": {"certainty": "approximate", "date": "2003"}}]}

    def test_a_reports_b_adds_then_the_datatracker_learns_of_the_group(self):
        jabber = group(acronym="jabber", name="Jabber Protocol BOF", type="bof", state="unknown", datatracker=False,
                       sources=["IETF 54 proceedings"], chairs=[self.entry(1, "Ada Chair")])
        self.write_group(jabber)                       # person A reports the group and their role
        jabber["chairs"].append(self.entry(None, "Bea Helper"))
        self.write_group(jabber)                       # person B adds another chair
        self.assertEqual(reseed.reseed(self.seed([group()]), self.data), [])
        kept = yaml.safe_load((self.data / "groups" / "jabber.yaml").read_text())
        self.assertEqual([c["name"] for c in kept["chairs"]], ["Ada Chair", "Bea Helper"])  # untouched by the reseed

        later = group(acronym="jabber", name="Jabber Protocol", type="wg", state="conclude",
                      chairs=[{**self.entry(2, "Cy Recorded", status="confirmed"), "sources": None}])
        self.assertEqual(reseed.reseed(self.seed([group(), later]), self.data), [])
        merged = yaml.safe_load((self.data / "groups" / "jabber.yaml").read_text())
        self.assertNotIn("datatracker", merged)
        self.assertEqual(sorted(c["name"] for c in merged["chairs"]), ["Ada Chair", "Bea Helper", "Cy Recorded"])
        self.assertIn("IETF 54 proceedings", merged["sources"])

    def test_contributed_entries_in_seeded_groups_survive(self):
        g = group()
        g["chairs"][0] = self.entry(1, "Ada Chair")
        self.write_group(g)
        self.assertEqual(reseed.reseed(self.seed([group()]), self.data), [])
        kept = yaml.safe_load((self.data / "groups" / "abc.yaml").read_text())
        self.assertEqual(kept["chairs"][0]["status"], "contributed")

    def test_confirmations_rejections_and_overrides_survive(self):
        g = group(overrides={"bof": True}, rejected=[{"person": 9, "sources": ["issue #4"]}])
        g["chairs"][0]["confirmations"] = ["issue #3"]
        self.write_group(g)
        newer = group(bof=False)
        newer["chairs"][0]["periods"][0]["end"] = {"certainty": "exact", "date": "2020-01-01"}
        newer["chairs"].append({"person": 9, "name": "Not Achair", "status": "unconfirmed",
                                "periods": [{"start": {"certainty": "approximate", "date": "2001"}, "end": {"certainty": "approximate", "date": "2002"}}]})
        self.assertEqual(reseed.reseed(self.seed([newer]), self.data), [])
        kept = yaml.safe_load((self.data / "groups" / "abc.yaml").read_text())
        self.assertTrue(kept["bof"])  # the override wins
        self.assertEqual([c["person"] for c in kept["chairs"]], [1])  # the rejected candidate stays out
        self.assertEqual(kept["chairs"][0]["confirmations"], ["issue #3"])
        self.assertEqual(kept["chairs"][0]["periods"][0]["end"]["date"], "2020-01-01")  # still updates

    def test_a_group_with_contributions_is_not_deleted(self):
        g = group(acronym="old")
        g["chairs"][0] = self.entry(1, "Ada Chair")
        self.write_group(g)
        notes = []
        self.assertEqual(reseed.reseed(self.seed([group()]), self.data, notes), [])
        self.assertTrue((self.data / "groups" / "old.yaml").exists())
        self.assertTrue(any("kept for its contributions" in n for n in notes))

    def test_an_acronym_clash_writes_nothing(self):
        self.write_group(group(acronym="sip", name="Simple Internet Protocol", datatracker=False, sources=["x"]))
        clash = group(acronym="sip", name="Session Initiation Protocol")
        self.assertEqual(len(reseed.reseed(self.seed([clash]), self.data)), 1)
        self.assertEqual(yaml.safe_load((self.data / "groups" / "sip.yaml").read_text())["name"], "Simple Internet Protocol")


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
        problems = [m for _, m in self.sources_problems()]
        self.assertTrue(any("add a `sources` list" in m for m in problems))
        self.assertTrue(any("set its `status` to `contributed`" in m for m in problems))  # or the next reseed drops it
        g["chairs"][0]["sources"] = ["https://mailarchive.ietf.org/arch/msg/ietf-announce/example"]
        g["chairs"][0]["status"] = "contributed"
        self.write_group(g)
        self.commit()
        self.assertEqual(self.sources_problems(), [])

    def test_a_confirmation_is_not_a_change(self):
        g = group()
        g["chairs"][0]["confirmations"] = ["issue #3"]
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
        g["chairs"][0]["periods"][0]["notes"] = ["Start: the BOF met at IETF 49 (2000-12-10)"]
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
        }, {
            "kind": "proceedings", "listed_in": 3, "first": "1997-04-07", "last": "1998-11-25",
            "examples": [{"date": "1997-04-07", "subject": "IETF 38 proceedings charter",
                          "url": "https://www.ietf.org/proceedings/38/abc.htm"}],
        }, {
            "kind": "list message", "date": "2007-04-23", "says": "end", "implied": "another chair became the sole chair",
            "subject": "[abc] New chair", "url": "https://mailarchive.ietf.org/arch/msg/abc/sole/",
            "excerpt": "Bob has agreed to take over as the sole chair.",
        }, {
            "kind": "joined the IESG", "after_meeting": "74", "after": "2009-03-22", "by_meeting": "75", "by": "2009-07-26",
        }, {
            "kind": "BOF session", "meeting": "49", "date": "2000-12-10",
            "url": "https://www.ietf.org/proceedings/49/abc.htm",
        }, {
            "kind": "minutes without them", "date": "1999-03-01", "subject": "IETF 44 proceedings charter",
            "url": "https://www.ietf.org/proceedings/44/abc.htm",
        }]
        self.write_group(g)
        out = self.root / "site"
        site = render.Site(cd.load(self.data), out, "example/chairs")
        site.build(Path(__file__).parent.parent / "site")
        for page in ("index.html", "people.html", "groups.html", "groups/abc.html", "people/00000000-0000-4000-8000-000000000001.html", "people/n-old-timer.html"):
            self.assertTrue((out / page).exists(), page)
        person = (out / "people" / "00000000-0000-4000-8000-000000000001.html").read_text()
        self.assertIn("https://datatracker.ietf.org/person/00000000-0000-4000-8000-000000000001", person)
        link = next(part.split('"')[0] for part in person.split('href="') if "correction.yml" in part)
        query = parse_qs(urlparse(link.replace("&amp;", "&")).query)
        self.assertEqual(query["group"], ["abc"])
        self.assertEqual(query["person"], ["00000000-0000-4000-8000-000000000001"])
        self.assertIn("2012-03-04 to present", query["recorded"][0])
        self.assertIn('<a href="https://mailarchive.ietf.org/arch/msg/ietf-announce-old/example/">', person)
        self.assertIn("Group list message about joining, 2013-06-08", person)
        self.assertIn("<q>Please welcome Ada &lt;Chair&gt;.</q>", person)
        self.assertIn('Started 12 chair-type threads', person)
        self.assertIn("Listed as chair in 3 of the charter snapshots in meeting proceedings", person)
        self.assertIn('Not listed among the chairs in <a href="https://www.ietf.org/proceedings/44/abc.htm">', person)
        self.assertIn('<a href="https://mailarchive.ietf.org/arch/msg/abc/wglc/">', person)
        self.assertFalse((out / "people" / "1.html").exists())
        self.assertIn('href="../people/00000000-0000-4000-8000-000000000001.html"', (out / "groups" / "abc.html").read_text())
        self.assertIn('<section class="glossary" id="dates">', person)
        self.assertIn(">by 2006-03-19<", person)  # the legend shows each form as dates appear
        self.assertIn('href="#dates"', person)
        self.assertNotIn("on-or-before</dt>", person)
        self.assertIn("BOF only", (out / "index.html").read_text() + person)  # explained in the legend
        self.assertIn("Group list message naming a new sole chair, so the other chairs&#x27; terms ended, 2007-04-23", person)
        self.assertIn("Joined the IESG after IETF 74 (2009-03-22) and by IETF 75 (2009-07-26).", person)
        self.assertIn("How the dates were set:", person)
        self.assertIn("<b>Start:</b> the BOF met at IETF 49 (2000-12-10)", person)
        self.assertIn('The BOF met at <a href="https://www.ietf.org/proceedings/49/abc.htm">IETF 49</a>', person)
        self.assertIn("about 1995", (out / "people" / "n-old-timer.html").read_text())


class AreaHistoryTests(DataDirMixin, unittest.TestCase):
    def test_a_group_that_moved_shows_every_area(self):
        self.write_people(PEOPLE)
        self.write_group(group(acronym="avt", parent="rai", state="conclude", closed="2011-03-18", chairs=[], areas=[
            {"area": "tsv", "first": "1995-04-03", "last": "2005-03-06"},
            {"area": "rai", "first": "2006-07-09", "last": "2011-03-18"}]), "avt")
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        page = (out / "groups" / "avt.html").read_text()
        self.assertIn("concluded 2011-03-18.\nAreas: tsv (1995–2005), then rai (2006–2011).", page)
        index = (out / "groups.html").read_text()
        self.assertGreater(index.index("<h2>tsv</h2>"), index.index("<h2>rai</h2>"))
        self.assertEqual(index.count("groups/avt.html"), 2)  # under both areas

    def test_an_active_group_is_still_in_its_last_area(self):
        self.write_people(PEOPLE)
        self.write_group(group(acronym="nfsv4", parent="wit", areas=[
            {"area": "tsv", "first": "1998-08-05", "last": "2023-11-21"},
            {"area": "wit", "first": "2024-01-17", "last": None}]), "nfsv4")
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        self.assertIn("tsv (1998–2023), then wit (since 2024)", (out / "groups" / "nfsv4.html").read_text())

    def test_lifespan_puts_the_closing_date_with_the_closing_state(self):
        life = render.Site.lifespan_text
        self.assertEqual(life(group(state="conclude", closed="2014-11-08")),
                         "WG, started 2010-01-01, concluded 2014-11-08.")
        self.assertEqual(life(group()), "WG, started 2010-01-01, active.")
        self.assertEqual(life(group(state="bof-conc", started=None, never_chartered=True)), "BOF, concluded.")
        self.assertEqual(life(group(state="bof", started=None, never_chartered=True)), "BOF.")

    def test_state_names(self):
        self.assertEqual(cd.state_text("conclude"), "concluded")
        self.assertEqual(cd.state_text("bof-conc"), "BOF concluded")
        self.write_people(PEOPLE)
        self.write_group(group(state="concluded"))
        self.assertTrue(any("`state` must be one of" in m for m in self.problems()))

    def test_areas_need_dates(self):
        self.write_people(PEOPLE)
        self.write_group(group(areas=[{"area": "tsv", "first": "1995"}, {"area": "rai", "first": "2006"}]))
        self.assertTrue(any("`areas` must be" in m for m in self.problems()))  # only the current area is open

    def test_a_closed_groups_areas_all_end(self):
        self.write_people(PEOPLE)
        self.write_group(group(state="conclude", closed="2011-03-18", chairs=[],
                               areas=[{"area": "rai", "first": "2006", "last": None}]))
        self.assertTrue(any("`areas` must be" in m for m in self.problems()))


class RecordEvidenceTests(DataDirMixin, unittest.TestCase):
    def test_the_datatracker_record_is_shown_and_linked(self):
        self.write_people(PEOPLE)
        g = group(acronym="iasa20", state="bof", never_chartered=True, bof=True)
        g["history_url"] = "https://datatracker.ietf.org/group/iasa20/history/"
        g["chairs"][0]["evidence"] = [{"kind": "datatracker record", "date": "2017-02-27", "says": "start",
                                       "text": "Chairs changed to Gonzalo Camarillo, Leslie Daigle",
                                       "url": "https://datatracker.ietf.org/group/iasa20/history/"}]
        self.write_group(g, "iasa20")
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        page = (out / "groups" / "iasa20.html").read_text()
        self.assertIn('Datatracker record of joining, 2017-02-27: <a href="https://datatracker.ietf.org/group/iasa20/history/">'
                      "“Chairs changed to Gonzalo Camarillo, Leslie Daigle”</a>", page)
        self.assertIn('<a href="https://datatracker.ietf.org/group/iasa20/history/">from datatracker records</a>', page)


class ChartingAnnouncementTests(DataDirMixin, unittest.TestCase):
    def test_not_named_at_chartering_is_shown(self):
        self.write_people(PEOPLE)
        g = group(acronym="oauth", bof=True, chartered="2009-05-12")
        g["chairs"][0]["evidence"] = [{"kind": "chartering announcement without them", "date": "2009-05-13",
                                       "subject": "WG Action: Open Authentication Protocol (oauth)",
                                       "url": "https://mailarchive.ietf.org/arch/msg/ietf-announce/abc/"}]
        self.write_group(g, "oauth")
        self.assertEqual(self.problems(), [])
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        self.assertIn("Not named among the chairs when the group was chartered, 2009-05-13: "
                      '<a href="https://mailarchive.ietf.org/arch/msg/ietf-announce/abc/">“WG Action: Open Authentication Protocol (oauth)”</a>',
                      (out / "groups" / "oauth.html").read_text())


class SuccessionTests(DataDirMixin, unittest.TestCase):
    def build(self):
        out = self.root / "site"
        render.Site(cd.load(self.data), out, "example/chairs").build(Path(__file__).parent.parent / "site")
        return out

    def test_a_bof_that_went_on_under_another_acronym(self):
        self.write_people(PEOPLE)
        self.write_group(group(acronym="iasa20", state="replaced", closed="2018-05-09", chairs=[], bof=True,
                               never_chartered=True, became={"group": "iasa2", "how": "the datatracker says so"}), "iasa20")
        self.write_group(group(acronym="iasa2", chairs=[], began_as=["iasa20"]), "iasa2")
        self.assertEqual(self.problems(), [])
        out = self.build()
        bof = (out / "groups" / "iasa20.html").read_text()
        self.assertIn('A BOF that went on as <a href="../groups/iasa2.html">iasa2</a> (the datatracker says so)', bof)
        self.assertIn('Carries on from <a href="../groups/iasa20.html">iasa20</a>.', (out / "groups" / "iasa2.html").read_text())

    def test_a_working_group_that_went_on_as_another(self):
        self.write_people(PEOPLE)
        for a in ("bmwg", "ippm"):
            self.write_group(group(acronym=a, state="conclude", closed="2026-11-04", chairs=[],
                                   became={"group": "bpm", "how": "the datatracker says so"}), a)
        self.write_group(group(acronym="bpm", chairs=[]), "bpm")
        out = self.build()
        self.assertIn('It went on as <a href="../groups/bpm.html">bpm</a> (the datatracker says so).',
                      (out / "groups" / "bmwg.html").read_text())
        self.assertIn("Carries on from <a href=\"../groups/bmwg.html\">bmwg</a> and <a href=\"../groups/ippm.html\">ippm</a>.",
                      (out / "groups" / "bpm.html").read_text())

    def test_no_known_successor_is_not_a_claim_there_was_none(self):
        self.write_people(PEOPLE)
        self.write_group(group(acronym="furi", state="conclude", closed="2003-12-10", chairs=[], bof=True,
                               never_chartered=True, became=None), "furi")
        page = (self.build() / "groups" / "furi.html").read_text()
        self.assertIn("no working group was chartered under this acronym", page)
        self.assertNotIn("not chartered as a working group", page)
        self.assertIn("template=successor.yml", page)

    def test_became_must_name_another_group(self):
        self.write_people(PEOPLE)
        self.write_group(group(acronym="iasa20", chairs=[], became={"group": "nosuch"}), "iasa20")
        self.assertTrue(any("`became` names 'nosuch'" in m for m in self.problems()))


class BofPhaseTests(unittest.TestCase):
    def period(self, start, end):
        return {"start": start, "end": end}

    def test_never_chartered_bof(self):
        g = {"bof": True, "state": "bof-conc"}
        self.assertEqual(cd.bof_phase(g, self.period({"certainty": "evidence-only", "not_after": "2010-03"},
                                                     {"certainty": "group-closed", "date": "2010-11-01"})), "bof")

    def test_bof_the_datatracker_shows_as_concluded(self):
        g = {"bof": True, "state": "conclude", "never_chartered": True, "chartered": None}
        p = self.period({"certainty": "on-or-before", "date": "2003-12-10"}, {"certainty": "group-closed", "date": "2003-12-10"})
        self.assertEqual(cd.bof_phase(g, p), "bof")

    def test_an_end_known_only_to_within_days_after_chartering_is_bof_only(self):
        g = {"bof": True, "state": "active", "chartered": "2009-05-12"}  # oauth
        def ending(not_before, not_after):
            return self.period({"certainty": "evidence-only", "not_after": "2008-11-16"},
                               {"certainty": "between", "not_before": not_before, "not_after": not_after})
        self.assertEqual(cd.bof_phase(g, ending("2008-12-01", "2009-05-15")), "bof")  # Mark Nottingham
        self.assertEqual(cd.bof_phase(g, ending("2008-12-01", "2009-05-12")), "bof")  # the charter date itself
        self.assertIsNone(cd.bof_phase(g, ending("2008-12-01", "2009-07-15")))  # could have chaired the WG for weeks

    def test_chartered_group(self):
        g = {"bof": True, "state": "conclude", "chartered": "2001-11-01"}
        bof_only = self.period({"certainty": "evidence-only", "not_after": "2001-08-05"},
                               {"certainty": "between", "not_before": "2001-08-05", "not_after": "2001-10-01"})
        through = self.period({"certainty": "on-or-before", "date": "2001-08-14"},
                              {"certainty": "group-closed", "date": "2009-05-01"})
        at_charter = self.period({"certainty": "approximate", "date": "2001-10-25"},
                                 {"certainty": "group-closed", "date": "2009-05-01"})
        unknown_end = self.period({"certainty": "evidence-only", "not_after": "2001-08-14"},
                                  {"certainty": "evidence-only", "not_before": "2001-09-01"})
        self.assertEqual(cd.bof_phase(g, bof_only), "bof")
        self.assertEqual(cd.bof_phase(g, through), "bof-wg")
        self.assertIsNone(cd.bof_phase(g, at_charter))  # named at chartering, days before the state change
        self.assertIsNone(cd.bof_phase(g, unknown_end))  # might have ended before or after chartering
        self.assertIsNone(cd.bof_phase({"bof": False, "chartered": "2001-11-01"}, through))


class DescribeTests(unittest.TestCase):
    def test_partial_date_ranges(self):
        self.assertEqual(str(cd.latest("2024-02")), "2024-02-29")
        self.assertEqual(str(cd.earliest("1998")), "1998-01-01")
        self.assertEqual(str(cd.latest("1998")), "1998-12-31")

    def test_descriptions(self):
        self.assertEqual(cd.describe_start({"certainty": "on-or-before", "date": "2011-12-09"}), "by 2011-12-09")
        self.assertEqual(cd.describe_end({"certainty": "between", "not_before": "2011-12-09"}), "after 2011-12-09")
        self.assertEqual(cd.describe_end({"certainty": "group-closed", "date": "2003-12-10"}), "2003-12-10 (group closed)")
        self.assertEqual(cd.describe_end({"certainty": "on-or-before", "date": "2000-03-26"}), "ended by 2000-03-26")


if __name__ == "__main__":
    unittest.main()
