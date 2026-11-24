# wikiinfo

Generate WebP infographics from a Wikipedia article using the Google Gemini
image API. The current command-line program is `wikiinfo_full.py`: it creates
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
