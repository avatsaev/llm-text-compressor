# LLM Text Compressor API

FastAPI REST API for the `llm-text-compressor` library.

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"
pip install -r api/requirements.txt

# Run the server
uvicorn api.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for interactive Swagger UI.

## Endpoints

| Method | Path               | Description                             |
| ------ | ------------------ | --------------------------------------- |
| GET    | `/health`          | Health check with cache status          |
| GET    | `/cache/stats`     | Cache statistics and Redis info         |
| POST   | `/compress`        | Compress text, return compressed string |
| POST   | `/compress/stats`  | Compress text with detailed statistics  |
| POST   | `/compress/batch`  | Compress multiple texts in one request  |
| POST   | `/compress/stream` | Stream-compress text chunks             |

## Features

### Redis Caching

The API includes Redis-based caching to improve performance:

- Compression results are cached with configurable TTL
- Automatic cache key generation based on request parameters
- Cache statistics endpoint for monitoring
- Graceful fallback if Redis is unavailable

### Environment Variables

| Variable    | Default              | Description                   |
| ----------- | -------------------- | ----------------------------- |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL          |
| `CACHE_TTL` | `3600`               | Cache TTL in seconds (1 hour) |

## Example

```bash
curl -X POST http://localhost:8000/compress \
  -H "Content-Type: application/json" \
  -d '{"text": "This function takes a list of integers and returns the maximum value.", "level": 2}'
```

## Docker

### Using Docker Compose (Recommended)

```bash
docker compose up --build
```

The API will be available at [http://localhost:8000](http://localhost:8000).

### Using Docker directly

```bash
docker build -t llm-text-compressor-api .
docker run -p 8000:8000 llm-text-compressor-api
```
