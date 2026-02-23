# Deployment Guide

Quick reference for publishing new versions to PyPI.

## Prerequisites

1. PyPI account with API token
2. Get token from: https://pypi.org/manage/account/token/
3. Set environment variables:
   ```bash
   export TWINE_USERNAME=__token__
   export TWINE_PASSWORD=pypi-your-token-here
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

## Test with TestPyPI first (recommended)

```bash
# Deploy to TestPyPI instead
./deploy.sh --test

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
8. ✅ Uploads to PyPI/TestPyPI

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
