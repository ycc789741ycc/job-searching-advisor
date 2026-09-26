"""Résumé export: content to HTML to PDF (ADR 0007).

Export is presentation, not a domain rule (section 2.9): the template picks a
rule and a name colour, the page is white, and that is all. Every value is
escaped and nothing external is referenced — no fonts, images or stylesheets
are fetched — so a résumé's text can never make the renderer reach the
network. The grey source notes stay in the app; a résumé sent to a company does
not carry them.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from advisor.resume._domain import Options, ResumeContent, Template

# One page is what "trim" means; these keep the brief template on it.
_TRIMMED_BULLETS = 3
_TRIMMED_SKILLS = 12


@dataclass(frozen=True, slots=True)
class _Look:
    rule: str
    name_color: str
    dot: str


# The prototype's three templates (tplDef).
_LOOKS = {
    Template.WARM: _Look(rule="3px solid #c67139", name_color="#8a4a20", dot="#c67139"),
    Template.PLAIN: _Look(rule="1px solid #cfcac5", name_color="#201e1d", dot="#9b9691"),
    Template.BRIEF: _Look(rule="3px solid #7a8a5e", name_color="#4d5a35", dot="#7a8a5e"),
}


def render_html(content: ResumeContent, *, template: Template, options: Options) -> str:
    look = _LOOKS[template]
    skills = content.skills[:_TRIMMED_SKILLS] if options.trim else content.skills

    positions = []
    for position in content.experience:
        bullets = position.bullets[:_TRIMMED_BULLETS] if options.trim else position.bullets
        items = "".join(f"<li>{escape(b.text)}</li>" for b in bullets)
        positions.append(
            '<section class="job">'
            '<div class="job-head">'
            f'<span class="job-title">{escape(position.title)} — {escape(position.org)}</span>'
            f'<span class="job-when">{escape(position.when)}</span>'
            "</div>"
            f"<ul>{items}</ul>"
            "</section>"
        )

    skill_items = "".join(f'<span class="skill">{escape(s)}</span>' for s in skills)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(content.name)}</title>
<style>
@page {{ size: A4; margin: 18mm 17mm; }}
body {{ font-family: "DejaVu Sans", sans-serif; font-size: 10pt; color: #201e1d;
       background: #ffffff; line-height: 1.5; margin: 0; }}
header {{ border-bottom: {look.rule}; padding-bottom: 10pt; margin-bottom: 14pt; }}
h1 {{ font-family: "DejaVu Serif", serif; font-size: 22pt; line-height: 1.1;
     color: {look.name_color}; margin: 0; font-weight: normal; }}
.contact {{ font-size: 9.5pt; color: #5a5550; margin-top: 4pt; }}
h2 {{ font-size: 8.5pt; letter-spacing: 0.1em; text-transform: uppercase;
     font-weight: bold; color: {look.name_color}; margin: 14pt 0 6pt; }}
.summary {{ margin: 0; }}
.job {{ margin-bottom: 10pt; page-break-inside: avoid; }}
.job-head {{ display: flex; justify-content: space-between; gap: 12pt; }}
.job-title {{ font-family: "DejaVu Serif", serif; font-size: 11pt; }}
.job-when {{ font-size: 9pt; color: #6b6560; white-space: nowrap; }}
ul {{ margin: 4pt 0 0; padding-left: 12pt; }}
li {{ margin-bottom: 3pt; }}
li::marker {{ color: {look.dot}; }}
.skills {{ display: flex; flex-wrap: wrap; gap: 5pt; }}
.skill {{ font-size: 9pt; padding: 2pt 8pt; border-radius: 999px;
         background: #f3f1ee; color: #3d3a36; }}
</style></head>
<body>
<header>
<h1>{escape(content.name)}</h1>
<div class="contact">{escape(" · ".join(p for p in (content.headline, content.contact) if p))}</div>
</header>
<h2>Summary</h2>
<p class="summary">{escape(content.summary)}</p>
<h2>Experience</h2>
{"".join(positions)}
<h2>Skills</h2>
<div class="skills">{skill_items}</div>
</body></html>"""


def render_pdf(html: str) -> bytes:
    """Worker ``docs`` queue only: rendering is CPU and memory, never a request."""
    # Imported here so the api, which never renders, does not load Pango.
    from weasyprint import HTML
    from weasyprint.urls import FatalURLFetchingError, URLFetcher

    class NoFetching(URLFetcher):  # type: ignore[misc]
        """Nothing in a résumé should be fetched; anything that tries stops it."""

        def fetch(self, url: str, headers: object = None) -> object:
            raise FatalURLFetchingError(f"export does not fetch external resources: {url[:80]}")

    try:
        document = HTML(string=html, url_fetcher=NoFetching(fail_on_errors=True))
        return bytes(document.write_pdf())
    except FatalURLFetchingError as exc:
        raise ValueError(str(exc)) from exc
