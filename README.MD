# wikiinfo

Generate WebP infographics from a Wikipedia article using the Google Gemini
image API. The current command-line program is `wikiinfo.py`: it creates
one infographic for the article lead and each meaningful top-level section,
including text from that section's subsections.

## Requirements

- Python 3.10 or newer
- A Gemini API key with access to image generation
- The Python packages listed in `requirements.txt`

Install directly from GitHub (provides the `wikiinfo` command):

```bash
python -m pip install git+https://github.com/frederick623/wikiinfo.git
```

Or, from a local checkout, install the dependencies only:

```bash
python -m pip install -r requirements.txt
```

Set your API key in the shell before running the program:

```bash
export GEMINI_API_KEY="your-api-key"
```

Alternatively, create a `.env` file in the project directory with the same
setting. The program loads `.env` automatically. Optionally, set
`GEMINI_IMAGE_MODEL` to choose a different image model or
`WIKIPEDIA_USER_AGENT` to provide a contact address in the Wikipedia request
user agent. By default, the program uses `gemini-3.1-flash-lite-image` and
`WikiToInfographicBot/1.0 (contact@example.com)`.

## Usage

Generate up to 10 infographics for the first sections of an article:

```bash
python wikiinfo.py "Hong Kong"
```

Limit the number of sections or choose a different output directory:

```bash
python wikiinfo.py "Hong Kong" --max-sections 3
python wikiinfo.py "Hong Kong" --output-dir infographics-test
```

The article lead counts as a section when Wikipedia provides a summary. The
program skips reference-style sections such as References and External links.
By default, it processes up to 10 sections and writes `.webp` files under
`infographics/<article-name>/`. Use `--help` to see the available options.

All sections are sent as a single Gemini Batch API job by default, which costs
about half as much but returns results with a delay; the program waits and
polls until the job finishes. Pass `--no-batch` to generate each section with an
immediate request instead.

To avoid waiting, submit the job and collect the images later:

```bash
python wikiinfo.py "Apple_Inc." --async            # writes job.json and exits
python wikiinfo.py --collect                       # saves the images if the job is done
python collect_infographics.py job.json            # same, as a standalone program
```

`--async` and `--collect` take an optional file name (default `job.json`); put
the title before `--async`, or write `--async=FILE`. Collecting exits with
status 2 while the job is still running, 1 if some images are missing, and 0
once every image is saved.

Each section's source text is sent directly to the configured Gemini image
model. The prompt asks the model to use only that text, feature no more than
five key facts, and create a standalone portrait infographic. Images are named
with a numbered, filesystem-safe version of the section title.

## Batch mode

Batch mode is the default. The program sends every section as one request list
in a single [Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-api)
job instead of one request per section.

- **Cost:** batch requests are priced at 50% of the standard rate.
- **Timing:** Google targets a turnaround of up to 24 hours; many jobs finish
  much sooner. A job that is pending or running for more than 48 hours
  expires and returns no results.
- **Waiting:** by default the program polls every 15 seconds and stays running
  until the job ends. If you close the terminal while waiting, the job
  reference is lost; use `--async` to keep it in `job.json`.
- **Failures:** if any section comes back without an image, the program reports
  which ones and exits with an error. Images that were generated are still
  saved.
- **Resubmitting:** creating a batch job is not idempotent. Submitting the same
  request twice creates, and bills, two jobs.

| Option | Behavior |
| --- | --- |
| _(default)_ / `--batch` | One batch job; wait until it finishes, then save the images |
| `--no-batch` | One immediate request per section, at the standard price |
| `--async [FILE]` | Submit the batch job, write its job info to `FILE`, and exit |
| `--collect [FILE]` | Check the job in `FILE` and save the images once it is done |

`--async` always uses batch mode and cannot be combined with `--no-batch`.
`--collect` cannot be combined with a title or `--async`.

### Job file

`--async` writes a small JSON file that identifies the job and where its images
should go:

```json
{
  "job_name": "batches/...",
  "model": "gemini-3.1-flash-lite-image",
  "submitted_at": 1795451497,
  "output_paths": ["infographics/nvidia/01-nvidia.webp", "..."],
  "article": "Nvidia"
}
```

`--collect` and `collect_infographics.py` read this file and write the images to
the recorded paths. The paths are relative, so run them from the same directory
you used for `--async`. Collecting can be repeated; once the job is done it saves the
images again. The Gemini docs do not state how long finished results stay
available, so collect within 48 hours of the job finishing to be safe.

### Using the functions from Python

The same flow is available as functions in `wikiinfo.py`:

```python
from wikiinfo import (
    create_client,
    fetch_infographic_images,
    generate_infographic_image,
    generate_infographic_images_async,
)

client = create_client()

# Lists of prompts and output paths run in batch mode and wait for the result.
generate_infographic_image(client, prompts, output_paths)

# Or submit without waiting, and query the returned dict later.
job = generate_infographic_images_async(client, prompts, output_paths)
result = fetch_infographic_images(client, job)
# result: {"job_name", "state", "done", "saved", "failed", "error"}
```

Passing a single prompt and a single path to `generate_infographic_image` makes
an immediate, non-batch request with retries. `generate_infographic_images_async`
returns a JSON-serializable dict, so it can be stored or handed to another
process. `fetch_infographic_images` only saves images once `done` is true.
