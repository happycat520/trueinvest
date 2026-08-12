# Publishing a new research article

Articles are written in Markdown and turned into site pages by a script —
you never hand-edit HTML.

## 1. Write the article

Create a new file in `content/articles/`, e.g. `content/articles/why-margins-matter.md`:

```markdown
---
title: Why Margins Matter
date: 2026-09-02
deck: One or two sentences — this is what shows up on the preview card.
tags: [Fundamentals]
---

Your article body goes here, written in plain Markdown.

## A heading

More paragraphs, lists, **bold**, *italics*, and > blockquotes all work.
```

Required frontmatter fields: `title`, `date` (YYYY-MM-DD), `deck`.
Optional: `tags` (a list, shown as filter chips), `slug` (defaults to a
slugified title), `author` (defaults to "CrystalWell Analytics").

## 2. Run the publish script

```
pip install markdown --break-system-packages   # one-time setup
python3 scripts/new_article.py content/articles/why-margins-matter.md
```

This writes `research/why-margins-matter.html` (styled to match the rest of
the site) and adds the article to `data/articles.json`. That's the only
file the Research page and homepage preview read from, so the new article
appears in both automatically — no other files need to change.

## 3. Re-publishing / edits

Edit the `.md` file and re-run the same command. It regenerates the HTML
page and updates its `articles.json` entry in place (matched by slug).

## Notes

- `content/articles/` holds your Markdown source — keep these; they're the
  editable originals. `research/*.html` is generated output.
- If you'd rather write in Word, save as `.docx` and export/paste into
  Markdown first (or ask me to convert it) — the script only reads `.md`.
