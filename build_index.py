"""Index generator: scan suburbs/*.json (via lint.py's list_metros) and
write _site/index.html linking to each metro's comparison page. Manual,
on-demand step -- not auto-triggered after every evaluation, same "no
auto-refresh" discipline as reloeval's build_index.py.
"""
from __future__ import annotations

import html
from pathlib import Path

from lint import list_metros
from models import MetroRecord

SITE_DIR = Path(__file__).parent / "_site"
INDEX_PATH = SITE_DIR / "index.html"

_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Burbeval</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }}
  h1 {{ font-size: 1.4rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 10px 0; border-bottom: 1px solid #ddd; }}
  a {{ text-decoration: none; font-weight: 600; }}
  .empty {{ color: #666; }}
</style>
</head>
<body>
<h1>Burbeval &mdash; Suburb Comparisons</h1>
{body}
</body>
</html>
"""


def build_index(metros: list[MetroRecord]) -> str:
    metros = sorted(metros, key=lambda m: m.metro_label)
    if not metros:
        body = '<p class="empty">No metros evaluated yet.</p>'
    else:
        items = []
        for m in metros:
            site_file = SITE_DIR / f"{m.metro_slug}.html"
            label = html.escape(m.metro_label)
            href = f"{m.metro_slug}.html" if site_file.exists() else "#"
            items.append(f'<li><a href="{href}">{label}</a> &mdash; {len(m.suburbs)} suburbs</li>')
        body = "<ul>\n" + "\n".join(items) + "\n</ul>"
    return _TEMPLATE.format(body=body)


if __name__ == "__main__":
    SITE_DIR.mkdir(exist_ok=True)
    html_content = build_index(list_metros())
    INDEX_PATH.write_text(html_content)
    print(f"Wrote {INDEX_PATH}")
