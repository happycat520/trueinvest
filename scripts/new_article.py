#!/usr/bin/env python3
"""
new_article.py — publish a CrystalWell research article from a Word (.docx) file.

Usage:
    python3 scripts/new_article.py content/articles/my-new-piece.docx --tags "Framework,Philosophy"

    # updating an already-published article — keep its existing slug/URL:
    python3 scripts/new_article.py content/articles/my-new-piece.docx --slug my-investment-framework

Required layout of the .docx (see content/articles/*.docx for examples):

    Heading 1:  Article title
    Paragraph (bold): CrystalWell Analytics
    Paragraph (bold): Month D, YYYY            <- publish date, human format
    Heading 3:  Summary
    Paragraph(s): 1–3 sentence summary          <- first sentence becomes the
                                                    card/preview "deck"; the
                                                    whole Summary section stays
                                                    in the published article.
    ...rest of the article (Heading 2 / Heading 3 sections, body text)...
    Paragraph (italic, optional): standard disclaimer
        (if omitted, the site's standard disclaimer is appended automatically —
        either way only one disclaimer will appear in the final page)

Flags:
    --tags "Tag One,Tag Two"   Required for a brand-new article. Optional when
                                updating an existing one — the previous tags
                                carry over automatically if you omit it.
    --slug custom-slug         Use this instead of slugifying the title. Always
                                pass this when revising an already-published
                                article, so its URL doesn't change.
    --author "Name"            Defaults to "CrystalWell Analytics".

What it does:
  1. Converts the .docx to HTML with pandoc and parses out title / date /
     summary / body / (optional) disclaimer.
  2. Writes research/<slug>.html using the site's article template.
  3. Adds (or updates) the article's entry in data/articles.json, so it
     shows up on the Research page and the homepage automatically.

Requires: pandoc (system binary) and beautifulsoup4 (pip install beautifulsoup4 --break-system-packages)
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    sys.exit("Missing dependency. Run: pip install beautifulsoup4 --break-system-packages")

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "research"
ARTICLES_JSON = ROOT / "data" / "articles.json"

DISCLAIMER = (
    "CrystalWell Analytics publishes independent investment research and "
    "educational content. This material is provided for informational and "
    "educational purposes only and does not constitute investment advice, an "
    "offer, or a recommendation to buy or sell any security. Investing "
    "involves risk, including the possible loss of principal."
)

DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")

ARTICLE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | CrystalWell Analytics</title>
<meta name="description" content="{deck}">
<link rel="stylesheet" href="../css/styles.css">
</head>
<body>

<nav class="site-nav">
  <div class="container">
    <a href="../index.html" class="brand">
      <span class="facet-mark">
        <svg width="26" height="26" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <polygon points="16,2 29,11 16,15" fill="#3577c9"/>
          <polygon points="16,2 3,11 16,15" fill="#245fa8"/>
          <polygon points="3,11 16,15 16,30" fill="#173a68"/>
          <polygon points="29,11 16,15 16,30" fill="#0d1b32"/>
          <line x1="16" y1="2" x2="16" y2="30" stroke="#e4d3ab" stroke-width="0.6" opacity="0.7"/>
        </svg>
      </span>
      CrystalWell
    </a>
    <button class="nav-toggle" aria-label="Toggle navigation" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    </button>
    <div class="nav-links">
      <a href="../framework.html">Framework</a>
      <a href="../research.html" class="active">Research</a>
      <a href="../dashboard.html">Dashboard</a>
      <a href="../contact.html">Contact</a>
    </div>
    <div class="nav-cta">
      <a href="../contact.html#digest" class="btn btn-primary btn-sm">Get the Daily Digest</a>
    </div>
  </div>
</nav>

<header class="article-header">
  <div class="container">
    <a class="back-link" href="../research.html">← All research</a>
    <span class="eyebrow">{tags_eyebrow}</span>
    <h1>{title}</h1>
    <div class="article-meta">By {author} · {date_display}</div>
  </div>
</header>

<div class="container">
<article class="article-body">
{body_html}
</article>

<div class="article-footer">
  <p class="article-disclaimer">{disclaimer}</p>
</div>
</div>

<footer class="site-footer">
  <div class="container">
    <div class="footer-bottom" style="margin-top:0; border-top:none; padding-top:0;">
      <span>© {year} CrystalWell Analytics LLC. All rights reserved.</span>
      <a href="../research.html" style="color:var(--blue-400);">← Back to Research</a>
    </div>
  </div>
</footer>

<script src="../js/main.js"></script>
</body>
</html>
"""


