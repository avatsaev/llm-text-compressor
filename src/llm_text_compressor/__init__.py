"""LLM Text Compressor - Remove characters from text while keeping it LLM-readable."""

from llm_text_compressor.compressor import (
    CompressionResult,
    PreservedSpan,
    compress,
    compress_file,
    compress_stream,
    compress_with_stats,
)

__all__ = [
    "compress",
    "compress_with_stats",
    "compress_stream",
    "compress_file",
    "CompressionResult",
    "PreservedSpan",
]
