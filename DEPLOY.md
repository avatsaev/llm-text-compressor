# Deployment Guide

Quick reference for publishing new versions to PyPI and Docker Hub.

## Automatic Deployment (Recommended)

The project uses GitHub Actions for automatic deployment on version tags.
When a tag matching `v*` is pushed, the workflow publishes to PyPI and Docker Hub.

1. **Set up repository secrets** in GitHub:
   - Go to: https://github.com/avatsaev/llm-text-compressor/settings/secrets/actions
   - Add secret: `PYPI_API_TOKEN` = your PyPI token
   - Add secret: `DOCKERHUB_USERNAME` = your Docker Hub username
   - Add secret: `DOCKERHUB_TOKEN` = your Docker Hub access token/password

2. **(Optional) Set Docker image name variable**:
   - Go to: https://github.com/avatsaev/llm-text-compressor/settings/variables/actions
   - Add variable: `DOCKER_IMAGE_NAME` (defaults to repository name if omitted)

3. **Update version** in `pyproject.toml`:

   ```toml
   version = "0.1.1"  # Increment version
   ```

4. **Create and push a version tag**:
   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 0.1.1"
   git tag v0.1.1
   git push origin main
   git push origin v0.1.1
   ```

The `.github/workflows/publish.yml` workflow will automatically run tests, build, publish to PyPI, and push Docker images tagged as `<git-tag>` and `latest`.

## Manual Deployment

### Prerequisites

1. PyPI account with API token
2. Get token from: https://pypi.org/manage/account/token/
3. Set environment variables:
   ```bash
   export TWINE_USERNAME=__token__
   export TWINE_PASSWORD=pypi-your-token-here
   ```
4. (Optional, for Docker publish) Docker Hub account and local Docker login:
   ```bash
   docker login
   export DOCKERHUB_USERNAME=your-dockerhub-user
   # Optional, defaults to llm-text-compressor
   export DOCKER_IMAGE_NAME=llm-text-compressor
   ```

## Deploy to PyPI

```bash
# Full deployment (runs tests, linting, builds, uploads)
./deploy.sh

# Skip tests (faster, but make sure tests pass first!)
./deploy.sh --skip-tests

# Use existing dist/ (rebuilds are usually recommended)
./deploy.sh --skip-build
```

## Deploy Docker image to Docker Hub

```bash
# Build + push Docker image, and also deploy package to PyPI/TestPyPI
./deploy.sh --docker

# Only build + push Docker image (skip package build/upload)
./deploy.sh --docker-only

# Custom image name
DOCKER_IMAGE_NAME=llm-text-compressor-api ./deploy.sh --docker
```

Docker tags pushed by script:

- `${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:${VERSION}` always
- `${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:latest` for production deploys (not `--test`)

## Test with TestPyPI first (recommended)

```bash
# Deploy to TestPyPI instead
./deploy.sh --test

# Deploy to TestPyPI and push versioned Docker tag
./deploy.sh --test --docker

# Then test installation
pip install --index-url https://test.pypi.org/simple/ llm-text-compressor
```

## What the script does

1. ✅ Runs pytest (124 tests)
2. ✅ Runs ruff linter
3. ✅ Runs mypy type checker
4. ✅ Cleans old builds
5. ✅ Builds wheel and sdist
6. ✅ Validates with twine
7. ✅ Shows version and asks for confirmation
8. ✅ Uploads to PyPI/TestPyPI (unless `--docker-only`)
9. ✅ Builds and pushes Docker image to Docker Hub (with `--docker`/`--docker-only`)

## Manual deployment

If you prefer to run commands manually:

```bash
# Run quality checks
pytest
ruff check src/ tests/
mypy src/

# Build package
rm -rf dist/
python3 -m build

# Validate
twine check dist/*

# Upload
twine upload dist/*                           # PyPI
twine upload --repository testpypi dist/*     # TestPyPI

# Docker image
docker build -t ${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:<version> .
docker push ${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:<version>
docker tag ${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:<version> ${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:latest
docker push ${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}:latest
```

## Before deploying

- [ ] Update version in `pyproject.toml`
- [ ] Update `SPECS.md` and `AGENTS.md` if needed
- [ ] All tests pass (`pytest`)
- [ ] No lint errors (`ruff check src/ tests/`)
- [ ] No type errors (`mypy src/`)
- [ ] Update CHANGELOG if you have one

## After deploying

1. Create a git tag for the version:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

2. Verify package on PyPI:
   - https://pypi.org/project/llm-text-compressor/

3. Test installation in a clean environment:
   ```bash
   pip install llm-text-compressor
   python -c "from llm_text_compressor import compress; print(compress('test'))"
   ```
