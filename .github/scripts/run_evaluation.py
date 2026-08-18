"""CI entrypoint for the evaluate-metro workflow.

Same shape as reloeval's run_evaluation.py: distinguishes outcomes via
exit code so the workflow can post a different comment and decide
whether to deploy/close the issue for each.

  0 - success, gap rate acceptable
  2 - MetroNotFoundError / MetroConfigError (issue title doesn't match a
      metros.json entry, or metros.json itself is malformed)
  3 - excessive gap rate (>=90% unresolved/missing/flagged) -- looks like
      a misconfigured API key, not a normal per-field gap
  1 - any other pipeline failure

Writes `slug`, `gap_summary`, and `error_message` to $GITHUB_OUTPUT.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evaluate import MetroNotFoundError, evaluate_metro
from lint import find_gaps_for_suburb, list_metros
from metros import MetroConfigError, slugify_metro
from models import fetchable_fields, load_schema

GAP_FAILURE_THRESHOLD = 0.90


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"[output] {name}={value}")
        return
    with open(output_path, "a") as f:
        if "\n" in value:
            f.write(f"{name}<<EOF\n{value}\nEOF\n")
        else:
            f.write(f"{name}={value}\n")


async def _main(issue_title: str) -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        write_output("error_message", "OPENROUTER_API_KEY is not set.")
        return 1
    if not os.environ.get("CENSUS_API_KEY"):
        write_output("error_message", "CENSUS_API_KEY is not set.")
        return 1

    metro_slug = slugify_metro(issue_title)

    try:
        slug = await evaluate_metro(metro_slug)
    except (MetroNotFoundError, MetroConfigError) as e:
        write_output("error_message", str(e))
        return 2
    except Exception as e:
        write_output("error_message", f"{type(e).__name__}: {e}")
        return 1

    write_output("slug", slug)

    schema = load_schema()
    metros = {m.metro_slug: m for m in list_metros()}
    record = metros[slug]

    total = sum(len(fetchable_fields(schema, key)) for key in schema["categories"]) * max(len(record.suburbs), 1)
    gap_count = 0
    gap_lines = []
    for suburb_slug, suburb in record.suburbs.items():
        gaps = find_gaps_for_suburb(schema, suburb.categories)
        for category_key, fields in gaps.items():
            for field_key, reason in fields.items():
                gap_count += 1
                gap_lines.append(f"- [{reason}] {suburb_slug}.{category_key}.{field_key}")

    gap_rate = (gap_count / total) if total else 0.0
    if gap_rate >= GAP_FAILURE_THRESHOLD:
        write_output(
            "error_message",
            f"{gap_count}/{total} fields ({gap_rate:.0%}) came back unresolved/missing/"
            "flagged -- this looks like a misconfigured or invalid API key, not a "
            "normal per-field gap. Check the repo secrets.",
        )
        return 3

    if gap_count:
        write_output("gap_summary", f"{gap_count}/{total} fields still need a backfill:\n" + "\n".join(gap_lines[:20]))
    else:
        write_output("gap_summary", "All fields valid and up to date.")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python run_evaluation.py "City, ST"', file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(_main(sys.argv[1])))
