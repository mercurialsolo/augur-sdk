"""Mirror raw ``.md`` alongside the built HTML + emit ``llms.txt`` /
``llms-full.txt`` so coding agents can consume the docs directly.

After plugins (notably ``include-markdown``) have processed each page,
this hook copies the resulting markdown into ``site_dir/<src_path>``
so every published HTML page has a sibling ``.md``. It also writes
an ``llmstxt.org``-style index at ``llms.txt`` and a single-file
concatenation at ``llms-full.txt`` at the root of the built site.

Wired via ``mkdocs.yml#/hooks``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# src_path -> processed markdown (post include-markdown).
_pages: dict[str, str] = {}
# src_path -> nav title.
_titles: dict[str, str] = {}
# src_paths in nav order.
_nav_order: list[str] = []


def on_page_markdown(markdown: str, *, page: Any, **_: Any) -> str:
    _pages[page.file.src_path] = markdown
    return markdown


def on_nav(nav: Any, **_: Any) -> Any:
    _titles.clear()
    _nav_order.clear()
    for item in nav.pages:
        src = item.file.src_path
        _titles[src] = item.title
        _nav_order.append(src)
    return nav


def on_post_build(*, config: Any, **_: Any) -> None:
    site_dir = Path(config["site_dir"])

    # 1. Mirror every page as raw .md alongside its HTML.
    for src_path, content in _pages.items():
        dest = site_dir / src_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    # 2. llms.txt index, grouped by first path segment.
    site_name = config.get("site_name") or "Docs"
    site_description = (config.get("site_description") or "").strip()

    groups: dict[str, list[str]] = {}
    for src in _nav_order:
        head = src.split("/", 1)[0] if "/" in src else "_root"
        groups.setdefault(head, []).append(src)

    lines: list[str] = [f"# {site_name}"]
    if site_description:
        lines += ["", f"> {site_description}"]
    lines += [
        "",
        "Raw markdown for every page on this site is mirrored alongside the",
        "HTML — fetch `<page>.md` instead of `<page>/` to get the canonical",
        "source. This file follows the [llms.txt](https://llmstxt.org/)",
        "convention so coding agents can discover the docs without scraping.",
        "See also `llms-full.txt` for a single-file concatenation.",
        "",
    ]

    group_order = ["_root"] + sorted(k for k in groups if k != "_root")
    for head in group_order:
        if head not in groups:
            continue
        section = "Overview" if head == "_root" else head.capitalize()
        lines += [f"## {section}", ""]
        for src in groups[head]:
            title = _titles.get(src, src)
            lines.append(f"- [{title}]({src})")
        lines.append("")

    (site_dir / "llms.txt").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8"
    )

    # 3. llms-full.txt — concatenated full content in nav order.
    full: list[str] = [f"# {site_name} — full documentation", ""]
    if site_description:
        full += [f"> {site_description}", ""]
    for src in _nav_order:
        title = _titles.get(src, src)
        body = _pages.get(src, "").rstrip()
        full += ["", "---", "", f"# {title}", "", f"_Source: `{src}`_", "", body, ""]
    (site_dir / "llms-full.txt").write_text(
        "\n".join(full).rstrip() + "\n", encoding="utf-8"
    )
