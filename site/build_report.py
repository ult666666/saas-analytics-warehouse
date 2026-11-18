"""Publish the generated Markdown report and just the chart files it references."""

import argparse
import re
import shutil
from html import escape
from pathlib import Path
from string import Template

from markdown_it import MarkdownIt
from markdown_it.token import Token

SITE = Path(__file__).resolve().parent


def publish(report: Path, output: Path) -> None:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(report.read_text(encoding="utf-8"))
    if len(tokens) < 3 or tokens[0].type != "heading_open" or tokens[0].tag != "h1":
        raise ValueError("The report needs a title")
    title = tokens[1].content
    tokens = tokens[3:]
    section_id = ""
    sections: list[tuple[str, str]] = []
    figures: set[str] = set()
    annotated: list[Token] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2":
            heading = tokens[index + 1].content
            section_id = "-".join(re.findall(r"[a-z0-9]+", heading.lower()))
            token.attrSet("id", section_id)
            sections.append((section_id, re.split(r",| \(", heading, maxsplit=1)[0]))
        if token.type == "table_open":
            wrapper = Token("html_block", "", 0)
            wrapper.content = (
                f'<div class="table-scroll" role="region" '
                f'aria-labelledby="{section_id}" tabindex="0">\n'
            )
            annotated.append(wrapper)
        if token.type == "th_open":
            token.attrSet("scope", "col")
        if token.type == "td_open" and tokens[index - 1].type == "tr_open":
            # Markdown tables emit open, inline content, close for each cell.
            token.tag = tokens[index + 2].tag = "th"
            token.attrSet("scope", "row")
        for child in token.children or []:
            if child.type == "image":
                source = child.attrGet("src") or ""
                if not re.fullmatch(r"figures/[a-z0-9_]+\.png", source):
                    raise ValueError(f"Unexpected report image {source!r}")
                figures.add(source)
        annotated.append(token)
        if token.type == "table_close":
            end = Token("html_block", "", 0)
            end.content = "</div>\n"
            annotated.append(end)
    if not sections:
        raise ValueError("The report needs at least one section")
    nav = "\n".join(f'<li><a href="#{key}">{escape(label)}</a></li>' for key, label in sections)
    page = Template((SITE / "report.html").read_text(encoding="utf-8")).substitute(
        title=escape(title),
        sections=nav,
        report=parser.renderer.render(annotated, parser.options, {}),
    )
    output.mkdir(parents=True, exist_ok=True)
    for source in sorted(figures):
        target = output / source
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(report.parent / source, target)
    shutil.copyfile(SITE / "report.css", output / "report.css")
    (output / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("report", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    publish(args.report, args.output)
