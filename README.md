# Burbeval

> **⚠️ Draft / experimental.** This is an early, unfinished build — no live
> evaluation has run yet (still needs `CENSUS_API_KEY` and `OPENROUTER_API_KEY`
> configured as repo secrets), and two fields render as "unresolved" by design
> until they're fixed (see Status below). Expect rough edges.

**Live site:** https://mattmaximum.github.io/burbeval/ (empty until the first
metro is evaluated)

**This is a personal project**, sibling to
[reloeval](https://github.com/mattmaximum/reloeval), built to compare the suburbs
of a metro area for a real family relocation decision. Where reloeval researches
one city in depth, this tool researches an entire metro's suburbs at once and
ranks them side by side — the "which of these should we actually pick" version
of the same research problem.

Like reloeval, this is **not currently open to contributions** and running it
against your own data isn't supported — see reloeval's README for why (cost,
attribution, no multi-tenant support).

## What it does

Given a metro's core city ("Boise, ID"), this enumerates every suburb in that
city's county (or counties — Ada + Canyon for Treasure Valley) and produces one
comparison page ranking them on population, growth, commute time, crime,
demographics, weather, and amenities (retail, mountain biking, pickleball, rec
centers, schools with ratings), plus a thin pass on grid reliability and water
source. Every suburb gets a **Family Fit** score; v1 uses an equal-weighted,
percentile-rank-normalized default (personalized weighting is a planned second
pass).

Objective fields (suburb list, population, demographics, commute time, growth,
amenity distances) come from real public APIs — Census Places/TIGERweb, Census
ACS, Overpass/OpenStreetMap — not LLM guessing, so there's no citation-
fabrication risk on the fields that matter most: which places exist, and how
big the differences between them actually are. Fields with no clean API (crime
narrative, school ratings, weather, self-sufficiency) come from an LLM
structured-output call, same pattern as reloeval, with the same citation and
low-confidence-caveat discipline.

Full design rationale — including three rounds of adversarial review and an
independent cross-model challenge — lives in the design doc this project
started from (see `git log` on the first commit for the design session).

## Status

Early build, not yet run for real. The full pipeline (enumeration, Census,
Overpass, LLM fetch, scoring, rendering, lint, and the GitHub Actions
Issue→Pages workflow) is built and unit-tested, and GitHub Pages is enabled,
but no metro has actually been evaluated yet:

- Needs `CENSUS_API_KEY` (free — https://api.census.gov/data/key_signup.html)
  and `OPENROUTER_API_KEY` added as repo secrets before a real run can happen.
- `growth_rate` (Building Permits Survey) and `commute_time_min` (wrong ACS
  variable caught during build, not yet fixed) intentionally render
  "unresolved" rather than a wrong or placeholder number.
- Suburb enumeration (`census.py`) itself is live-tested against real Census
  TIGERweb data and needs no API key.

## License

[MIT](LICENSE) — same as reloeval.
