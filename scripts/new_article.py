#!/usr/bin/env python3
"""
new_article.py — publish a CrystalWell research article from Markdown.

Usage:
    python3 scripts/new_article.py content/articles/my-new-piece.md

What it does:
  1. Reads the Markdown file's frontmatter (title, date, deck, tags, slug).
  2. Converts the Markdown body to HTML.
  3. Writes research/<slug>.html using the site's article template.
  4. Adds (or updates) the article's entry in data/articles.json, so it
     shows up on the Research page and the homepage automatically.

Requires the `markdown` package: pip install markdown --break-system-packages

Markdown file format:

    ---
    title: My New Piece
    date: 2026-08-20
    deck: One or two sentences for the preview card.
    tags: [Framework, Signals]
    ---

    Article body in Markdown goes here...
"""
import json
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("Missing dependency. Run: pip install markdown --break-system-packages")

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "research"
ARTICLES_JSON = ROOT / "data" / "articles.json"

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
      <a href="../research.html" class="active">Research</a>
      <a href="../dashboard.html">Dashboard</a>
      <a href="../index.html#philosophy">Philosophy</a>
      <a href="../index.html#process">Process</a>
      <a href="../index.html#about">About</a>
    </div>
    <div class="nav-cta">
      <a href="../index.html#newsletter-contact" class="btn btn-primary btn-sm">Join the newsletter</a>
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
  <p class="article-disclaimer">This article is independent commentary published for educational purposes only and does not constitute personalized investment advice or a recommendation to buy or sell any security. Investing involves risk, including loss of principal.</p>
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


def parse_frontmatter(text):
    if not text.startswith("---"):
        sys.exit("Markdown file must start with a '---' frontmatter block.")
    _, fm_text, body = text.split("---", 2)
    meta = {}
    for line in fm_text.strip().splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
        else:
            meta[key] = val.strip("\"'")
    return meta, body.lstrip("\n")


def slugify(title):
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def date_display(iso_date):
    from datetime import datetime
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else iso_date
    except Exception:
        return iso_date


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 scripts/new_article.py path/to/article.md")

    md_path = Path(sys.argv[1])
    if not md_path.exists():
        sys.exit(f"File not found: {md_path}")

    raw = md_path.read_text(encoding="utf-8")
    meta, body_md = parse_frontmatter(raw)

    required = ["title", "date", "deck"]
    missing = [k for k in required if k not in meta]
    if missing:
        sys.exit(f"Missing required frontmatter field(s): {', '.join(missing)}")

    title = meta["title"]
    date = meta["date"]  # expects YYYY-MM-DD
    deck = meta["deck"]
    tags = meta.get("tags", [])
    slug = meta.get("slug") or slugify(title)
    author = meta.get("author", "CrystalWell Analytics")

    body_html = markdown.markdown(body_md, extensions=["extra", "smarty"])

    html = ARTICLE_TEMPLATE.format(
        title=title,
        deck=deck,
        tags_eyebrow=" · ".join(tags) if tags else "Research",
        author=author,
        date_display=date_display(date),
        body_html=body_html,
        year=date[:4] if len(date) >= 4 else "2026",
    )

    RESEARCH_DIR.mkdir(exist_ok=True)
    out_path = RESEARCH_DIR / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path.relative_to(ROOT)}")

    articles = json.loads(ARTICLES_JSON.read_text(encoding="utf-8")) if ARTICLES_JSON.exists() else []
    articles = [a for a in articles if a.get("slug") != slug]
    articles.append({
        "slug": slug,
        "title": title,
        "date": date,
        "deck": deck,
        "tags": tags,
        "url": f"research/{slug}.html",
    })
    ARTICLES_JSON.write_text(json.dumps(articles, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {ARTICLES_JSON.relative_to(ROOT)} ({len(articles)} articles)")


if __name__ == "__main__":
    main()
