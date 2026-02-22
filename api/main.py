"""FastAPI REST API for llm-text-compressor."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from llm_text_compressor import (
    CompressionResult,
    compress,
    compress_stream,
    compress_with_stats,
)


# ---------------------------------------------------------------------------
# Redis Cache
# ---------------------------------------------------------------------------

redis_client: aioredis.Redis | None = None

# Cache TTL in seconds (default: 1 hour)
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

# Redis connection URL
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


def _generate_cache_key(prefix: str, data: dict) -> str:
    """Generate a cache key from request data."""
    # Sort dict keys for consistent hashing
    sorted_data = json.dumps(data, sort_keys=True)
    hash_value = hashlib.sha256(sorted_data.encode()).hexdigest()[:16]
    return f"{prefix}:{hash_value}"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CompressRequest(BaseModel):
    """Request body for compression endpoints."""

    text: str = Field(..., description="Text to compress")
    level: int = Field(default=2, ge=1, le=4, description="Compression level (1-4)")
    normalize: bool = Field(default=True, description="Normalize whitespace")
    preserve_patterns: list[str] | None = Field(
        default=None, description="Custom regex patterns to preserve"
    )
    preserve_words: list[str] | None = Field(
        default=None, description="Custom words to preserve (case-insensitive)"
    )
    markdown: bool = Field(default=False, description="Markdown-aware compression")
    locale: str | None = Field(
        default=None, description="Locale code for language-specific stop words (fr, es, de, pt, it)"
    )

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "text": "This function takes a list of integers as input and returns the maximum value.",
                "level": 2,
            }
        ]
    }}


class CompressResponse(BaseModel):
    """Response body for the /compress endpoint."""

    text: str = Field(..., description="Compressed text")


class PreservedSpanResponse(BaseModel):
    """A preserved span in the compressed output."""

    start: int
    end: int
    text: str
    kind: str


class CompressStatsResponse(BaseModel):
    """Response body for the /compress/stats endpoint."""

    text: str = Field(..., description="Compressed text")
    original_length: int = Field(..., description="Original text length")
    compressed_length: int = Field(..., description="Compressed text length")
    ratio: float = Field(..., description="Compression ratio (0.0-1.0)")
    savings_pct: float = Field(..., description="Percentage of characters saved")
    level: int = Field(..., description="Compression level used")
    preserved_spans: list[PreservedSpanResponse] = Field(
        default_factory=list, description="Spans preserved during compression"
    )


class BatchItem(BaseModel):
    """A single item in a batch compression request."""

    id: str = Field(..., description="Unique identifier for this item")
    text: str = Field(..., description="Text to compress")


class BatchRequest(BaseModel):
    """Request body for batch compression."""

    items: list[BatchItem] = Field(..., description="List of texts to compress")
    level: int = Field(default=2, ge=1, le=4, description="Compression level (1-4)")
    normalize: bool = Field(default=True, description="Normalize whitespace")
    preserve_patterns: list[str] | None = Field(default=None)
    preserve_words: list[str] | None = Field(default=None)
    markdown: bool = Field(default=False)
    locale: str | None = Field(default=None)


class BatchItemResponse(BaseModel):
    """A single result in a batch compression response."""

    id: str
    text: str
    original_length: int
    compressed_length: int
    ratio: float
    savings_pct: float


class BatchResponse(BaseModel):
    """Response body for batch compression."""

    items: list[BatchItemResponse]
    total_original_length: int
    total_compressed_length: int
    overall_ratio: float
    overall_savings_pct: float


class StreamRequest(BaseModel):
    """Request body for streaming compression."""

    chunks: list[str] = Field(..., description="Text chunks to compress")
    level: int = Field(default=2, ge=1, le=4)
    normalize: bool = Field(default=True)
    preserve_patterns: list[str] | None = Field(default=None)
    preserve_words: list[str] | None = Field(default=None)
    markdown: bool = Field(default=False)
    locale: str | None = Field(default=None)
    buffer_size: int = Field(default=4096, ge=64, description="Buffer size for streaming")


class HealthResponse(BaseModel):
    """Response body for health check."""

    status: str = "ok"
    version: str
    cache_enabled: bool = False
    redis_connected: bool = False


class CacheStatsResponse(BaseModel):
    """Response body for cache statistics."""

    enabled: bool
    connected: bool
    ttl_seconds: int
    redis_url: str
    keys_count: int | None = None
    memory_used: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_kwargs(req: CompressRequest | BatchRequest | StreamRequest) -> dict:
    """Extract common kwargs from a request model."""
    kwargs: dict = {
        "level": req.level,
        "normalize": req.normalize,
        "markdown": req.markdown,
        "locale": req.locale,
    }
    if req.preserve_patterns is not None:
        kwargs["preserve_patterns"] = req.preserve_patterns
    if req.preserve_words is not None:
        kwargs["preserve_words"] = set(req.preserve_words)
    return kwargs


def _result_to_stats_response(result: CompressionResult) -> CompressStatsResponse:
    """Convert a CompressionResult to the API response model."""
    return CompressStatsResponse(
        text=result.text,
        original_length=result.original_length,
        compressed_length=result.compressed_length,
        ratio=result.ratio,
        savings_pct=result.savings_pct,
        level=result.level,
        preserved_spans=[
            PreservedSpanResponse(
                start=span.start,
                end=span.end,
                text=span.text,
                kind=span.kind,
            )
            for span in result.preserved_spans
        ],
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan - setup Redis connection."""
    global redis_client
    try:
        redis_client = await aioredis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await redis_client.ping()
        print(f"✓ Connected to Redis at {REDIS_URL}")
    except Exception as e:
        print(f"⚠ Redis unavailable: {e}. Caching disabled.")
        redis_client = None
    
    yield
    
    if redis_client:
        await redis_client.close()


