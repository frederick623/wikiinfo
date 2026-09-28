# wikiinfo

Generate one infographic per meaningful section of a Wikipedia article.

The project includes two command-line implementations:

- `wikiinfo_copilot.py` generates self-contained SVG infographics with GitHub Copilot CLI.
- `wikiinfo.py` generates PNG infographics with the Google Gemini API.

## Requirements

- Python 3.10 or newer
- [`wikipedia-api`](https://pypi.org/project/Wikipedia-API/)
- [`google-genai`](https://pypi.org/project/google-genai/) for `wikiinfo.py`
- [`python-dotenv`](https://pypi.org/project/python-dotenv/) for loading `.env`
- An installed and authenticated GitHub Copilot CLI for `wikiinfo_copilot.py`

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy the example environment file and set the values in `.env`:

```bash
cp .env.example .env
```

The scripts load `.env` automatically from the project directory. Set
`GEMINI_API_KEY` when using the Gemini implementation; the other values provide
defaults for the Wikipedia user agent, model names, and Copilot CLI command.

## GitHub Copilot CLI

Generate SVG files:

```bash
python wikiinfo_copilot.py "Hong Kong"
```

Useful options:

```bash
python wikiinfo_copilot.py "Hong Kong" \
  --output-dir infographics-copilot \
  --max-sections 3 \
  --model gpt-5.6-luna
```

## Google Gemini

Set your API key and generate PNG files:

```bash
export GEMINI_API_KEY="your-api-key"
python wikiinfo.py "Hong Kong"
```

Limit the number of generated sections when testing:

```bash
python wikiinfo.py "Hong Kong" --max-sections 3
```

Generated files are written beneath a topic-named directory in the selected
output directory.