def slugify(title):
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_docx(docx_path):
    """Convert docx -> HTML via pandoc, then split into title / date / deck / body / disclaimer."""
    result = subprocess.run(
        ["pandoc", "-f", "docx", "-t", "html5", "--wrap=none", str(docx_path)],
        capture_output=True, text=True, check=True,
    )
    soup = BeautifulSoup(result.stdout, "html.parser")
    top_level = [el for el in soup.contents if not isinstance(el, NavigableString)]

    if not top_level or top_level[0].name != "h1":
        sys.exit("Article must start with a Heading 1 title in the .docx.")
    title_tag = top_level.pop(0)
    title = title_tag.get_text(strip=True)

    # Metadata paragraphs (author / date) sit between the title and the next
    # heading. Pull a date out of them; anything else is ignored unless it's
    # meant to override the default author (handled via --author instead).
    date_display_val = None
    while top_level and top_level[0].name not in ("h2", "h3"):
        para = top_level.pop(0)
        # Author and date are often on separate lines within the same
        # paragraph (a Word soft line-break), so split on those rather
        # than treating the whole paragraph as one string.
        for line in para.get_text("\n", strip=True).split("\n"):
            if DATE_RE.match(line.strip()):
                date_display_val = line.strip()

    if date_display_val is None:
        sys.exit("Could not find a publish date (expected a bold paragraph like 'July 24, 2026' "
                  "before the first section heading).")

    # Deck = first sentence of the Summary section, if present.
    deck = None
    if top_level and top_level[0].name == "h3" and top_level[0].get_text(strip=True).lower() == "summary":
        summary_para = None
        for el in top_level[1:]:
            if el.name == "p":
                summary_para = el
                break
            if el.name in ("h2", "h3"):
                break
        if summary_para:
            summary_text = summary_para.get_text(" ", strip=True)
            match = re.search(r"^.*?[.!?](?=\s|$)", summary_text)
            deck = (match.group(0) if match else summary_text[:220]).strip()

    if deck is None:
        sys.exit("Could not find a '### Summary' section with a lead paragraph to use as the "
                 "card/preview description.")

    # Strip a trailing italic disclaimer paragraph if the author included one —
    # the template supplies the standard disclaimer, so we don't want it twice.
    disclaimer_pattern = re.compile(r"CrystalWell Analytics publishes independent investment research")
    if top_level and top_level[-1].name == "p":
        last_text = top_level[-1].get_text(" ", strip=True)
        if disclaimer_pattern.search(last_text):
            top_level.pop()

    body_html = "\n".join(str(el) for el in top_level)
    return title, date_display_val, deck, body_html


def main():
    parser = argparse.ArgumentParser(description="Publish a CrystalWell research article from a .docx file.")
    parser.add_argument("docx_path", type=Path)
    parser.add_argument("--tags", help="Comma-separated tags, e.g. 'Framework,Philosophy'")
    parser.add_argument("--slug", help="URL slug. Required to stay the same when updating a published article.")
    parser.add_argument("--author", default="CrystalWell Analytics")
    args = parser.parse_args()

    if not args.docx_path.exists():
        sys.exit(f"File not found: {args.docx_path}")

    title, date_disp, deck, body_html = parse_docx(args.docx_path)
    slug = args.slug or slugify(title)

    articles = json.loads(ARTICLES_JSON.read_text(encoding="utf-8")) if ARTICLES_JSON.exists() else []
    existing = next((a for a in articles if a.get("slug") == slug), None)

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else (existing["tags"] if existing else None)
    if not tags:
        sys.exit("New article: --tags is required, e.g. --tags \"Framework,Philosophy\"")

    iso_date = datetime.strptime(date_disp, "%B %d, %Y").strftime("%Y-%m-%d")

    html = ARTICLE_TEMPLATE.format(
        title=title,
        deck=deck,
        tags_eyebrow=" · ".join(tags),
        author=args.author,
        date_display=date_disp,
        body_html=body_html,
        disclaimer=DISCLAIMER,
        year=iso_date[:4],
    )

    RESEARCH_DIR.mkdir(exist_ok=True)
    out_path = RESEARCH_DIR / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path.relative_to(ROOT)}")

    articles = [a for a in articles if a.get("slug") != slug]
    articles.append({
        "slug": slug,
        "title": title,
        "date": iso_date,
        "deck": deck,
        "tags": tags,
        "url": f"research/{slug}.html",
    })
    ARTICLES_JSON.write_text(json.dumps(articles, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {ARTICLES_JSON.relative_to(ROOT)} ({len(articles)} articles)")


if __name__ == "__main__":
    main()