app = FastAPI(
    title="LLM Text Compressor API",
    description=(
        "REST API for compressing text while keeping it understandable by LLMs. "
        "Reduces token consumption by removing redundant characters while preserving "
        "structured data like URLs, emails, code blocks, JSON, and XML."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Check API health, version, and cache status."""
    redis_connected = False
    if redis_client:
        try:
            await redis_client.ping()
            redis_connected = True
        except Exception:
            pass
    
    return HealthResponse(
        status="ok",
        version="0.1.0",
        cache_enabled=redis_client is not None,
        redis_connected=redis_connected,
    )


@app.get("/cache/stats", response_model=CacheStatsResponse, tags=["Cache"])
async def cache_stats() -> CacheStatsResponse:
    """Get cache statistics and Redis connection info."""
    keys_count = None
    memory_used = None
    connected = False
    
    if redis_client:
        try:
            await redis_client.ping()
            connected = True
            # Get number of keys matching our patterns
            keys_count = 0
            for pattern in ["compress:*", "compress_stats:*"]:
                keys_count += len(await redis_client.keys(pattern))
            
            # Get memory usage
            info = await redis_client.info("memory")
            memory_used = info.get("used_memory_human", "unknown")
        except Exception:
            pass
    
    return CacheStatsResponse(
        enabled=redis_client is not None,
        connected=connected,
        ttl_seconds=CACHE_TTL,
        redis_url=REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL,
        keys_count=keys_count,
        memory_used=memory_used,
    )


@app.post("/compress", response_model=CompressResponse, tags=["Compression"])
async def compress_text(req: CompressRequest) -> CompressResponse:
    """Compress text by removing redundant characters.

    The text remains understandable by LLMs while being smaller.
    URLs, emails, IDs, code blocks, and other structured data are
    automatically preserved.
    
    Results are cached in Redis for improved performance.
    """
    try:
        # Generate cache key
        cache_data = req.model_dump()
        cache_key = _generate_cache_key("compress", cache_data)
        
        # Try cache first
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                return CompressResponse(text=cached)
        
        # Compress
        kwargs = _build_kwargs(req)
        result = compress(req.text, **kwargs)
        
        # Store in cache
        if redis_client:
            await redis_client.setex(cache_key, CACHE_TTL, result)
        
        return CompressResponse(text=result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/compress/stats", response_model=CompressStatsResponse, tags=["Compression"])
async def compress_text_with_stats(req: CompressRequest) -> CompressStatsResponse:
    """Compress text and return detailed compression statistics.

    Returns the compressed text along with metrics like compression ratio,
    savings percentage, and positions of all preserved spans.
    
    Results are cached in Redis for improved performance.
    """
    try:
        # Generate cache key
        cache_data = req.model_dump()
        cache_key = _generate_cache_key("compress_stats", cache_data)
        
        # Try cache first
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                cached_data = json.loads(cached)
                return CompressStatsResponse(**cached_data)
        
        # Compress
        kwargs = _build_kwargs(req)
        result = compress_with_stats(req.text, **kwargs)
        response = _result_to_stats_response(result)
        
        # Store in cache
        if redis_client:
            await redis_client.setex(
                cache_key,
                CACHE_TTL,
                response.model_dump_json(),
            )
        
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/compress/batch", response_model=BatchResponse, tags=["Compression"])
async def compress_batch(req: BatchRequest) -> BatchResponse:
    """Compress multiple texts in a single request.

    Each item is compressed independently with the same settings.
    Returns per-item results and aggregate statistics.
    """
    try:
        kwargs = _build_kwargs(req)
        items: list[BatchItemResponse] = []
        total_orig = 0
        total_comp = 0

        for item in req.items:
            result = compress_with_stats(item.text, **kwargs)
            items.append(BatchItemResponse(
                id=item.id,
                text=result.text,
                original_length=result.original_length,
                compressed_length=result.compressed_length,
                ratio=result.ratio,
                savings_pct=result.savings_pct,
            ))
            total_orig += result.original_length
            total_comp += result.compressed_length

        overall_ratio = total_comp / total_orig if total_orig > 0 else 1.0
        return BatchResponse(
            items=items,
            total_original_length=total_orig,
            total_compressed_length=total_comp,
            overall_ratio=overall_ratio,
            overall_savings_pct=(1.0 - overall_ratio) * 100,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/compress/stream", tags=["Compression"])
async def compress_text_stream(req: StreamRequest) -> StreamingResponse:
    """Compress text chunks and return a streaming response.

    Accepts an array of text chunks, compresses them using the streaming
    API, and returns compressed chunks as a streaming text response.
    """
    try:
        kwargs = _build_kwargs(req)
        kwargs["buffer_size"] = req.buffer_size

        def generate():
            for chunk in compress_stream(req.chunks, **kwargs):
                yield chunk

        return StreamingResponse(generate(), media_type="text/plain")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
