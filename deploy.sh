#!/usr/bin/env bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 llm-text-compressor deployment script${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: pyproject.toml not found. Run this script from the project root.${NC}"
    exit 1
fi

# Parse command line arguments
TARGET="pypi"
SKIP_TESTS=false
SKIP_BUILD=false
PUSH_DOCKER=false
DOCKER_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            TARGET="testpypi"
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --docker)
            PUSH_DOCKER=true
            shift
            ;;
        --docker-only)
            PUSH_DOCKER=true
            DOCKER_ONLY=true
            shift
            ;;
        --help)
            echo "Usage: ./deploy.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --test         Deploy to TestPyPI instead of PyPI"
            echo "  --skip-tests   Skip running tests before deployment"
            echo "  --skip-build   Skip cleaning and rebuilding (use existing dist/)"
            echo "  --docker       Build and push Docker image to Docker Hub"
            echo "  --docker-only  Only build and push Docker image (skip PyPI upload)"
            echo "  --help         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  TWINE_USERNAME  PyPI username (default: __token__)"
            echo "  TWINE_PASSWORD  PyPI API token (required)"
            echo "  DOCKERHUB_USERNAME  Docker Hub namespace/user (required with --docker)"
            echo "  DOCKER_IMAGE_NAME   Docker image name (default: llm-text-compressor)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Run './deploy.sh --help' for usage information"
            exit 1
            ;;
    esac
done

