# 0007. Render résumé PDFs with WeasyPrint, not a headless browser

**Status:** Accepted — 2026-09-23.

## Context

The Resume Advisor exports a résumé as a white, printable PDF in one of three
templates (domain section 2.9: export is presentation, not a domain rule).
`docs/technical_boundaries.md` planned Playwright for this, rendering on the
worker's `docs` queue.

Playwright means a headless Chromium in the worker image. That is roughly
400 MB more image, a browser that `make scan` then reports on with every
Chromium CVE, a JavaScript engine executing inside the worker, and a process
that wants a writable home and a sandbox the non-root, read-only worker does
not give it. The documents we render are ours: one HTML page, built from the
résumé's own fields, with no scripts and no external resources.

## Decision

Résumé PDFs are rendered by **WeasyPrint** (HTML and CSS to PDF, in Python),
on the worker's `docs` queue.

- `modules/resume/infra/render.py` builds the page: every value HTML-escaped,
  three templates taken from the prototype's `tplDef`, a white A4 page. Fonts
  are DejaVu, installed from Debian, so nothing is fetched to render.
- Its URL fetcher refuses every URL, so even a résumé that somehow contained a
  link to an internal address could not make the renderer reach it.
- The base image installs Pango, HarfBuzz-Subset and the DejaVu fonts, pinned to
  the versions bookworm ships; `weasyprint` is a locked Python dependency.
- The PDF goes to object storage under the user's prefix, and the page gets a
  short-lived signed link, like uploaded résumés.

## Consequences

Easier:
- No browser in the image, and no JavaScript engine running on user content.
  WeasyPrint and its system libraries add a few tens of megabytes.
- Renders in-process, as the worker's non-root user, with nothing writable
  beyond `/tmp`.
- Unit tests render a real PDF hermetically, because nothing is fetched.

Harder:
- WeasyPrint's CSS is a print-focused subset. Layouts that depend on a browser
  (JavaScript, some flexbox and grid behaviour) will not render the same, so a
  template has to be written for WeasyPrint rather than copied from the SPA.
- The exported page is set in DejaVu, not the prototype's Caprasimo and Figtree:
  the templates' colours and rules match the prototype, the type does not.
- Three more system packages to keep pinned and re-pin when the base image
  moves to a new Debian release.

## Alternatives considered

- **Playwright with headless Chromium, as planned.** Lost on image size, scan
  noise, and running a browser engine in the worker for a static page.
- **Render in the browser (print to PDF from the SPA).** Lost because the output
  would vary with the user's browser and printer settings, and the white,
  template-exact PDF is the point of export.
- **A PDF drawing library (ReportLab).** Lost because the layout would be code
  rather than HTML and CSS, so the templates could not follow the page the user
  already sees.
