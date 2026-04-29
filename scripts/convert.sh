PATTERNS_TXT="data/patterns.txt"
PATTERNS_CSV="data/patterns.csv"

source .venv311/bin/activate
echo "PYTHON VERSION: $(python --version)"
python scripts/parse_patterns.py $PATTERNS_TXT $PATTERNS_CSV
