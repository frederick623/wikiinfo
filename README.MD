# wikiinfo

Generate one infographic per meaningful section of a Wikipedia article.

The project includes two command-line implementations:

- `wikiinfo_copilot.py` generates self-contained SVG infographics with GitHub Copilot CLI.
- `wikiinfo.py` generates PNG infographics with the Google Gemini API.

## Requirements

- Python 3.10 or newer
- [`wikipedia-api`](https://pypi.org/project/Wikipedia-API/)
- [`google-genai`](https://pypi.org/project/google-genai/) for `wikiinfo.py`
- An installed and authenticated GitHub Copilot CLI for `wikiinfo_copilot.py`

Install the Python dependencies:

```bash
python -m pip install wikipedia-api google-genai
```

Set a descriptive Wikipedia user agent:

```bash
export WIKIPEDIA_USER_AGENT="WikiToInfographicBot/1.0 (you@example.com)"
```

## GitHub Copilot CLI

Generate SVG files:

```bash
python wikiinfo.py "Hong Kong"
```

Useful options:

```bash
python wikiinfo.py "Hong Kong" \
  --output-dir infographics-copilot \
  --max-sections 3 \
  --model gpt-5.6-luna
```

## Google Gemini

Set your API key and generate PNG files:

```bash
export GEMINI_API_KEY="your-api-key"
python wikiinfo_copilot.py "Hong Kong"
```

Limit the number of generated sections when testing:

```bash
python wikiinfo_copilot.py "Hong Kong" --max-sections 3
```

Generated files are written beneath a topic-named directory in the selected
output directory.
