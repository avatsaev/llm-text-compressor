# LLM Text Compressor

Remove characters from text while keeping it understandable by LLMs — save on inference costs at scale.

**Zero dependencies. Deterministic. Preservation-first.**

## Why?

LLMs don't need every character to understand language. This text:

> Ths fnctn tks a lst of intgrs as inpt and rtrns the mxmm vle fnd in the clctn. If the lst is mpty, it rss a VlError excptn.

Is perfectly understood as:

> This function takes a list of integers as input and returns the maximum value found in the collection. If the list is empty, it raises a ValueError exception.

The compressed version is **~20% smaller**, which adds up fast when you're feeding large contexts to LLMs.

## Features

- **4 compression levels** — from light (doubled letters) to maximum (sentence pruning)
- **Smart preservation** — URLs, emails, phone numbers, UUIDs, IDs, proper nouns, and acronyms are never touched
- **Structured data detection** — code blocks, JSON, XML pass through verbatim
- **Opt-out regions** — wrap text in `[COMPRESSOR_OFF]...[/COMPRESSOR_OFF]` to skip compression
- **Markdown-aware mode** — preserves headings, lists, links, blockquotes
- **Locale support** — French, Spanish, German, Portuguese, Italian stop words
- **Streaming API** — compress files of arbitrary size without loading into memory
- **Compression stats** — get detailed metrics and preserved span positions
- **Custom patterns & words** — extend preservation with your own regex or word sets

## Installation

```bash
pip install llm-text-compressor
```

Requires Python 3.10+. No dependencies.

## Quick Start

```python
from llm_text_compressor import compress

text = "This function takes a list of integers as input and returns the maximum value."
print(compress(text))
# "Ths fnctn tks a lst of intgrs as inpt and rtrns the mxmm vle."
```

## Compression Levels

| Level | Strategy | Description                                                     |
| ----- | -------- | --------------------------------------------------------------- |
| 1     | Light    | Remove doubled letters (`letter` → `leter`)                     |
| 2     | Medium   | + Remove interior vowels (`letter` → `ltr`)                     |
| 3     | Heavy    | + Truncate long words (`understanding` → `undrsg`)              |
| 4     | Maximum  | + Remove filler phrases & deduplicate lines, then apply level 3 |

```python
compress("understanding artificial intelligence", level=1)
# "understaning artificial inteligence"

compress("understanding artificial intelligence", level=2)
# "undrstndng artfcl intlgnce"

compress("understanding artificial intelligence", level=3)
# "undrsg artfl intle"
```

## Preservation

Structured data is automatically detected and preserved:

```python
text = "Contact user@example.com or visit https://docs.example.com for ID abc-123-def"
print(compress(text, level=3))
# "Cntct user@example.com or vist https://docs.example.com for ID abc-123-def"
```

**Auto-preserved types:** URLs, emails, phone numbers, UUIDs, hex IDs, alphanumeric IDs, proper nouns, acronyms, code blocks, JSON objects, XML blocks.

### Custom Preservation

```python
# Preserve specific words
compress(text, preserve_words={"kubernetes", "nginx"})

# Preserve regex patterns (e.g. Jira tickets)
compress(text, preserve_patterns=[r"[A-Z]+-\d+"])
```

### Opt-Out Regions

```python
text = """
This will be compressed.
[COMPRESSOR_OFF]
This exact text will NOT be compressed.
[/COMPRESSOR_OFF]
This will be compressed too.
"""
compress(text)
```

## Markdown Mode

Preserves markdown syntax while compressing content:

```python
text = "## Introduction\n\nThis is an important paragraph about machine learning."
compress(text, markdown=True)
# "## Introduction\n\nThs is an imprtnt pargrph abt mchn lrnng."
```

Headings markers, list markers, link URLs, blockquote markers, and horizontal rules are kept intact.

## Locale Support

Preserve language-specific stop words for better readability:

```python
compress("Le développement de l'intelligence artificielle", locale="fr")
# Preserves "le", "de" and other French stop words
```

Supported locales: `fr` (French), `es` (Spanish), `de` (German), `pt` (Portuguese), `it` (Italian).

## Compression Stats

Get detailed metrics about the compression:

```python
from llm_text_compressor import compress_with_stats

result = compress_with_stats("Hello world, this is a test.", level=2)
print(f"Ratio: {result.ratio:.2f}")        # 0.85
print(f"Saved: {result.savings_pct:.1f}%")  # 15.0%
print(f"Preserved spans: {len(result.preserved_spans)}")
```

Returns a `CompressionResult` with: `text`, `original_length`, `compressed_length`, `ratio`, `savings_pct`, `level`, and `preserved_spans`.

## Streaming

Compress large files without loading them into memory:

```python
from llm_text_compressor import compress_stream, compress_file

# From chunks
chunks = ["This is a ", "test of streaming ", "compression."]
for compressed_chunk in compress_stream(chunks, level=2):
    print(compressed_chunk, end="")

# From a file
for chunk in compress_file("large_document.txt", level=2):
    output.write(chunk)
```

## Benchmarks

Run the included benchmark suite:

```bash
python benchmarks/run_benchmark.py
python benchmarks/run_benchmark.py --markdown          # test markdown mode
python benchmarks/run_benchmark.py --tokens            # token counts (requires tiktoken)
python benchmarks/run_benchmark.py -o results.json     # save JSON report
```

Typical results across the included corpus (~14 KB of mixed content):

| Level | Character Savings |
| ----- | ----------------- |
| L1    | ~1%               |
| L2    | ~10%              |
| L3    | ~13%              |
| L4    | ~14%              |

## API Reference

```python
# Core compression
compress(text, level=2, normalize=True, preserve_patterns=None,
         preserve_words=None, markdown=False, locale=None) -> str

# With statistics
compress_with_stats(...) -> CompressionResult

# Streaming
compress_stream(chunks, level=2, buffer_size=4096, ...) -> Generator[str]
compress_file(file_path, level=2, chunk_size=8192, encoding="utf-8", ...) -> Generator[str]
```

See [SPECS.md](SPECS.md) for full technical specifications.

## Development

```bash
# Clone and install
git clone https://github.com/avatsaev/llm-text-compressor.git
cd llm-text-compressor
pip install -e ".[dev]"

# Run tests (124 tests)
pytest

# Lint & type check
ruff check src/ tests/
mypy src/
```

## License

MIT
