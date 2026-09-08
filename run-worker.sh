#!/bin/bash
# Simple script to run Jarvis OCR Worker using Poetry

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}Jarvis OCR Worker - Native Runner${NC}"
echo ""

# A local .venv takes precedence over Poetry.
#
# Hosts that run one provider do not want Poetry's full dependency set: the Mac
# mini exists to run Apple Vision and has no use for fastapi, tesseract or
# rapidocr. It also has no Poetry, and this script used to exit 1 there, which
# made the launchd agent crash-loop with a message about installing a build tool.
if [ -x ".venv/bin/python" ]; then
    echo -e "${GREEN}Using .venv${NC}"
    exec .venv/bin/python worker.py
fi

# Check if Poetry is installed
if ! command -v poetry &> /dev/null; then
    echo -e "${RED}Error: no .venv found and Poetry is not installed${NC}"
    echo "Either create a venv:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    echo "Or install Poetry:     curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is not installed${NC}"
    exit 1
fi

# Check if Redis is available
REDIS_PORT=${REDIS_PORT:-6379}
if ! command -v redis-cli &> /dev/null && ! docker ps | grep -q "jarvis-ocr-redis\|redis.*${REDIS_PORT}"; then
    echo -e "${YELLOW}Warning: Redis may not be running. Worker requires Redis to be available.${NC}"
    echo "Start Redis with: ./run.sh --enable-redis-queue"
    echo "Or ensure Redis is running on port ${REDIS_PORT}"
    echo ""
fi

# Install dependencies
echo -e "${YELLOW}Installing dependencies with Poetry...${NC}"
poetry install

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found. Using default environment variables.${NC}"
    echo "Create a .env file in the project root to customize configuration."
    echo ""
fi

# Run the worker
echo -e "${GREEN}Starting Jarvis OCR Worker...${NC}"
echo -e "${BLUE}Worker will continuously pull jobs from Redis queue and process them.${NC}"
echo -e "${BLUE}Press Ctrl+C to stop the worker.${NC}"
echo ""
poetry run python worker.py

