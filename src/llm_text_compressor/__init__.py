"""LLM Text Compressor - Remove characters from text while keeping it LLM-readable."""

from llm_text_compressor.compressor import (
    compress,
    compress_with_stats,
    compress_stream,
    compress_file,
    CompressionResult,
    PreservedSpan,
)

__all__ = [
    "compress",
    "compress_with_stats",
    "compress_stream",
    "compress_file",
    "CompressionResult",
    "PreservedSpan",
]