VERSION=$(grep -E '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

if [ "$PUSH_DOCKER" = true ] && [ -z "$DOCKERHUB_USERNAME" ]; then
    echo -e "${RED}❌ DOCKERHUB_USERNAME is required when using --docker or --docker-only${NC}"
    exit 1
fi

if [ -z "$DOCKER_IMAGE_NAME" ]; then
    DOCKER_IMAGE_NAME="llm-text-compressor"
fi

DOCKER_IMAGE="${DOCKERHUB_USERNAME}/${DOCKER_IMAGE_NAME}"

if [ "$DOCKER_ONLY" = true ]; then
    SKIP_BUILD=true
fi

# Step 1: Run tests
if [ "$SKIP_TESTS" = false ]; then
    echo -e "${YELLOW}📋 Running tests...${NC}"
    if ! pytest; then
        echo -e "${RED}❌ Tests failed! Fix them before deploying.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Tests passed${NC}"
    echo ""
fi

# Step 2: Lint and type check
echo -e "${YELLOW}🔍 Running linters...${NC}"
if ! ruff check src/ tests/; then
    echo -e "${RED}❌ Linting failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Linting passed${NC}"
echo ""

echo -e "${YELLOW}🔎 Running type checker...${NC}"
if ! mypy src/; then
    echo -e "${RED}❌ Type checking failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Type checking passed${NC}"
echo ""

# Step 3: Build Python package
if [ "$DOCKER_ONLY" = false ]; then
    if [ "$SKIP_BUILD" = false ]; then
        echo -e "${YELLOW}🧹 Cleaning old builds...${NC}"
        rm -rf dist/ build/ *.egg-info src/*.egg-info
        echo ""

        echo -e "${YELLOW}📦 Building package...${NC}"
        if ! python3 -m build; then
            echo -e "${RED}❌ Build failed!${NC}"
            exit 1
        fi
        echo -e "${GREEN}✅ Package built${NC}"
        echo ""
    fi

    # Step 4: Validate package
    echo -e "${YELLOW}✔️  Validating package...${NC}"
    if ! twine check dist/*; then
        echo -e "${RED}❌ Package validation failed!${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Package validated${NC}"
    echo ""

    # Step 5: Show what will be uploaded
    echo -e "${YELLOW}📋 Package contents:${NC}"
    ls -lh dist/
    echo ""
fi

# Step 6: Confirm deployment
if [ "$DOCKER_ONLY" = false ]; then
    if [ "$TARGET" = "testpypi" ]; then
        echo -e "${YELLOW}⚠️  You are about to deploy to TestPyPI${NC}"
    else
        echo -e "${YELLOW}⚠️  You are about to deploy to PyPI (production)${NC}"
    fi
fi
if [ "$PUSH_DOCKER" = true ]; then
    echo -e "${YELLOW}⚠️  Docker image will be built and pushed:${NC}"
    echo -e "${YELLOW}   ${DOCKER_IMAGE}:${GREEN}${VERSION}${NC}"
    if [ "$TARGET" != "testpypi" ]; then
        echo -e "${YELLOW}   ${DOCKER_IMAGE}:${GREEN}latest${NC}"
    fi
fi
echo -e "${YELLOW}   Version: ${GREEN}${VERSION}${NC}"
echo ""

read -p "Continue? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled${NC}"
    exit 0
fi

# Step 7: Upload Python package
if [ "$DOCKER_ONLY" = false ]; then
    echo ""
    echo -e "${YELLOW}🚀 Uploading to ${TARGET}...${NC}"

    if [ "$TARGET" = "testpypi" ]; then
        if ! twine upload --repository testpypi dist/*; then
            echo -e "${RED}❌ Upload to TestPyPI failed!${NC}"
            exit 1
        fi
        echo ""
        echo -e "${GREEN}✅ Successfully deployed to TestPyPI!${NC}"
        echo -e "${GREEN}   View at: https://test.pypi.org/project/llm-text-compressor/${VERSION}/${NC}"
        echo ""
        echo -e "${YELLOW}To test installation:${NC}"
        echo "   pip install --index-url https://test.pypi.org/simple/ llm-text-compressor"
    else
        if ! twine upload dist/*; then
            echo -e "${RED}❌ Upload to PyPI failed!${NC}"
            echo ""
            echo -e "${YELLOW}Common issues:${NC}"
            echo "  1. Make sure TWINE_USERNAME=__token__"
            echo "  2. Make sure TWINE_PASSWORD is set to your PyPI token"
            echo "  3. Check that the token has upload permissions"
            echo "  4. This version might already exist on PyPI"
            exit 1
        fi
        echo ""
        echo -e "${GREEN}✅ Successfully deployed to PyPI!${NC}"
        echo -e "${GREEN}   View at: https://pypi.org/project/llm-text-compressor/${VERSION}/${NC}"
        echo ""
        echo -e "${YELLOW}To install:${NC}"
        echo "   pip install llm-text-compressor"
    fi
fi

# Step 8: Build and push Docker image
if [ "$PUSH_DOCKER" = true ]; then
    echo ""
    echo -e "${YELLOW}🐳 Building Docker image...${NC}"
    if ! docker build -t "${DOCKER_IMAGE}:${VERSION}" .; then
        echo -e "${RED}❌ Docker build failed!${NC}"
        exit 1
    fi

    if [ "$TARGET" != "testpypi" ]; then
        if ! docker tag "${DOCKER_IMAGE}:${VERSION}" "${DOCKER_IMAGE}:latest"; then
            echo -e "${RED}❌ Failed to tag Docker image as latest!${NC}"
            exit 1
        fi
    fi

    echo -e "${YELLOW}📤 Pushing Docker image ${DOCKER_IMAGE}:${VERSION}...${NC}"
    if ! docker push "${DOCKER_IMAGE}:${VERSION}"; then
        echo -e "${RED}❌ Docker push failed for ${DOCKER_IMAGE}:${VERSION}!${NC}"
        exit 1
    fi

    if [ "$TARGET" != "testpypi" ]; then
        echo -e "${YELLOW}📤 Pushing Docker image ${DOCKER_IMAGE}:latest...${NC}"
        if ! docker push "${DOCKER_IMAGE}:latest"; then
            echo -e "${RED}❌ Docker push failed for ${DOCKER_IMAGE}:latest!${NC}"
            exit 1
        fi
    fi

    echo ""
    echo -e "${GREEN}✅ Docker image pushed successfully!${NC}"
    echo -e "${GREEN}   View at: https://hub.docker.com/r/${DOCKER_IMAGE}${NC}"
fi

echo ""
echo -e "${GREEN}🎉 Deployment complete!${NC}"
