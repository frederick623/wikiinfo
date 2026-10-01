import argparse
import os
import re
import time
from pathlib import Path

import wikipediaapi
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types


load_dotenv()

IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
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

RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}


def create_client() -> genai.Client:
    """Create a Gemini client from the GEMINI_API_KEY environment variable."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY before running this program.")
    return genai.Client(api_key=api_key)


def section_text(section) -> str:
    """Combine a top-level section with the text of all its subsections."""
    parts = [section.text]
    parts.extend(section_text(child) for child in section.sections)
    return "\n\n".join(part.strip() for part in parts if part.strip())


def fetch_wikipedia_sections(title: str) -> list[tuple[str, str]]:
    """Fetch the complete lead and meaningful top-level article sections."""
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
        sections.append((title, page.summary.strip()))
    for section in page.sections:
        text = section_text(section)
        if section.title not in SKIPPED_SECTIONS and text:
            sections.append((section.title, text))

    if not sections:
        raise ValueError(f"Wikipedia page '{title}' has no usable content.")
    return sections


def build_infographic_prompt(
    article_title: str,
    section_title: str,
    section_content: str,
) -> str:
    """Build an image prompt containing the complete Wikipedia section."""
    title_instruction = (
        f'Keep the exact title "{article_title}" visible as the primary and only title.'
        if section_title == article_title
        else (
            f'Keep the exact article title "{article_title}" visible as the primary '
            f'title and the exact section title "{section_title}" as a subordinate title.'
        )
    )
    return f"""
Create a polished standalone infographic from this Wikipedia section.

ARTICLE: {article_title}
SECTION: {section_title}
SOURCE TEXT:
---
{section_content}
---

Use only facts supported by the source text. Select at most five key facts so the
image remains readable. {title_instruction} Use a clear visual hierarchy,
relevant imagery or data visualization, an eye-catching color palette, a sans
serif font, and large legible typography. Do not include citations, URLs, facts
from other sections, or unsupported claims.
""".strip()


def generate_infographic_image(
    client: genai.Client,
    prompt: str,
    output_path: Path,
) -> None:
    """Send a complete section directly to the configured image model."""
    max_attempts = 4

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="3:4"),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
        except errors.ClientError as error:
            retryable = error.code in RETRYABLE_HTTP_CODES
            if not retryable or attempt == max_attempts:
                raise
            wait_seconds = 2 ** (attempt - 1)
            print(
                f"Gemini request failed with HTTP {error.code}. "
                f"Retrying in {wait_seconds}s "
                f"({attempt}/{max_attempts})..."
            )
            time.sleep(wait_seconds)
            continue
        except Exception as error:
            if attempt == max_attempts:
                raise
            wait_seconds = 2 ** (attempt - 1)
            print(
                f"Gemini request failed with {type(error).__name__}. "
                f"Retrying in {wait_seconds}s "
                f"({attempt}/{max_attempts})..."
            )
            time.sleep(wait_seconds)
            continue

        for part in response.parts or []:
            if part.inline_data:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                part.as_image().save(output_path)
                return

        if attempt == max_attempts:
            raise RuntimeError(
                f"The image model returned no image for '{output_path.stem}'."
            )

        wait_seconds = 2 ** (attempt - 1)
        print(
            "The image model returned no image payload. "
            f"Retrying in {wait_seconds}s ({attempt}/{max_attempts})..."
        )
        time.sleep(wait_seconds)


def safe_filename(value: str) -> str:
    """Convert a title to a stable, filesystem-safe filename."""
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "section"


def wiki_to_infographics(
    wiki_title: str,
    output_directory: Path,
    max_sections: int | None = None,
) -> list[Path]:
    """Generate one WebP infographic directly from each complete section."""
    client = create_client()
    sections = fetch_wikipedia_sections(wiki_title)
    if max_sections is not None:
        sections = sections[:max_sections]
    topic_directory = output_directory / safe_filename(wiki_title)

    output_paths = []
    print(f"Found {len(sections)} sections in '{wiki_title}'.")
    for index, (section_title, content) in enumerate(sections, start=1):
        output_path = topic_directory / (
            f"{index:02d}-{safe_filename(section_title)}.webp"
        )
        print(f"[{index}/{len(sections)}] Generating: {section_title}")
        prompt = build_infographic_prompt(wiki_title, section_title, content)
        generate_infographic_image(client, prompt, output_path)
        output_paths.append(output_path)
        print(f"Saved: {output_path}")

    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate WebP infographics directly from Wikipedia sections."
    )
    parser.add_argument("title", help="Wikipedia article title")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("infographics"),
        help="Parent directory for topic folders (default: infographics)",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=10,
        help="Generate only the first N sections (default: 10)",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    try:
        wiki_to_infographics(
            arguments.title,
            arguments.output_dir,
            arguments.max_sections,
        )
    except errors.ClientError as error:
        if error.code != 403:
            raise
        raise SystemExit(
            "Gemini API access was denied for the project linked to "
            "GEMINI_API_KEY. Use an eligible Google AI Studio project."
        ) from None


if __name__ == "__main__":
    main()