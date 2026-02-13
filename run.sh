#!/bin/bash
# Development server
# Usage: ./run.sh [--docker] [--enable-redis-queue]

set -e
cd "$(dirname "$0")"

# Check for docker mode
if [[ "$1" == "--docker" ]]; then
    # Docker development mode
    BUILD_FLAGS=""
    if [[ "$2" == "--rebuild" ]]; then
        docker compose --env-file .env -f docker-compose.dev.yaml build --no-cache
        BUILD_FLAGS="--build"
    elif [[ "$2" == "--build" ]]; then
        BUILD_FLAGS="--build"
    fi
    docker compose --env-file .env -f docker-compose.dev.yaml up $BUILD_FLAGS
    exit 0
fi

# Local development mode with Poetry

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
ENABLE_REDIS=false
for arg in "$@"; do
    case $arg in
        --enable-redis-queue)
            ENABLE_REDIS=true
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

echo -e "${GREEN}Jarvis OCR Service - Development Server${NC}"
echo ""

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
    echo -e "${RED}Error: Poetry is not installed${NC}"
    echo "Install Poetry: curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is not installed${NC}"
    exit 1
fi

# Start Redis if enabled
if [ "$ENABLE_REDIS" = true ]; then
    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is required to run Redis queue. Please install Docker.${NC}"
        exit 1
    fi

    # Check if Redis is already running
    REDIS_PORT=${REDIS_PORT:-6379}
    if docker ps | grep -q "jarvis-ocr-redis"; then
        echo -e "${BLUE}Redis is already running on port ${REDIS_PORT}${NC}"
    else
        echo -e "${YELLOW}Starting Redis queue...${NC}"
        docker run -d \
            --name jarvis-ocr-redis \
            -p "${REDIS_PORT}:6379" \
            redis:7-alpine \
            redis-server --appendonly yes

        # Wait a moment for Redis to start
        sleep 2
        echo -e "${GREEN}Redis started on port ${REDIS_PORT}${NC}"
    fi
else
    echo -e "${YELLOW}Redis queue disabled (use --enable-redis-queue to enable)${NC}"
fi

# Install dependencies
echo -e "${YELLOW}Installing dependencies with Poetry...${NC}"
poetry install

# Install local jarvis packages
echo -e "${YELLOW}Installing local jarvis packages...${NC}"
pip install -q -e ../jarvis-config-client 2>/dev/null || echo -e "${YELLOW}Note: jarvis-config-client not found locally${NC}"
pip install -q -e ../jarvis-settings-client 2>/dev/null || echo -e "${YELLOW}Note: jarvis-settings-client not found locally${NC}"

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found. Using default environment variables.${NC}"
    echo "Create a .env file in the project root to customize configuration."
    echo ""
fi

# Run the service
echo -e "${GREEN}Starting Jarvis OCR Service...${NC}"
echo ""
poetry run python main.py
