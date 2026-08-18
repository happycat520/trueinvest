# Publishing a new research article

Articles are written in Word (.docx) and turned into site pages by a
script — you never hand-edit HTML.

## 1. Write the article

Create a new `.docx` file in `content/articles/`, e.g.
`content/articles/why-margins-matter.docx`, following this structure:

```
Heading 1:   Why Margins Matter
Paragraph:   CrystalWell Analytics                 (bold)
             September 2, 2026                     (bold, on its own line)
Heading 3:   Summary
Paragraph:   One or two sentences. The first sentence becomes the preview
             card description automatically; the whole Summary section
             stays in the published article as the lead-in.

...the rest of the article: Heading 2 / Heading 3 sections and body text...

Paragraph (optional, italic): the standard disclaimer, if you want it to
             read exactly as written rather than the site's default.
```

`The_CrystalWell_Investment_Framework.docx` and
`When_Insider_Buying_Actually_Matters.docx` in this folder are real
examples — duplicate one and edit it if you're not sure about formatting.

## 2. Run the publish script

```
pip install beautifulsoup4 --break-system-packages   # one-time setup
python3 scripts/new_article.py content/articles/why-margins-matter.docx --tags "Fundamentals"
```

`--tags` is required for a brand-new article (comma-separated, shown as
filter chips on the Research page). This writes
`research/why-margins-matter.html` (styled to match the rest of the site)
and adds the article to `data/articles.json`. That's the only file the
Research page and homepage preview read from, so the new article appears
in both automatically — no other files need to change.

## 3. Re-publishing / edits

Edit the `.docx` file and re-run the same command, passing `--slug` with
the article's existing slug so the URL doesn't change:

```
python3 scripts/new_article.py content/articles/why-margins-matter.docx --slug why-margins-matter
```

`--tags` can be omitted on an update — the previous tags carry over
automatically. It regenerates the HTML page and updates the
`articles.json` entry in place (matched by slug).

## Notes

- `content/articles/` holds your `.docx` source — keep these; they're the
  editable originals. `research/*.html` is generated output — don't
  hand-edit it, since the next publish run will overwrite it.
- The publish date must be a bold line formatted like `September 2, 2026`
  somewhere between the title and the first section heading.
- Always pass `--slug` when updating an already-published article, even
  if the title changed — the slug is what keeps the URL (and every link
  to it elsewhere on the site) working.
