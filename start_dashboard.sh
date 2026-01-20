#!/bin/bash

# Check if virtual environment is active
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "⚠️  Virtual environment not active. Activating..."
    source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null
fi

# Set default API URL if not set
export DASHBOARD_API_URL="http://localhost:8080"

echo "🚀 Starting Swarm Trading Dashboard..."
echo "📊 Connecting to API at: $DASHBOARD_API_URL"

# Run Streamlit
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0
