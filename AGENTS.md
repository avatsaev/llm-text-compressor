# AGENTS.md

## Project overview

`llm-text-compressor` is a pure Python library (zero dependencies) that removes characters from text while keeping it understandable by LLMs. It compresses text at 4 graduated levels — from light (doubled letter removal) to maximum (sentence pruning + aggressive trim) — while automatically preserving structured data like URLs, emails, IDs, code blocks, JSON, and XML.

The project includes a production-ready FastAPI REST API with Redis caching support for high-performance deployments.

The full technical specification is in `SPECS.md`.

## Setup commands

### Core Library

- Install in editable mode: `pip install -e ".[dev]"`
- Run tests: `pytest`
- Lint: `ruff check src/ tests/`
- Type check: `mypy src/`
- Run benchmarks: `python benchmarks/run_benchmark.py`

### REST API

- Install API dependencies: `pip install -r api/requirements.txt`
- Start API locally: `uvicorn api.main:app --reload`
- Start with Docker Compose: `docker compose up --build`
- Stop containers: `docker compose down`
- View API docs: `http://localhost:8000/docs`

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
api/
  main.py              # FastAPI application with Redis caching (~450 lines)
  requirements.txt     # API dependencies (fastapi, uvicorn, redis)
  README.md            # API documentation
  .env.example         # Environment variable template
docker-compose.yml     # Docker Compose config (API + Redis)
Dockerfile             # Container image for API
```

The **core library** is a single-module design. All compression logic lives in `compressor.py`. Do not split it into multiple modules without explicit instruction.

The **REST API** is a separate FastAPI application in the `api/` directory with Redis caching support.

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

## REST API architecture

### Components

- **FastAPI application** (`api/main.py`) — async REST endpoints with OpenAPI documentation
- **Redis caching** — optional, automatic fallback if unavailable
- **Docker Compose** — multi-container setup (API + Redis 7)
- **Health checks** — container-level health monitoring

### API endpoints

| Method | Path               | Description                          |
| ------ | ------------------ | ------------------------------------ |
| GET    | `/health`          | Health check with cache status       |
| GET    | `/cache/stats`     | Cache statistics (keys, memory, TTL) |
| POST   | `/compress`        | Compress text (cached)               |
| POST   | `/compress/stats`  | Compress with statistics (cached)    |
| POST   | `/compress/batch`  | Batch compression (not cached)       |
| POST   | `/compress/stream` | Streaming compression (not cached)   |

### Caching strategy

- **Cache keys** generated from SHA-256 hash of request parameters
- **TTL** configurable via `CACHE_TTL` env var (default: 3600s)
- **Prefixes**: `compress:*` and `compress_stats:*`
- **Graceful degradation**: API works without Redis
- Batch and streaming endpoints do not use cache

### Environment variables

- `REDIS_URL` — Redis connection URL (default: `redis://redis:6379`)
- `CACHE_TTL` — Cache TTL in seconds (default: `3600`)
- `PYTHONUNBUFFERED` — Set to `1` for Docker logs

### Code style (API)

- Python 3.10+ with FastAPI and async/await
- Pydantic models for request/response validation
- Type hints on all functions
- redis.asyncio (aioredis) for async Redis client
- Follow same ruff/mypy rules as core library

### API development workflow

1. Make changes to `api/main.py`
2. Test locally: `uvicorn api.main:app --reload`
3. Test with Docker: `docker compose up --build`
4. Verify health: `curl http://localhost:8000/health`
5. Check cache: `curl http://localhost:8000/cache/stats`
6. Test compression: `curl -X POST http://localhost:8000/compress -H "Content-Type: application/json" -d '{"text": "test", "level": 2}'`
7. Stop: `docker compose down`
