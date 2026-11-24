import argparse
import json
import os
import re
import time
from pathlib import Path

import wikipediaapi
from dotenv import find_dotenv, load_dotenv
from google import genai
from google.genai import errors, types


# Search from the working directory, not site-packages, when installed.
load_dotenv(find_dotenv(usecwd=True))

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
BATCH_POLL_SECONDS = 15
DEFAULT_JOB_FILE = Path("job.json")
BATCH_DONE_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_PARTIALLY_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
}


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


def image_generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="3:4"),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def save_first_image(response: types.GenerateContentResponse, output_path: Path) -> bool:
    """Save the first image part of a response; return False if there is none."""
    for part in response.parts or []:
        if part.inline_data:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            part.as_image().save(output_path)
            return True
    return False


def generate_infographic_images_async(
    client: genai.Client,
    prompts: list[str],
    output_paths: list[Path],
) -> dict:
    """Submit a Gemini Batch API job without waiting; return a JSON-serializable job dict.

    Pass the dict to fetch_infographic_images() later, even from another process.
    """
    if len(prompts) != len(output_paths):
        raise ValueError("prompts and output_paths must have the same length.")

    config = image_generation_config()
    job = client.batches.create(
        model=IMAGE_MODEL,
        src=[types.InlinedRequest(contents=prompt, config=config) for prompt in prompts],
        config=types.CreateBatchJobConfig(display_name="wikiinfo-infographics"),
    )
    print(f"Submitted batch job {job.name} with {len(prompts)} requests.")
    return {
        "job_name": job.name,
        "model": IMAGE_MODEL,
        "submitted_at": int(time.time()),
        "output_paths": [str(path) for path in output_paths],
    }


def fetch_infographic_images(client: genai.Client, job_info: dict) -> dict:
    """Query a job from generate_infographic_images_async(); save images once it is done.

    Returns {"job_name", "state", "done", "saved", "failed", "error"}.
    """
    job = client.batches.get(name=job_info["job_name"])
    state = job.state.name if job.state else "JOB_STATE_UNSPECIFIED"
    result = {
        "job_name": job_info["job_name"],
        "state": state,
        "done": state in BATCH_DONE_STATES,
        "saved": [],
        "failed": [],
        "error": str(job.error) if job.error else None,
    }
    if not result["done"]:
        return result

    output_paths = [Path(path) for path in job_info["output_paths"]]
    responses = (job.dest.inlined_responses if job.dest else None) or []
    for index, output_path in enumerate(output_paths):
        response = responses[index].response if index < len(responses) else None
        if response and save_first_image(response, output_path):
            result["saved"].append(str(output_path))
        else:
            result["failed"].append(str(output_path))
    return result


def generate_infographic_images_batch(
    client: genai.Client,
    prompts: list[str],
    output_paths: list[Path],
) -> None:
    """Submit all prompts as one Gemini Batch API job, wait, and save the results."""
    job_info = generate_infographic_images_async(client, prompts, output_paths)

    result = fetch_infographic_images(client, job_info)
    while not result["done"]:
        print(f"Batch job state: {result['state']}")
        time.sleep(BATCH_POLL_SECONDS)
        result = fetch_infographic_images(client, job_info)

    for path in result["saved"]:
        print(f"Saved: {path}")
    if result["failed"]:
        raise RuntimeError(
            f"Batch job {result['job_name']} ended as {result['state']}; "
            f"no image for: {', '.join(Path(p).stem for p in result['failed'])}"
        )


def generate_infographic_image(
    client: genai.Client,
    prompt: str | list[str],
    output_path: Path | list[Path],
) -> None:
    """Generate one image, or run in Batch API mode when given lists."""
    if isinstance(prompt, list):
        if not isinstance(output_path, list):
            raise TypeError("Batch mode needs a list of output paths.")
        generate_infographic_images_batch(client, prompt, output_path)
        return
    if isinstance(output_path, list):
        raise TypeError("A single prompt needs a single output path.")

    max_attempts = 4

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=IMAGE_MODEL,
                contents=prompt,
                config=image_generation_config(),
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

        if save_first_image(response, output_path):
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
    batch: bool = True,
) -> list[Path]:
    """Generate one WebP infographic directly from each complete section."""
    client = create_client()
    if batch:
        prompts, output_paths = build_batch_inputs(
            wiki_title, output_directory, max_sections
        )
        generate_infographic_image(client, prompts, output_paths)
        return output_paths

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


