#!/usr/bin/env bash
set -euo pipefail

source .venv311/bin/activate
echo "PYTHON VERSION: $(python --version)"

pip install -U pip
pip install -r requirements.txt
python scripts/build_projectdb.py