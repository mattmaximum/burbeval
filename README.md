# Burbeval

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

Early build. Suburb enumeration (`census.py`) is live and tested against real
Census TIGERweb data — no API key required for that part. Fetching
population/demographics requires a free Census API key
(`CENSUS_API_KEY` — sign up at https://api.census.gov/data/key_signup.html).

## License

[MIT](LICENSE) — same as reloeval.
