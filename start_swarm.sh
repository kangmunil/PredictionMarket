#!/bin/bash

# PredictionMarket Swarm System Startup Script
# This script ensures the correct Python environment is used

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}PredictionMarket Swarm System${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Error: Virtual environment not found!${NC}"
    echo -e "${YELLOW}Please create a virtual environment first:${NC}"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found!${NC}"
    echo "Please create a .env file with required API keys."
    echo ""
fi

# Use venv Python
PYTHON="$SCRIPT_DIR/venv/bin/python"

echo -e "${GREEN}🐍 Using Python:${NC} $PYTHON"
echo -e "${GREEN}📁 Working Directory:${NC} $SCRIPT_DIR"
echo ""

# Parse arguments
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Usage: ./start_swarm.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --ui          Launch with TUI Dashboard"
    echo "  --dry-run     Run in paper trading mode (no real trades)"
    echo "  --help, -h    Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./start_swarm.sh --ui --dry-run    # Launch with UI in dry-run mode"
    echo "  ./start_swarm.sh --dry-run         # Run without UI in dry-run mode"
    echo "  ./start_swarm.sh                   # Run in live mode (WARNING: real trading!)"
    exit 0
fi

# Forward all arguments to run_swarm.py
echo -e "${GREEN}🚀 Starting Swarm System...${NC}"
echo ""
exec "$PYTHON" run_swarm.py "$@"
