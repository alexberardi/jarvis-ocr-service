#!/bin/bash
# Deployment script for Jarvis OCR Service (native macOS)
# Usage: ./deploy.sh [--skip-deps] [--restart-worker]

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
SKIP_DEPS=false
RESTART_WORKER=false
for arg in "$@"; do
    case $arg in
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --restart-worker)
            RESTART_WORKER=true
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

echo -e "${GREEN}Jarvis OCR Service - Deployment${NC}"
echo ""

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}Error: Not a git repository${NC}"
    exit 1
fi

# Check current branch
CURRENT_BRANCH=$(git branch --show-current)
echo -e "${BLUE}Current branch: ${CURRENT_BRANCH}${NC}"

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Pull latest changes
echo -e "${YELLOW}Pulling latest changes from git...${NC}"
git pull origin "${CURRENT_BRANCH}" || {
    echo -e "${RED}Error: Failed to pull from git${NC}"
    exit 1
}
echo -e "${GREEN}✓ Git pull successful${NC}"

# Install/update dependencies
if [ "$SKIP_DEPS" = false ]; then
    echo -e "${YELLOW}Installing/updating dependencies with Poetry...${NC}"
    if ! command -v poetry &> /dev/null; then
        echo -e "${RED}Error: Poetry is not installed${NC}"
        exit 1
    fi
    poetry install
    echo -e "${GREEN}✓ Dependencies updated${NC}"
else
    echo -e "${YELLOW}Skipping dependency installation${NC}"
fi

# Find and stop running service processes
echo -e "${YELLOW}Checking for running service processes...${NC}"

# Find main.py processes
MAIN_PIDS=$(pgrep -f "python.*main.py" || true)
if [ -n "$MAIN_PIDS" ]; then
    echo -e "${BLUE}Found running service (PIDs: ${MAIN_PIDS})${NC}"
    echo -e "${YELLOW}Stopping service...${NC}"
    echo "$MAIN_PIDS" | xargs kill -TERM || true
    sleep 2
    # Force kill if still running
    REMAINING=$(pgrep -f "python.*main.py" || true)
    if [ -n "$REMAINING" ]; then
        echo -e "${YELLOW}Force killing remaining processes...${NC}"
        echo "$REMAINING" | xargs kill -9 || true
    fi
    echo -e "${GREEN}✓ Service stopped${NC}"
else
    echo -e "${BLUE}No running service found${NC}"
fi

# Find and stop worker processes if requested
if [ "$RESTART_WORKER" = true ]; then
    WORKER_PIDS=$(pgrep -f "python.*worker.py" || true)
    if [ -n "$WORKER_PIDS" ]; then
        echo -e "${BLUE}Found running worker (PIDs: ${WORKER_PIDS})${NC}"
        echo -e "${YELLOW}Stopping worker...${NC}"
        echo "$WORKER_PIDS" | xargs kill -TERM || true
        sleep 2
        # Force kill if still running
        REMAINING=$(pgrep -f "python.*worker.py" || true)
        if [ -n "$REMAINING" ]; then
            echo -e "${YELLOW}Force killing remaining worker processes...${NC}"
            echo "$REMAINING" | xargs kill -9 || true
        fi
        echo -e "${GREEN}✓ Worker stopped${NC}"
    else
        echo -e "${BLUE}No running worker found${NC}"
    fi
fi

echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Start the service: ./run.sh [--enable-redis-queue]"
if [ "$RESTART_WORKER" = true ]; then
    echo "  2. Start the worker: ./run-worker.sh"
fi
echo ""
echo -e "${YELLOW}Note: The service and worker are not automatically started.${NC}"
echo -e "${YELLOW}Start them manually or use a process manager (e.g., launchd, supervisor, pm2).${NC}"

