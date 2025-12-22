#!/bin/bash
# Setup launchd services for automatic startup
# Run this once to enable services to start on boot

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}Setting up launchd services for Jarvis OCR${NC}"
echo ""

# Get project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCHD_DIR"

# Update plist files with actual project path
echo -e "${BLUE}Updating plist files with project path...${NC}"

# Service plist
SERVICE_PLIST="$PROJECT_DIR/com.jarvis.ocr.service.plist"
if [ -f "$SERVICE_PLIST" ]; then
    # Replace placeholder path with actual path
    sed -i '' "s|/Users/jarvis/jarvis-ocr-service|$PROJECT_DIR|g" "$SERVICE_PLIST"
    echo -e "${GREEN}✓ Updated service plist${NC}"
else
    echo -e "${RED}Error: Service plist not found${NC}"
    exit 1
fi

# Worker plist
WORKER_PLIST="$PROJECT_DIR/com.jarvis.ocr.worker.plist"
if [ -f "$WORKER_PLIST" ]; then
    # Replace placeholder path with actual path
    sed -i '' "s|/Users/jarvis/jarvis-ocr-service|$PROJECT_DIR|g" "$WORKER_PLIST"
    echo -e "${GREEN}✓ Updated worker plist${NC}"
else
    echo -e "${RED}Error: Worker plist not found${NC}"
    exit 1
fi

# Copy plist files to LaunchAgents
echo ""
echo -e "${BLUE}Installing launchd services...${NC}"

# Unload existing services if they exist
if [ -f "$LAUNCHD_DIR/com.jarvis.ocr.service.plist" ]; then
    echo -e "${YELLOW}Unloading existing service...${NC}"
    launchctl unload "$LAUNCHD_DIR/com.jarvis.ocr.service.plist" 2>/dev/null || true
fi

if [ -f "$LAUNCHD_DIR/com.jarvis.ocr.worker.plist" ]; then
    echo -e "${YELLOW}Unloading existing worker...${NC}"
    launchctl unload "$LAUNCHD_DIR/com.jarvis.ocr.worker.plist" 2>/dev/null || true
fi

# Copy plist files
cp "$SERVICE_PLIST" "$LAUNCHD_DIR/"
cp "$WORKER_PLIST" "$LAUNCHD_DIR/"
echo -e "${GREEN}✓ Plist files copied to LaunchAgents${NC}"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"
echo -e "${GREEN}✓ Logs directory created${NC}"

# Load services
echo ""
echo -e "${BLUE}Loading launchd services...${NC}"
launchctl load "$LAUNCHD_DIR/com.jarvis.ocr.service.plist"
launchctl load "$LAUNCHD_DIR/com.jarvis.ocr.worker.plist"
echo -e "${GREEN}✓ Services loaded${NC}"

# Start services
echo ""
echo -e "${BLUE}Starting services...${NC}"
launchctl start com.jarvis.ocr.service
launchctl start com.jarvis.ocr.worker
echo -e "${GREEN}✓ Services started${NC}"

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo -e "${BLUE}Services will now start automatically on boot.${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo "  Check status: launchctl list | grep jarvis"
echo "  Stop service: launchctl stop com.jarvis.ocr.service"
echo "  Stop worker:  launchctl stop com.jarvis.ocr.worker"
echo "  Start service: launchctl start com.jarvis.ocr.service"
echo "  Start worker:  launchctl start com.jarvis.ocr.worker"
echo "  View logs:     tail -f $PROJECT_DIR/logs/service.log"
echo "                 tail -f $PROJECT_DIR/logs/worker.log"

