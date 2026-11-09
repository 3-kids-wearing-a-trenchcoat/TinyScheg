#!/usr/bin/env bash
set -e

# Must match the name in environment.yml
ENV_NAME="tinyscheg"

# Modules in src/ import each other by bare module name (e.g. `from DateTimeRange import ...`),
# so src/ must be on the import path no matter where this script is called from.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Print output as it happens: `conda run` would otherwise capture it and replay it only on exit,
# and Python block-buffers stdout when it isn't a terminal.
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

# Ensure conda is available
if ! command -v conda &> /dev/null; then
    echo "Conda not found. Please install Miniconda/Miniforge/Anaconda."
    exit 1
fi

# Run inside the correct environment
conda run --no-capture-output -n "$ENV_NAME" python "$@"
