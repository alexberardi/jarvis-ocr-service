#!/bin/bash
# Script to fix Poetry installation and Python environment
# Run this once to fix the environment, then deploy.sh will work

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}Fixing Poetry and Python Environment${NC}"
echo ""

# Step 1: Check current Poetry installation
echo -e "${BLUE}Step 1: Checking current Poetry installation...${NC}"
if command -v poetry &> /dev/null; then
    POETRY_PATH=$(which poetry)
    echo -e "Found Poetry at: ${POETRY_PATH}"
    
    if [[ "$POETRY_PATH" =~ pyenv ]]; then
        echo -e "${YELLOW}Poetry is installed via pyenv (may cause issues)${NC}"
    fi
else
    echo -e "${YELLOW}Poetry is not installed${NC}"
fi

# Step 2: Install Poetry via Homebrew (recommended)
echo ""
echo -e "${BLUE}Step 2: Installing Poetry via Homebrew...${NC}"
if ! command -v brew &> /dev/null; then
    echo -e "${RED}Error: Homebrew is not installed${NC}"
    echo "Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

# Uninstall old Poetry if it exists and is from pyenv
if [[ "$POETRY_PATH" =~ pyenv ]] && [ -n "$POETRY_PATH" ]; then
    echo -e "${YELLOW}Removing pyenv Poetry installation...${NC}"
    # Don't remove, just note it - Homebrew will take precedence
fi

# Install via Homebrew
if brew list poetry &> /dev/null; then
    echo -e "${GREEN}Poetry is already installed via Homebrew${NC}"
    brew upgrade poetry 2>/dev/null || echo -e "${YELLOW}Poetry is up to date${NC}"
else
    echo -e "${BLUE}Installing Poetry via Homebrew...${NC}"
    brew install poetry
fi

# Verify Homebrew Poetry
if [ -f "/opt/homebrew/bin/poetry" ] || [ -f "/usr/local/bin/poetry" ]; then
    echo -e "${GREEN}✓ Poetry installed via Homebrew${NC}"
else
    echo -e "${RED}Error: Poetry installation failed${NC}"
    exit 1
fi

# Step 3: Configure Poetry to use system Python
echo ""
echo -e "${BLUE}Step 3: Configuring Poetry to use system Python...${NC}"

# Find system Python
SYSTEM_PYTHON=""
if [ -f "/usr/bin/python3" ]; then
    SYSTEM_PYTHON="/usr/bin/python3"
elif [ -f "/usr/local/bin/python3" ]; then
    SYSTEM_PYTHON="/usr/local/bin/python3"
fi

if [ -z "$SYSTEM_PYTHON" ]; then
    echo -e "${RED}Error: Could not find system Python${NC}"
    exit 1
fi

echo -e "Using Python: ${SYSTEM_PYTHON}"
$SYSTEM_PYTHON --version

# Configure Poetry (ensure we use Homebrew Poetry and bypass pyenv)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Remove pyenv from PATH temporarily
CLEAN_PATH=$(echo "$PATH" | tr ':' '\n' | grep -v pyenv | tr '\n' ':')
export PATH="$CLEAN_PATH"

# Configure Poetry to use system Python
poetry config virtualenvs.prefer-active-python false
poetry env use "$SYSTEM_PYTHON" --force 2>/dev/null || poetry env use "$SYSTEM_PYTHON"

echo -e "${GREEN}✓ Poetry configured to use system Python${NC}"

# Step 4: Test Poetry
echo ""
echo -e "${BLUE}Step 4: Testing Poetry...${NC}"
if poetry --version &> /dev/null; then
    echo -e "${GREEN}✓ Poetry is working${NC}"
    poetry --version
else
    echo -e "${RED}Error: Poetry is not working${NC}"
    exit 1
fi

# Step 5: Install dependencies
echo ""
echo -e "${BLUE}Step 5: Installing project dependencies...${NC}"
cd "$(dirname "$0")"
poetry install

echo ""
echo -e "${GREEN}✓ Environment fixed!${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Add Homebrew Poetry to your PATH (if not already):"
echo "     echo 'export PATH=\"/opt/homebrew/bin:/usr/local/bin:\$PATH\"' >> ~/.zshrc"
echo "     source ~/.zshrc"
echo ""
echo "  2. You can now run: ./deploy.sh"

