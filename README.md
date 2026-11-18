# IETF group chair history

**NOTE** : This is a preview instance of this idea - any data collected in this preview will be lost. Feel free to play with the concept. The actual data collection will come later.

Who chaired which IETF working group, research group and similar group, and when.

**Site: https://rjsparks.github.io/preview-role-history/**

The IETF datatracker has dated records of chair changes only from 2012, with partial
records from late 2011. This repository starts from those records and fills the gaps
with help from the people who were there. The site built from it has a page for each
person and each group, so you can check your own record at a glance.

## Checking your record

1. Open the [People list](https://rjsparks.github.io/preview-role-history/people.html) and
   find your name.
2. Check that every group you chaired is listed, and that the dates are right. Dates marked
   **?** are uncertain; hover over one to see why.
3. On each row, choose **This is right** or **Correct this**. To add a group that's missing,
   use the link at the top of your page. Each link opens a short issue form, already filled
   in with the row you clicked.

A link to an announcement, minutes, proceedings or a mailing list message helps the
reviewers most, but "I was the chair" is useful too.

## Editing the data directly

If you're comfortable with git, edit the group's file under `data/groups/` and open a pull
request. Each file lists the group's chairs:

```yaml
chairs:
- person: 12345            # datatracker person id; see data/people.yaml
  name: Example Person
  status: contributed
  periods:
  - start: {certainty: exact, date: '2006-03-20'}
    end: {certainty: approximate, date: '2010-11'}
  sources:
  - https://mailarchive.ietf.org/arch/msg/ietf-announce/...
```

- **person**: who it is. One of:
  - the datatracker person id, for anyone already in `data/people.yaml`;
  - the person's datatracker UUID, from their profile address
    (`https://datatracker.ietf.org/person/<uuid>`), for someone the datatracker knows who
    isn't in `data/people.yaml` yet. Add them there too, with `uuid` and `name`; the next
    reseed switches to their id;
  - a key such as `jane-doe` (lower-case letters, digits and hyphens), for someone the
    datatracker doesn't know about. Add them to `data/people.yaml` with that `key`, their
    `name`, `datatracker: false` and a `sources` list. Their roles in every group then share
    one page.
- **status**: `confirmed` (from datatracker records), `unconfirmed` (suggested by indirect
  evidence), or `contributed` (added or corrected by a contributor). An entry a pull request
  adds or changes must be `contributed`: that is what keeps it when the data is reseeded.
- **periods**: one per stretch as chair. Dates are `YYYY-MM-DD`, `YYYY-MM` or `YYYY`.
  Each start and end has a `certainty`:

  | certainty | meaning | fields |
  |---|---|---|
  | `exact` | recorded when the change was made | `date` |
  | `approximate` | dated by a datatracker edit made near the time | `date` |
  | `announced` | dated by an announcement or list message about the change | `date` |
  | `on-or-before` | the earliest record; may have started earlier | `date`, optional `not_before` |
  | `between` | sometime in a range | `not_before`, optional `not_after` |
  | `group-closed` | still chair when the group closed (ends only) | `date`, if known |
  | `evidence-only` | dated only by evidence (start: `not_after`; end: `not_before`) | as noted |
  | `ongoing` | current chair (ends only) | none |

- **sources**: required on any entry a pull request adds or changes. Links (`https://`) or
  citations.
- **confirmations**: a list of sources for "this is right" (an issue, a link). Adding one is
  not a change to the entry: it keeps its status and keeps updating from new evidence.
- **rejected** (group level): people who were *not* chairs of the group although the seed
  suggested it, each `{person, sources}`. The seed won't list them again.
- **overrides** (group level): corrected group fields (`name`, `state`, `parent`, `started`,
  `closed`, `bof`, `never_chartered`, `chartered`), kept over the seed's values.
- **Group fields** `bof`, `never_chartered`, `chartered` and `bof_sessions` say whether the
  group began as a BOF, whether it never became a working group, when it was first
  chartered, and which BOF sessions the meeting proceedings show.
  The site uses them to mark chairing that was only for the BOF ("BOF only") or that
  carried on into the working group ("BOF, then WG"). Correct them under `overrides`.
- **Groups the datatracker doesn't know about.** Some early groups and BOFs never made it
  into the datatracker, and we collect their chairs anyway. Add a file for one with
  `datatracker: false`, a `type` of `bof`, `wg` or `rg`, its `state` as best known (or
  `unknown`), and a group-level `sources` list saying how we know it existed. Anyone can
  report one with the "A group that isn't listed" issue form; once its file exists, its page
  takes further chairs and corrections like any other group's.
- **evidence**: written by the seed extraction. Leave it as it is.

Checks run on every pull request. To run them yourself:

```sh
pip install -r requirements.txt
python tools/validate.py data --base origin/main
python -m unittest discover tools
python tools/render.py data _site     # then open _site/index.html
```

## For maintainers

- **Issues to pull requests.** A correction or missing-role issue becomes a `contributed`
  entry, with the issue linked in `sources`. A confirmation adds the issue to the entry's
  `confirmations`. A report that someone was never a chair adds them to the group's
  `rejected` list.
- **Review.** The checks catch malformed data and missing sources; reviewers judge whether
  the sources support the claim.
- **Reseeding.** Run `python tools/reseed.py <seed dir> data` rather than replacing `data/`.
  It keeps contributed entries, confirmations, rejections, overrides, and groups and people
  the datatracker doesn't know about; it never deletes a file that carries a contribution,
  and prints what it kept or could not match. It merges a contributed group into the
  datatracker's once the datatracker has it. If a contributed group's acronym turns out to
  belong to a different datatracker group, it stops and says so: rename the contributed file
  and run it again. Each seed carries a manifest saying how it was made.
- **Publishing.** Merging to `main` rebuilds the site and deploys it to GitHub Pages.
- **Setup.** Enable Pages with "GitHub Actions" as the source. Create the labels
  `correction`, `confirmation`, `missing` and `missing-group`, which the issue forms apply.

## Where the seed came from

`data/` is seeded by an extraction that reads public IETF records and weighs them together:

- the datatracker: group history snapshots, logged chair changes, group state changes,
  meeting session requests (2006–2011) and sessions, document shepherd assignments, and
  IESG roles;
- WG Action and WG Review announcements on ietf-announce and ietf-announce-old;
- the groups' own public mailing lists: messages announcing chairs joining or leaving, last
  calls and adoption calls the chairs started, and chair lists in posted minutes;
- the meeting proceedings since IETF 29: each group's charter snapshot, the chair lists in
  minutes published there, and the BOF sessions they show;
- the IETF's list of past IESG members, for when people became Area Directors (who usually
  stop chairing then).

Only lists whose archives are public are read, and no email addresses are published. Each
date says what it rests on, under "How the dates were set". Roles with good evidence but no
datatracker record are listed as `unconfirmed`.
