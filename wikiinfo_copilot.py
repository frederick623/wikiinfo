import argparse
import os
import re
import subprocess
from pathlib import Path

import wikipediaapi


DEFAULT_MODEL = "gpt-5.6-luna"
SKIPPED_SECTIONS = {
    "See also",
    "Notes",
    "Footnotes",
    "References",
    "Citations",
    "Bibliography",
    "Sources",
    "Works cited",
    "Further reading",
    "External links",
}


def section_text(section) -> str:
    """Combine a top-level section with the text of all its subsections."""
    parts = [section.text]
    parts.extend(section_text(child) for child in section.sections)
    return "\n\n".join(part.strip() for part in parts if part.strip())


def fetch_wikipedia_sections(title: str) -> list[tuple[str, str]]:
    """Fetch the article lead followed by meaningful top-level sections."""
    user_agent = os.getenv(
        "WIKIPEDIA_USER_AGENT",
        "WikiToInfographicBot/1.0 (contact@example.com)",
    )
    wiki = wikipediaapi.Wikipedia(user_agent=user_agent, language="en")
    page = wiki.page(title)

    if not page.exists():
        raise ValueError(f"Wikipedia page '{title}' does not exist.")

    sections = []
    if page.summary.strip():
        sections.append((title, page.summary.strip()[:5000]))
    for section in page.sections:
        text = section_text(section)
        if section.title not in SKIPPED_SECTIONS and text:
            sections.append((section.title, text[:5000]))

    if not sections:
        raise ValueError(f"Wikipedia page '{title}' has no usable content.")
    return sections


def build_infographic_prompt(
    article_title: str,
    section_title: str,
    section_content: str,
) -> str:
    """Create a constrained request for a standalone SVG infographic."""
    is_lead = section_title == article_title
    title_instruction = (
        f'The exact article title, "{article_title}", must be visible as the '
        "primary and only title."
        if is_lead
        else (
            f'The exact article title, "{article_title}", must be visible as the '
            f'primary title. Use the exact section title, "{section_title}", as a '
            "subordinate title."
        )
    )
    return f"""
Create one standalone, production-ready SVG infographic from this Wikipedia excerpt.

ARTICLE: {article_title}
SECTION: {section_title}
SOURCE TEXT:
---
{section_content}
---

Use only facts supported by the source text and choose at most five key facts.
{title_instruction} Do not mention other article sections. Create a clear visual
hierarchy with large legible typography, an appropriate data visualization or
illustration, and a restrained, high-contrast color palette. Make the SVG
self-contained: use only inline styles, shapes, paths, and text; do not reference
external fonts, images, or scripts.
Use a 1200 by 1600 viewBox. Return only valid SVG markup, beginning with <svg and
ending with </svg>, without Markdown fences or explanation.
""".strip()


def generate_svg(
    prompt: str,
    model: str,
    copilot_command: str,
) -> str:
    """Generate SVG markup through an authenticated GitHub Copilot CLI."""
    try:
        response = subprocess.run(
            [copilot_command, "-p", prompt, "--model", model],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "GitHub Copilot CLI is not installed. Install and authenticate the "
            "Copilot CLI, then run this script again."
        ) from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip() or str(error)
        raise RuntimeError(f"Copilot CLI failed: {message}") from error

    start = response.stdout.find("<svg")
    end = response.stdout.rfind("</svg>")
    if start == -1 or end == -1:
        raise RuntimeError("Copilot did not return a complete SVG document.")
    return response.stdout[start : end + len("</svg>")]


def safe_filename(value: str) -> str:
    """Convert a section title to a stable, filesystem-safe filename."""
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "section"


def wiki_to_infographics(
    wiki_title: str,
    output_directory: Path,
    model: str,
    copilot_command: str,
    max_sections: int | None = None,
) -> list[Path]:
    """Generate SVG infographics in a folder named after the Wikipedia topic."""
    sections = fetch_wikipedia_sections(wiki_title)
    if max_sections is not None:
        sections = sections[:max_sections]
    topic_directory = output_directory / safe_filename(wiki_title)

    output_paths = []
    for index, (section_title, content) in enumerate(sections, start=1):
        output_path = topic_directory / (
            f"{index:02d}-{safe_filename(section_title)}.svg"
        )
        print(f"[{index}/{len(sections)}] Generating: {section_title}")
        svg = generate_svg(
            build_infographic_prompt(wiki_title, section_title, content),
            model,
            copilot_command,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(svg, encoding="utf-8")
        output_paths.append(output_path)
        print(f"Saved: {output_path}")

    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SVG infographics with GitHub Copilot CLI."
    )
    parser.add_argument("title", help="Wikipedia article title")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("infographics-copilot"),
        help="Parent directory for topic-named SVG folders (default: infographics-copilot)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("COPILOT_MODEL", DEFAULT_MODEL),
        help=f"Copilot model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--copilot-command",
        default=os.getenv("COPILOT_COMMAND", "copilot"),
        help="Copilot CLI executable (default: copilot)",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        help="Generate only the first N sections (useful for testing CLI access)",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    wiki_to_infographics(
        arguments.title,
        arguments.output_dir,
        arguments.model,
        arguments.copilot_command,
        arguments.max_sections,
    )


if __name__ == "__main__":
    main()