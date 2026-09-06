#!/bin/bash
# One-shot agent run, invoked by launchd every 6 hours.
# Uses the venv's python and calls run_agent() directly (skipping the
# in-process 6-hour scheduler so launchd owns the cadence).
set -euo pipefail

PROJECT_DIR="$HOME/Desktop/tastes-of-india"
cd "$PROJECT_DIR"

source venv/bin/activate
python -c "from agent.recipe_agent import run_agent; run_agent()"
