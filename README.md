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

- **person**: the datatracker person id. For someone with no datatracker record, use
  `person: null` and give `name`. Anyone new must also be added to `data/people.yaml`
  with their `id`, `name` and `uuid`: the primary UUID from their datatracker profile
  address (`https://datatracker.ietf.org/person/<uuid>`). The site names each person's
  page by that UUID.
- **status**: `confirmed` (from datatracker records), `unconfirmed` (suggested by indirect
  evidence), or `contributed` (added or corrected by a contributor).
- **periods**: one per stretch as chair. Dates are `YYYY-MM-DD`, `YYYY-MM` or `YYYY`.
  Each start and end has a `certainty`:

  | certainty | meaning | fields |
  |---|---|---|
  | `exact` | recorded when the change was made | `date` |
  | `approximate` | close, but not precisely recorded | `date` |
  | `on-or-before` | the earliest record; may have started earlier | `date`, optional `not_before` |
  | `between` | sometime in a range | `not_before`, optional `not_after` |
  | `group-closed` | still chair when the group closed (ends only) | `date` |
  | `evidence-only` | dated only by evidence (start: `not_after`; end: `not_before`) | as noted |
  | `ongoing` | current chair (ends only) | none |

- **sources**: required on any entry a pull request adds or changes. Links or citations.
- **evidence**: written by the seed extraction (announcements, session requests, documents
  shepherded). Leave it as it is.

Checks run on every pull request. To run them yourself:

```sh
pip install -r requirements.txt
python tools/validate.py data --base origin/main
python -m unittest discover tools
python tools/render.py data _site     # then open _site/index.html
```

## For maintainers

- **Issues to pull requests.** Each correction, confirmation or missing-role issue becomes
  an edit to the group's file, with the issue linked in `sources`. A confirmation of an
  `unconfirmed` entry changes its status to `contributed`.
- **Review.** The checks catch malformed data and missing sources; reviewers judge whether
  the sources support the claim.
- **Publishing.** Merging to `main` rebuilds the site and deploys it to GitHub Pages.
- **Setup.** Enable Pages with "GitHub Actions" as the source. Create the labels
  `correction`, `confirmation` and `missing`, which the issue forms apply.

## Where the seed came from

The first version of `data/` was extracted from the datatracker: group history snapshots,
logged chair changes, group state changes, WG Action and WG Review announcements, session
requests (2006–2011) and document shepherd assignments. Roles with strong evidence but no
datatracker record are listed as `unconfirmed`.
