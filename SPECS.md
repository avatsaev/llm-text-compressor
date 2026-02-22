# Technical Specifications

> **llm-text-compressor v0.1.0** — Remove characters from text while keeping it understandable by LLMs, saving on inference costs.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Compression Algorithm](#3-compression-algorithm)
4. [Automatic Preservation](#4-automatic-preservation)
5. [Structured Data Preservation](#5-structured-data-preservation)
6. [COMPRESSOR_OFF Opt-Out Tags](#6-compressor_off-opt-out-tags)
7. [Whitespace Normalization](#7-whitespace-normalization)
8. [Compression Statistics](#8-compression-statistics)
9. [Custom Preserve Patterns](#9-custom-preserve-patterns)
10. [Custom Preserve Words](#10-custom-preserve-words)
11. [Markdown-Aware Mode](#11-markdown-aware-mode)
12. [Locale / Language Support](#12-locale--language-support)
13. [Streaming & Chunked API](#13-streaming--chunked-api)
14. [Sentence Pruning (Level 4)](#14-sentence-pruning-level-4)
15. [Benchmark Suite](#15-benchmark-suite)
16. [Public API Reference](#16-public-api-reference)
17. [Build & Tooling](#17-build--tooling)

---

## 1. Project Overview

### Purpose

LLM context windows have finite token budgets. `llm-text-compressor` reduces text size by systematically removing characters that are redundant for comprehension — doubled letters, interior vowels, long word tails, and filler phrases — while guaranteeing that structured data (URLs, emails, IDs, code blocks, JSON, XML) passes through untouched.

### Design Goals

| Goal | Rationale |
|---|---|
| **Zero dependencies** | Pure Python stdlib only; the library adds no transitive deps to consumer projects. |
| **Deterministic output** | Same input + same parameters = identical output, always. |
| **Preservation-first** | Anything that looks like machine-parseable data is never modified. |
| **Graduated compression** | Four discrete levels let callers trade readability for size. |
| **Streaming-ready** | Files of arbitrary size can be compressed without loading into memory. |

### Constraints

- Python ≥ 3.10 (uses `slots=True` on dataclasses, `X | Y` union syntax).
- Single-module implementation (`compressor.py`) — no internal package dependencies.
- Items are compressed word-by-word; the library never reorders or summarises content.

---

## 2. Architecture

### Package Layout

```
src/
  llm_text_compressor/
    __init__.py          # Public API re-exports
    compressor.py        # All compression logic (~1,200 lines)
tests/
  test_compressor.py     # 124 tests across 16 test classes
benchmarks/
  run_benchmark.py       # CLI benchmark runner
  corpus/                # Sample texts for benchmarking
    prose.txt
    code_mixed.txt
    log_output.txt
    chat_conversation.txt
    markdown_doc.txt
```

### Data Flow

```
Input text
  │
  ├─ Level 4? ──► _prune_sentences() ──► filler removal + line dedup
  │                                        │
  ▼                                        ▼
  ├─ normalize=True? ──► _normalize_whitespace()
  │
  ├─ [COMPRESSOR_OFF] extraction ──► verbatim regions pulled out
  │
  ├─ markdown=True?
  │    ├─ YES ──► _compress_markdown()   (line-by-line, syntax-aware)
  │    └─ NO  ──► _compress_with_preserve_patterns()
  │                  │
  │                  ├─ _extract_structured_data_spans()  (code, JSON, XML)
  │                  ├─ _PRESERVE_PATTERNS regex          (URLs, emails, IDs…)
  │                  ├─ custom_patterns                   (user-supplied)
  │                  │
  │                  ▼
  │               Non-preserved segments
  │                  │
  │                  ▼
  │               _compress_segment()
  │                  │
  │                  ▼
  │               _compress_word()  per token
  │                  ├─ L1: _remove_double_letters()
  │                  ├─ L2: + _remove_interior_vowels()
  │                  └─ L3: + _aggressive_trim()
  │
  ▼
Output text (or CompressionResult with stats)
```

### Key Internal Functions

| Function | Responsibility |
|---|---|
| `_compress_word(word, level)` | Applies level-appropriate transforms to a single alphabetic token. |
| `_compress_segment(segment, level)` | Tokenises a plain-text segment and compresses each word. |
| `_compress_with_preserve_patterns(text, level)` | Detects all spans to preserve, compresses the gaps between them. |
| `_compress_markdown(text, level)` | Line-by-line markdown processing: preserves syntax markers, compresses content. |
| `_extract_structured_data_spans(text)` | Finds fenced/inline code, JSON objects/arrays, and XML blocks. |
| `_prune_sentences(text)` | Removes filler phrases and deduplicates consecutive lines (level 4). |
| `_normalize_whitespace(text)` | Collapses whitespace runs, limits consecutive blank lines to 2. |

---

## 3. Compression Algorithm

### Level 1 — Light: Remove Doubled Letters

**Function:** `_remove_double_letters(word)`

Collapses consecutive identical letters into one.

```
"letter"     → "leter"
"committee"  → "comitee"    (note: only adjacent duplicates)
"bookkeeper" → "bokeper"
```

**Rules:**
- Comparison is case-insensitive (`Ss` → `S`).
- Words ≤ 2 characters are returned unchanged.

### Level 2 — Medium: Remove Interior Vowels

**Function:** `_remove_interior_vowels(word)` (applied after Level 1)

Strips vowels from the interior of the word, keeping the first letter, last letter, and all consonants.

```
"understanding"  → "undrstndng"   (after doubles: "undrstndng")
"compression"    → "cmprssn"      (after doubles: "comprsin" → interior vowels removed)
```

**Rules:**
- Words ≤ 3 characters are returned unchanged.
- A vowel is kept if removing it would create a run of ≥ 4 consecutive consonants (readability guard).
- The vowel set includes accented Latin characters: `àáâãäåæèéêëìíîïðòóôõöøùúûüýÿ` (and uppercase equivalents).

### Level 3 — Heavy: Aggressive Trim

**Function:** `_aggressive_trim(word)` (applied after Level 2)

Truncates words longer than 6 characters to `prefix(5) + last_char`.

```
"understanding" → (after L2: "undrstndng") → "undrsg"  (first 5 + last)
"short"         → "short"                               (≤ 6, unchanged)
```

### Level 4 — Maximum: Sentence Pruning + Level 3

Applies `_prune_sentences()` first (see [§14](#14-sentence-pruning-level-4)), then runs the full Level 3 pipeline on the pruned text.

### Word-Level Guards

Before any level transform, `_compress_word()` checks:

| Guard | Condition | Action |
|---|---|---|
| Short word | `len(word) ≤ 3` | Return unchanged |
| Stop word | `word.lower() in _PRESERVE_WORDS` | Return unchanged |
| Special chars | Contains `@`, `:`, `/`, `_`, `.`, `#`, `{`, `}`, `[`, `]`, `(`, `)` | Return unchanged |
| All-caps acronym | `word.isupper()` | Return unchanged |
| Proper noun | Starts uppercase, rest is not all-caps | Return unchanged |
| Custom preserve word | `word.lower() in preserve_words` | Return unchanged |

**Built-in `_PRESERVE_WORDS` set** (48 words):

> `i`, `a`, `an`, `the`, `is`, `am`, `are`, `was`, `were`, `be`, `to`, `of`, `in`, `on`, `at`, `by`, `or`, `and`, `not`, `no`, `if`, `it`, `he`, `she`, `we`, `do`, `did`, `has`, `had`, `can`, `but`, `for`, `nor`, `so`, `yet`, `all`, `its`, `my`, `me`, `up`, `as`, `go`, `us`, `ok`, `yes`, `true`, `false`, `null`, `none`, `def`, `class`, `return`, `import`, `from`

---

## 4. Automatic Preservation

### Regex-Based Pattern Detection

A single compiled regex (`_PRESERVE_PATTERNS`) matches spans that must never be compressed. Patterns are evaluated in order; the first match wins.

| Kind | Pattern | Example |
|---|---|---|
| **URL** | `https?://[^\s]+`, `ftp://[^\s]+`, `www.[^\s]+` | `https://docs.example.com/api/v2` |
| **Email** | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | `user@example.com` |
| **Phone** | `\+?\d[\d\-.\s()]{6,}\d` | `+1-555-123-4567` |
| **UUID** | `[0-9a-fA-F]{8}-...-[0-9a-fA-F]{12}` (8-4-4-4-12) | `550e8400-e29b-41d4-a716-446655440000` |
| **Hex ID** | `\b[0-9a-fA-F]{8,}\b` | `deadbeef01234567` |
| **Alphanum ID** | Mixed digits+letters with `_` or `-` | `usr_42x9`, `doc-auth-2024-abc123` |

### Proper Noun Detection

**Function:** `_is_proper_noun(word)`

A word is treated as a proper noun if:
1. Length > 1
2. First character is uppercase
3. The word is NOT entirely uppercase (that's an acronym — also preserved, but via a different guard)

---

## 5. Structured Data Preservation

### Fenced Code Blocks

**Regex:** `` ```\w*\n.*?``` `` (dotall)

Any content between triple-backtick fences is preserved verbatim, including the fence markers and language tag.

### Inline Code

**Regex:** `` `[^`\n]+` ``

Single-backtick inline code spans are preserved.

### JSON Blocks

**Function:** `_find_json_block(text, start)`

When the scanner encounters `{` or `[`, it checks if the next non-whitespace character is a valid JSON value starter (`"`, `{`, `[`, digit, `-`, `t`, `f`, `n`). If so, it uses `_find_balanced_end()` to locate the matching closing delimiter, handling nested structures and string escaping.

### XML / HTML Blocks

**Function:** `_find_xml_block(text, start)`

When `<` is encountered, the scanner looks for a valid opening tag (`<tagname ...>`). If found, it locates the corresponding `</tagname>` closing tag. Self-closing tags (`<tag ... />`) are also handled.

### Overlap Resolution

All detected spans (structured data + regex patterns + custom patterns) are merged into a single sorted list. When spans overlap, the earlier (or longer) span takes precedence and the overlapping span is discarded.

---

## 6. COMPRESSOR_OFF Opt-Out Tags

### Syntax

```
[COMPRESSOR_OFF]
This content is passed through verbatim.
No compression is applied here.
[/COMPRESSOR_OFF]
```

### Behaviour

1. The regex `_COMPRESSOR_OFF_RE` finds all `[COMPRESSOR_OFF]...[/COMPRESSOR_OFF]` regions (dotall).
2. The **tag markers are stripped** from the output — only the inner content appears.
3. Text **outside** the tags is compressed normally.
4. Multiple `[COMPRESSOR_OFF]` regions in a single input are supported.
5. Whitespace normalization is applied **only to text outside** COMPRESSOR_OFF regions.

---

## 7. Whitespace Normalization

**Function:** `_normalize_whitespace(text)`

Enabled by default (`normalize=True`). Applied before compression.

| Rule | Before | After |
|---|---|---|
| Trailing whitespace stripped | `"hello   \n"` | `"hello\n"` |
| Interior space runs collapsed | `"a    b"` | `"a b"` |
| Tab runs collapsed | `"a\t\tb"` | `"a b"` |
| Leading indent preserved | `"    code"` | `"    code"` |
| ≥ 3 blank lines → 2 blank lines | `"\n\n\n\n"` | `"\n\n"` |
| Leading/trailing blank lines stripped | `"\ntext\n"` | `"text"` |

---

## 8. Compression Statistics

### `CompressionResult` Dataclass

Returned by `compress_with_stats()`. Frozen, slotted.

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The compressed output. |
| `original_length` | `int` | `len()` of the input before compression. |
| `compressed_length` | `int` | `len()` of compressed output. |
| `ratio` | `float` | `compressed_length / original_length` (0.0–1.0). |
| `savings_pct` | `float` | `(1 - ratio) * 100`. |
| `level` | `int` | The compression level that was requested (1–4). |
| `preserved_spans` | `tuple[PreservedSpan, ...]` | Every span that was kept intact. |

### `PreservedSpan` Dataclass

| Field | Type | Description |
|---|---|---|
| `start` | `int` | Start position in the **compressed** output. |
| `end` | `int` | End position in the **compressed** output. |
| `text` | `str` | The preserved content. |
| `kind` | `str` | Span type (see below). |

**Span kinds:** `"url"`, `"email"`, `"phone"`, `"uuid"`, `"hex_id"`, `"alphanum_id"`, `"proper_noun"`, `"acronym"`, `"compressor_off"`, `"fenced_code"`, `"inline_code"`, `"json"`, `"xml"`, `"preserve"`, `"custom_pattern"`, `"markdown_hr"`.

---

## 9. Custom Preserve Patterns

### Parameter

```python
preserve_patterns: list[str | re.Pattern[str]] | None
```

### Behaviour

- Accepts raw regex strings **or** pre-compiled `re.Pattern` objects.
- Raw strings are compiled at call time; invalid regex raises `ValueError`.
- Custom pattern matches are tagged as `"custom_pattern"` in `PreservedSpan.kind`.
- Custom patterns are evaluated **before** built-in patterns, giving them higher priority.
- Overlapping spans are resolved in favour of the earlier match.

### Example

```python
# Preserve Jira ticket IDs
result = compress(text, preserve_patterns=[r"[A-Z]+-\d+"])
# "PROJ-1234" will never be modified
```

---

## 10. Custom Preserve Words

### Parameter

```python
preserve_words: set[str] | None
```

### Behaviour

- Merged with the built-in `_PRESERVE_WORDS` set at call time.
- Comparison is case-insensitive (`word.lower() in effective_set`).
- Any matching word is returned verbatim from `_compress_word()`, regardless of level.
- Does **not** use regex — this is a direct set lookup per word token.

### Example

```python
# Keep domain-specific terms intact
result = compress(text, preserve_words={"kubernetes", "nginx", "postgresql"})
```

---

## 11. Markdown-Aware Mode

### Parameter

```python
markdown: bool = False
```

### Behaviour

When `markdown=True`, the text is processed **line-by-line**. Each line is classified and handled:

| Markdown Element | Detection | Handling |
|---|---|---|
| **Horizontal rule** | `^(---+\|___+\|\*\*\*+)\s*$` | Entire line preserved verbatim. |
| **Heading** | `^#{1,6}\s+` | Marker (`## `) preserved; heading text compressed. |
| **List item** | `^\s*[-*+]\s+` or `^\s*\d+\.\s+` | Marker preserved; item text compressed. |
| **Blockquote** | `^>\s*` | Marker preserved; quote text compressed. |
| **Link / image** | `!?\[text\](url)` | Link text compressed; URL preserved verbatim. |
| **Bold / italic** | `**`, `__`, `*`, `_` markers | Markers pass through (they are non-alphabetic). |
| **Code fences** | `` ``` `` lines | Preserved by structured data detection (outer layer). |

Lines that don't match any markdown pattern are compressed normally with full preservation logic.

---

## 12. Locale / Language Support

### Parameter

```python
locale: str | None = None
```

### Supported Locales

| Code | Language | Stop Words Count |
|---|---|---|
| `fr` | French | 30 |
| `es` | Spanish | 32 |
| `de` | German | 30 |
| `pt` | Portuguese | 28 |
| `it` | Italian | 28 |

### Behaviour

1. When a locale is specified, the corresponding stop words from `_LOCALE_STOP_WORDS` are merged into the effective preserve-words set.
2. These words are then exempt from compression at all levels.
3. The extended `_VOWELS` set includes accented characters (e.g., `àáâãäåæèéêëìíîïðòóôõöøùúûüýÿ`), ensuring vowel removal works correctly for non-English text.
4. Locale stop words are **additive** — they merge with both built-in and user-supplied `preserve_words`.

### Example

```python
result = compress("Le développement de l'intelligence artificielle", locale="fr")
# "le", "de" are preserved; accented vowels in "développement" handled correctly
```

---

## 13. Streaming & Chunked API

### `compress_stream(chunks, ...)`

```python
def compress_stream(
    chunks: list[str] | tuple[str, ...],
    level: int = 2,
    buffer_size: int = 4096,
    ...
) -> Generator[str, None, None]:
```

**Algorithm:**

1. Accumulate incoming chunks into an internal buffer.
2. When `buffer_len ≥ buffer_size`:
   a. Search backwards (up to 100 chars) for the last whitespace character.
   b. Split at that word boundary.
   c. Compress everything before the split using `compress()`.
   d. Yield the compressed result.
   e. Keep the remainder as the new buffer.
3. On exhaustion of `chunks`, flush and yield any remaining buffer content.

**Invariants:**
- Splits only at whitespace boundaries to avoid breaking words.
- Each yielded chunk is independently valid compressed text.
- All parameters (`level`, `normalize`, `preserve_patterns`, `preserve_words`, `markdown`, `locale`) are forwarded to `compress()`.

### `compress_file(file_path, ...)`

```python
def compress_file(
    file_path: str,
    chunk_size: int = 8192,
    encoding: str = "utf-8",
    ...
) -> Generator[str, None, None]:
```

Convenience wrapper: reads the file in `chunk_size` byte chunks and delegates to `compress_stream()`. The file is read lazily — only one chunk is in memory at a time.

---

## 14. Sentence Pruning (Level 4)

### Function: `_prune_sentences(text)`

Applied **before** any word-level compression when `level=4`. After pruning, the text is compressed at Level 3.

### Filler Phrase Removal

Nine compiled regex patterns match and remove common filler phrases:

| # | Pattern | Examples |
|---|---|---|
| 1 | Discourse markers | "you know", "I mean", "sort of", "kind of", "basically", "actually", "literally" |
| 2 | Opinion hedges | "I think", "I believe", "in my opinion", "it seems" |
| 3 | Honesty markers | "to be honest", "honestly", "frankly" |
| 4 | Intensifiers (before adj) | "just ", "really ", "very ", "quite ", "pretty " |
| 5 | Reference phrases | "as you can see", "as mentioned", "as stated" |
| 6 | Example markers | "for example", "such as", "e.g.,", "i.e.," |
| 7 | Rephrase markers | "in other words", "that is to say" |
| 8 | Cliché phrases | "at the end of the day", "at this point in time" |
| 9 | Redundancy | "needless to say", "it goes without saying" |

Each match is replaced with a single space. Multiple consecutive spaces are then collapsed.

### Line Deduplication

After filler removal, consecutive lines with identical content (case-insensitive, stripped) are collapsed to a single line. Blank lines are preserved but do not reset the deduplication state.

---

## 15. Benchmark Suite

### Location

```
benchmarks/
  run_benchmark.py
  corpus/
    prose.txt             # ~3.4 KB — pure natural language (AI/ML essay)
    code_mixed.txt        # ~3.1 KB — documentation with Python code blocks, YAML, URLs
    log_output.txt        # ~3.7 KB — server logs with UUIDs, IPs, stack traces
    chat_conversation.txt # ~0.9 KB — LLM chat format with embedded code
    markdown_doc.txt      # ~3.3 KB — API reference with headings, tables, links
```

### CLI Usage

```bash
python benchmarks/run_benchmark.py                       # default: 10 iterations
python benchmarks/run_benchmark.py --iterations 50        # more stable timing
python benchmarks/run_benchmark.py --markdown             # test markdown mode
python benchmarks/run_benchmark.py --locale fr            # test French locale
python benchmarks/run_benchmark.py --tokens               # token counts (requires tiktoken)
python benchmarks/run_benchmark.py -o results.json        # save JSON report
```

### Output

For each corpus file and each level (1–4), the runner reports:

| Metric | Description |
|---|---|
| Orig | Original character count |
| Comp | Compressed character count |
| Ratio | `compressed / original × 100` |
| Saved | Percentage of characters removed |
| Mean(ms) | Mean compression time across iterations |
| Med(ms) | Median compression time |
| Orig Tok | Original token count (with `--tokens`) |
| Comp Tok | Compressed token count (with `--tokens`) |
| Tok Sav | Token savings percentage (with `--tokens`) |

An aggregate summary row is printed at the end, averaging across all files.

### JSON Report Schema

```json
{
  "timestamp": "ISO-8601",
  "python_version": "3.x.x",
  "platform": "Linux-...",
  "iterations": 10,
  "markdown": false,
  "locale": null,
  "files": [
    {
      "filename": "prose.txt",
      "original_chars": 3425,
      "levels": [
        {
          "level": 1,
          "original_chars": 3425,
          "compressed_chars": 3389,
          "ratio": 0.989,
          "savings_pct": 1.1,
          "mean_time_ms": 1.04,
          "median_time_ms": 1.03,
          "min_time_ms": 1.01,
          "max_time_ms": 1.12,
          "original_tokens": null,
          "compressed_tokens": null,
          "token_savings_pct": null
        }
      ]
    }
  ]
}
```

---

## 16. Public API Reference

### Exports (`__init__.py`)

```python
from llm_text_compressor import (
    compress,              # str → str
    compress_with_stats,   # str → CompressionResult
    compress_stream,       # Iterable[str] → Generator[str]
    compress_file,         # str → Generator[str]
    CompressionResult,     # dataclass
    PreservedSpan,         # dataclass
)
```

### Function Signatures

```python
def compress(
    text: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
) -> str: ...

def compress_with_stats(
    text: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
) -> CompressionResult: ...

def compress_stream(
    chunks: list[str] | tuple[str, ...],
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
    buffer_size: int = 4096,
) -> Generator[str, None, None]: ...

def compress_file(
    file_path: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
    chunk_size: int = 8192,
    encoding: str = "utf-8",
) -> Generator[str, None, None]: ...
```

### Error Handling

| Error | Condition |
|---|---|
| `ValueError` | `level` not in `{1, 2, 3, 4}` |
| `ValueError` | A string in `preserve_patterns` is not a valid regex |
| `FileNotFoundError` | `compress_file()` path does not exist |

---

## 17. Build & Tooling

### Build System

- **Backend:** Hatchling (PEP 517/518)
- **Config:** `pyproject.toml` (no `setup.py` or `setup.cfg`)
- **Source layout:** `src/llm_text_compressor/`

### Python Compatibility

- **Minimum:** Python 3.10
- **Tested:** 3.10, 3.11, 3.12, 3.13

### Code Quality

| Tool | Config | Purpose |
|---|---|---|
| **Ruff** | `select = ["E", "F", "I", "N", "W", "UP"]`, `line-length = 120` | Linting + import sorting |
| **mypy** | `strict = true`, `python_version = "3.10"` | Static type checking |
| **pytest** | `testpaths = ["tests"]` | 124 tests, 16 test classes |

### Test Coverage Matrix

| Test Class | Tests | Covers |
|---|---|---|
| `TestCompress` | 13 | Core compression at all levels, edge cases |
| `TestPreserveEmails` | 3 | Email address detection |
| `TestPreserveURLs` | 3 | URL detection (http, https, www) |
| `TestPreservePhoneNumbers` | 3 | Phone number formats |
| `TestPreserveIDs` | 3 | UUID, hex ID, alphanumeric ID |
| `TestPreserveProperNouns` | 3 | Capitalised words, acronyms |
| `TestCompressorOffTags` | 6 | Opt-out regions, multiple regions, nesting |
| `TestWhitespaceNormalization` | 8 | Space collapse, blank line limits, indent preservation |
| `TestPreserveStructuredData` | 10 | JSON, XML, fenced code, inline code, nested, overlaps |
| `TestCompressionStats` | 13 | CompressionResult fields, PreservedSpan positions, edge cases |
| `TestCustomPreservePatterns` | 8 | String patterns, compiled patterns, invalid regex, overlap |
| `TestCustomPreserveWords` | 6 | Custom words, merge with built-in, case-insensitivity |
| `TestMarkdownMode` | 13 | Headings, lists, links, blockquotes, HR, images, code fences |
| `TestLocaleSupport` | 10 | All 5 locales, stop word preservation, accented vowels |
| `TestStreamCompression` | 13 | Chunked input, buffer flushing, word boundaries, compress_file |
| `TestSentencePruning` | 9 | Filler removal, line dedup, interaction with other features |
