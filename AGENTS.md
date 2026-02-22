# AGENTS.md

## Project overview

`llm-text-compressor` is a pure Python library (zero dependencies) that removes characters from text while keeping it understandable by LLMs. It compresses text at 4 graduated levels — from light (doubled letter removal) to maximum (sentence pruning + aggressive trim) — while automatically preserving structured data like URLs, emails, IDs, code blocks, JSON, and XML.

The full technical specification is in `SPECS.md`.

## Setup commands

- Install in editable mode: `pip install -e ".[dev]"`
- Run tests: `pytest`
- Lint: `ruff check src/ tests/`
- Type check: `mypy src/`
- Run benchmarks: `python benchmarks/run_benchmark.py`

## Project structure

```
src/llm_text_compressor/
  __init__.py          # Public API re-exports (compress, compress_with_stats, compress_stream, compress_file, CompressionResult, PreservedSpan)
  compressor.py        # All compression logic — single module, ~1200 lines
tests/
  test_compressor.py   # 124 tests across 16 test classes
benchmarks/
  run_benchmark.py     # CLI benchmark runner
  corpus/              # Sample .txt files for benchmarking
```

This is a **single-module library**. All logic lives in `compressor.py`. Do not split it into multiple modules without explicit instruction.

## Code style

- Python 3.10+ required (uses `slots=True` on dataclasses, `X | Y` union syntax)
- Ruff linter with rules: `E`, `F`, `I`, `N`, `W`, `UP`
- Line length: 120
- mypy strict mode enabled
- Use `from __future__ import annotations` only where needed
- Dataclasses use `frozen=True, slots=True`
- Type all function signatures — no `Any` unless unavoidable
- Prefer compiled regex (`re.compile`) stored as module-level constants prefixed with `_`
- Private functions and constants prefixed with `_`

## Testing instructions

- All tests are in `tests/test_compressor.py`
- Run the full suite: `pytest`
- Run a specific test class: `pytest tests/test_compressor.py::TestCompress`
- Run a specific test: `pytest tests/test_compressor.py::TestCompress::test_level2_removes_vowels`
- Tests must pass before any commit. Fix failures before finishing a task.
- Add or update tests for any code change, even if not explicitly asked.
- Test classes follow the pattern `Test<FeatureName>` with descriptive method names `test_<behaviour>`

### Test classes and what they cover

| Class                         | Feature                                      |
| ----------------------------- | -------------------------------------------- |
| `TestCompress`                | Core compression at all levels, edge cases   |
| `TestPreserveEmails`          | Email address preservation                   |
| `TestPreserveURLs`            | URL preservation                             |
| `TestPreservePhoneNumbers`    | Phone number preservation                    |
| `TestPreserveIDs`             | UUID, hex ID, alphanumeric ID preservation   |
| `TestPreserveProperNouns`     | Capitalised words, acronyms                  |
| `TestCompressorOffTags`       | `[COMPRESSOR_OFF]` opt-out regions           |
| `TestWhitespaceNormalization` | Space collapse, blank line limits            |
| `TestPreserveStructuredData`  | JSON, XML, code blocks                       |
| `TestCompressionStats`        | `CompressionResult` fields and spans         |
| `TestCustomPreservePatterns`  | User regex patterns                          |
| `TestCustomPreserveWords`     | User word sets                               |
| `TestMarkdownMode`            | Markdown-aware compression                   |
| `TestLocaleSupport`           | French, Spanish, German, Portuguese, Italian |
| `TestStreamCompression`       | `compress_stream` and `compress_file`        |
| `TestSentencePruning`         | Level 4 filler removal and line dedup        |

## Architecture and conventions

- **Public API** is defined in `__init__.py` via `__all__`. Only add exports there if introducing a new public function or dataclass.
- **Compression pipeline order**: whitespace normalization → COMPRESSOR_OFF extraction → markdown routing or standard compression → preserve pattern detection → word-level compression.
- **Level 4** applies `_prune_sentences()` first, then delegates to level 3 compression. The variable `effective_level` is set to `3` when `level == 4`.
- **Preservation spans** are detected at three layers: structured data (`_extract_structured_data_spans`), built-in regex (`_PRESERVE_PATTERNS`), and custom patterns. All are merged, sorted, and deduplicated before compression fills the gaps.
- **Overlap resolution**: when preserved spans overlap, the earlier span wins and the later one is discarded.
- The **`_PRESERVE_WORDS`** set contains ~48 common English stop words plus Python keywords (`def`, `class`, `return`, `import`, `from`). These words are never compressed regardless of level.
- **Locale stop words** (`_LOCALE_STOP_WORDS`) are merged into the preserve-words set at call time; they don't modify the global state.
- **`_compress_word()`** is the core per-word transform. It checks guards (short word, stop word, special chars, acronym, proper noun) before applying level-specific transforms.

## Important warnings

- Never modify preserved spans or the order of pattern evaluation without updating tests.
- The `_PRESERVE_PATTERNS` regex uses alternation (`|`) with patterns ordered from most specific to least specific. Changing order can break preservation.
- `CompressionResult.preserved_spans` positions are in **compressed output** coordinates, not original text coordinates.
- Streaming (`compress_stream`) splits at word boundaries. Output is not guaranteed to be character-identical to non-streaming `compress()` on the same input due to whitespace normalization differences at chunk boundaries.
- `_normalize_whitespace` preserves leading indentation but collapses interior space runs. This is important for code-like content.

## PR and commit guidelines

- Run `pytest`, `ruff check src/ tests/`, and `mypy src/` before committing.
- Keep the single-module structure unless explicitly told to refactor.
- Bump version in `pyproject.toml` for any user-facing change.