def build_batch_inputs(
    wiki_title: str,
    output_directory: Path,
    max_sections: int | None = None,
) -> tuple[list[str], list[Path]]:
    """Build one prompt and one output path per article section."""
    sections = fetch_wikipedia_sections(wiki_title)
    if max_sections is not None:
        sections = sections[:max_sections]
    topic_directory = output_directory / safe_filename(wiki_title)
    print(f"Found {len(sections)} sections in '{wiki_title}'.")

    prompts = [
        build_infographic_prompt(wiki_title, section_title, content)
        for section_title, content in sections
    ]
    output_paths = [
        topic_directory / f"{index:02d}-{safe_filename(section_title)}.webp"
        for index, (section_title, _) in enumerate(sections, start=1)
    ]
    return prompts, output_paths


def submit_infographics_async(
    wiki_title: str,
    output_directory: Path,
    max_sections: int | None,
    job_file: Path,
) -> dict:
    """Submit a batch job without waiting and write its job dict to job_file."""
    client = create_client()
    prompts, output_paths = build_batch_inputs(
        wiki_title, output_directory, max_sections
    )
    job_info = generate_infographic_images_async(client, prompts, output_paths)
    job_info["article"] = wiki_title
    job_file.write_text(json.dumps(job_info, indent=2), encoding="utf-8")
    print(f"Saved job info to {job_file}. Run --collect {job_file} to get the images.")
    return job_info


def collect_infographics(job_file: Path) -> int:
    """Read job_file, save finished images, and return a process exit code.

    0 = all images saved, 1 = job finished with missing images, 2 = still running.
    """
    job_info = json.loads(job_file.read_text(encoding="utf-8"))
    result = fetch_infographic_images(create_client(), job_info)

    if not result["done"]:
        print(f"Job {result['job_name']} is {result['state']}; try again later.")
        return 2

    for path in result["saved"]:
        print(f"Saved: {path}")
    if result["failed"]:
        print(
            f"Job {result['job_name']} ended as {result['state']}; "
            f"no image for: {', '.join(result['failed'])}"
        )
        if result["error"]:
            print(f"Error: {result['error']}")
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate WebP infographics directly from Wikipedia sections."
    )
    parser.add_argument("title", nargs="?", help="Wikipedia article title")
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
    parser.add_argument(
        "--batch",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Send all sections as one Gemini Batch API job (default; about half "
            "the price, results are delayed). Use --no-batch for immediate requests."
        ),
    )
    parser.add_argument(
        "--async",
        dest="async_job",
        nargs="?",
        const=DEFAULT_JOB_FILE,
        type=Path,
        metavar="FILE",
        help=(
            "Submit a batch job without waiting and write its job info to FILE "
            f"(default: {DEFAULT_JOB_FILE}). Put the title before this option."
        ),
    )
    parser.add_argument(
        "--collect",
        nargs="?",
        const=DEFAULT_JOB_FILE,
        type=Path,
        metavar="FILE",
        help=(
            "Check the job described in FILE and save the images if it is done "
            f"(default: {DEFAULT_JOB_FILE}). Exits with 2 while still running."
        ),
    )
    arguments = parser.parse_args()

    if arguments.collect and (arguments.async_job or arguments.title):
        parser.error("--collect cannot be combined with a title or --async.")
    if arguments.async_job and not arguments.batch:
        parser.error("--async requires batch mode; remove --no-batch.")
    if not arguments.collect and not arguments.title:
        parser.error(
            "a title is required (use --async=FILE if the title follows --async)."
        )
    return arguments


def main() -> None:
    arguments = parse_args()
    try:
        if arguments.collect:
            raise SystemExit(collect_infographics(arguments.collect))
        if arguments.async_job:
            submit_infographics_async(
                arguments.title,
                arguments.output_dir,
                arguments.max_sections,
                arguments.async_job,
            )
            return
        wiki_to_infographics(
            arguments.title,
            arguments.output_dir,
            arguments.max_sections,
            arguments.batch,
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