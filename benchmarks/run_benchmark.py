#!/usr/bin/env python3
"""
Benchmark suite for llm-text-compressor.

Measures compression ratio, character savings, timing, and optionally token
savings across all compression levels and corpus files.

Usage:
    python benchmarks/run_benchmark.py                 # basic run
    python benchmarks/run_benchmark.py --markdown       # enable markdown mode
    python benchmarks/run_benchmark.py --locale fr      # test French locale
    python benchmarks/run_benchmark.py --tokens         # include token counts (requires tiktoken)
    python benchmarks/run_benchmark.py --output results.json  # save to file
    python benchmarks/run_benchmark.py --iterations 20  # average over 20 runs
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Ensure the src package is importable when running from repo root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from llm_text_compressor import compress, compress_with_stats  # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LevelResult:
    """Benchmark result for a single (file, level) combination."""

    level: int
    original_chars: int
    compressed_chars: int
    ratio: float
    savings_pct: float
    mean_time_ms: float
    median_time_ms: float
    min_time_ms: float
    max_time_ms: float
    original_tokens: int | None = None
    compressed_tokens: int | None = None
    token_savings_pct: float | None = None


@dataclass(slots=True)
class FileResult:
    """Benchmark results for a single corpus file across all levels."""

    filename: str
    original_chars: int
    levels: list[LevelResult] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkReport:
    """Full benchmark report."""

    timestamp: str
    python_version: str
    platform: str
    iterations: int
    markdown: bool
    locale: str | None
    files: list[FileResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Token counting (optional)
# ---------------------------------------------------------------------------

_tiktoken_encoding = None  # lazy singleton


def _try_load_tiktoken() -> bool:
    """Attempt to load tiktoken; return True if available."""
    global _tiktoken_encoding  # noqa: PLW0603
    try:
        import tiktoken  # type: ignore[import-untyped]

        _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        return True
    except (ImportError, Exception):
        return False


def _count_tokens(text: str) -> int | None:
    """Count tokens using tiktoken if available."""
    if _tiktoken_encoding is None:
        return None
    return len(_tiktoken_encoding.encode(text))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SEP = "-" * 100
_HEADER_FMT = "  {:<8s} {:>10s} {:>10s} {:>8s} {:>8s} {:>10s} {:>10s}"
_ROW_FMT = "  {:<8s} {:>10,d} {:>10,d} {:>7.1f}% {:>7.1f}% {:>9.2f}ms {:>9.2f}ms"
_TOKEN_HEADER_FMT = " {:>10s} {:>10s} {:>8s}"
_TOKEN_ROW_FMT = " {:>10s} {:>10s} {:>7.1f}%"


def _print_table_header(*, tokens: bool) -> None:
    header = _HEADER_FMT.format(
        "Level", "Orig", "Comp", "Ratio", "Saved", "Mean(ms)", "Med(ms)"
    )
    if tokens:
        header += _TOKEN_HEADER_FMT.format("Orig Tok", "Comp Tok", "Tok Sav")
    print(header)


def _print_table_row(r: LevelResult, *, tokens: bool) -> None:
    row = _ROW_FMT.format(
        f"L{r.level}",
        r.original_chars,
        r.compressed_chars,
        r.ratio * 100,
        r.savings_pct,
        r.mean_time_ms,
        r.median_time_ms,
    )
    if tokens and r.original_tokens is not None and r.compressed_tokens is not None:
        row += _TOKEN_ROW_FMT.format(
            f"{r.original_tokens:,d}",
            f"{r.compressed_tokens:,d}",
            r.token_savings_pct or 0.0,
        )
    elif tokens:
        row += " {:>10s} {:>10s} {:>8s}".format("n/a", "n/a", "n/a")
    print(row)


# ---------------------------------------------------------------------------
# Core benchmark logic
# ---------------------------------------------------------------------------


def benchmark_text(
    text: str,
    *,
    iterations: int = 10,
    markdown: bool = False,
    locale: str | None = None,
    count_tokens: bool = False,
) -> list[LevelResult]:
    """Run compression at all levels and return results."""
    results: list[LevelResult] = []

    for level in range(1, 5):
        timings: list[float] = []
        compressed = ""

        for _ in range(iterations):
            t0 = time.perf_counter()
            compressed = compress(text, level=level, markdown=markdown, locale=locale)
            t1 = time.perf_counter()
            timings.append((t1 - t0) * 1000)  # ms

        orig_len = len(text)
        comp_len = len(compressed)
        ratio = comp_len / orig_len if orig_len > 0 else 1.0
        savings = (1.0 - ratio) * 100.0

        lr = LevelResult(
            level=level,
            original_chars=orig_len,
            compressed_chars=comp_len,
            ratio=ratio,
            savings_pct=savings,
            mean_time_ms=statistics.mean(timings),
            median_time_ms=statistics.median(timings),
            min_time_ms=min(timings),
            max_time_ms=max(timings),
        )

        if count_tokens:
            lr.original_tokens = _count_tokens(text)
            lr.compressed_tokens = _count_tokens(compressed)
            if lr.original_tokens and lr.compressed_tokens:
                lr.token_savings_pct = (
                    (1.0 - lr.compressed_tokens / lr.original_tokens) * 100.0
                )

        results.append(lr)

    return results


def run_benchmark(
    corpus_dir: Path,
    *,
    iterations: int = 10,
    markdown: bool = False,
    locale: str | None = None,
    count_tokens: bool = False,
    output_path: Path | None = None,
) -> BenchmarkReport:
    """Run the full benchmark over all corpus files."""

    import datetime

    report = BenchmarkReport(
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        python_version=platform.python_version(),
        platform=platform.platform(),
        iterations=iterations,
        markdown=markdown,
        locale=locale,
    )

    corpus_files = sorted(corpus_dir.glob("*.txt"))
    if not corpus_files:
        print(f"No .txt files found in {corpus_dir}")
        sys.exit(1)

    print(f"\nllm-text-compressor benchmark")
    print(f"Python {platform.python_version()} on {platform.platform()}")
    print(f"Iterations per level: {iterations}")
    if markdown:
        print("Markdown mode: ON")
    if locale:
        print(f"Locale: {locale}")
    if count_tokens:
        print("Token counting: ON (tiktoken cl100k_base)")
    print(_SEP)

    for fp in corpus_files:
        text = fp.read_text(encoding="utf-8")
        filename = fp.name

        print(f"\n  File: {filename} ({len(text):,d} chars)")
        _print_table_header(tokens=count_tokens)

        level_results = benchmark_text(
            text,
            iterations=iterations,
            markdown=markdown,
            locale=locale,
            count_tokens=count_tokens,
        )

        fr = FileResult(filename=filename, original_chars=len(text), levels=level_results)
        report.files.append(fr)

        for lr in level_results:
            _print_table_row(lr, tokens=count_tokens)

    # Summary across all files
    print(f"\n{_SEP}")
    print("  AGGREGATE SUMMARY")
    print(_SEP)
    _print_table_header(tokens=count_tokens)

    for level in range(1, 5):
        all_orig = sum(fr.original_chars for fr in report.files)
        all_comp = sum(
            lr.compressed_chars
            for fr in report.files
            for lr in fr.levels
            if lr.level == level
        )
        all_mean = statistics.mean(
            lr.mean_time_ms for fr in report.files for lr in fr.levels if lr.level == level
        )
        all_median = statistics.median(
            lr.median_time_ms for fr in report.files for lr in fr.levels if lr.level == level
        )
        ratio = all_comp / all_orig if all_orig > 0 else 1.0
        savings = (1.0 - ratio) * 100.0

        agg = LevelResult(
            level=level,
            original_chars=all_orig,
            compressed_chars=all_comp,
            ratio=ratio,
            savings_pct=savings,
            mean_time_ms=all_mean,
            median_time_ms=all_median,
            min_time_ms=0.0,
            max_time_ms=0.0,
        )

        if count_tokens:
            orig_tok = [
                lr.original_tokens
                for fr in report.files
                for lr in fr.levels
                if lr.level == level and lr.original_tokens is not None
            ]
            comp_tok = [
                lr.compressed_tokens
                for fr in report.files
                for lr in fr.levels
                if lr.level == level and lr.compressed_tokens is not None
            ]
            if orig_tok and comp_tok:
                agg.original_tokens = sum(orig_tok)
                agg.compressed_tokens = sum(comp_tok)
                agg.token_savings_pct = (
                    (1.0 - agg.compressed_tokens / agg.original_tokens) * 100.0
                    if agg.original_tokens
                    else 0.0
                )

        _print_table_row(agg, tokens=count_tokens)

    print()

    # Optionally write JSON
    if output_path is not None:
        report_dict = asdict(report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
        print(f"  Results saved to {output_path}")
        print()

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark suite for llm-text-compressor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parent / "corpus",
        help="Directory with .txt corpus files (default: benchmarks/corpus/)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations per (file, level) to average timing (default: 10)",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Enable markdown-aware compression",
    )
    parser.add_argument(
        "--locale",
        type=str,
        default=None,
        help="Locale code for language-specific compression (e.g. fr, es, de)",
    )
    parser.add_argument(
        "--tokens",
        action="store_true",
        help="Count tokens using tiktoken (must be installed separately)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path to save JSON results (e.g. benchmarks/results.json)",
    )
    args = parser.parse_args()

    if args.tokens:
        if not _try_load_tiktoken():
            print("Warning: tiktoken not installed, token counting disabled.")
            print("Install with: pip install tiktoken")
            args.tokens = False

    run_benchmark(
        corpus_dir=args.corpus,
        iterations=args.iterations,
        markdown=args.markdown,
        locale=args.locale,
        count_tokens=args.tokens,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
