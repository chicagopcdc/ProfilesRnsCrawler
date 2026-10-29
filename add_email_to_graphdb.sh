#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
RUN_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_FILE:-$LOG_DIR/add_email_to_graphdb_${RUN_TIMESTAMP}.log}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Default values for GraphDB connection and CSV file
export GRAPHDB_STATEMENTS_URL="${GRAPHDB_STATEMENTS_URL:-http://localhost:7200/repositories/julian/statements}"
export GRAPHDB_NAMED_GRAPH="${GRAPHDB_NAMED_GRAPH:-http://example.org/graph/emails}"

# UChicago
# export CSV_FILE="${CSV_FILE:-email/uchicago_extracted_all.csv}"
# Rush
export CSV_FILE="${CSV_FILE:-email/rush_extracted_all.csv}"

export CHUNK_SIZE="${CHUNK_SIZE:-500}"

mkdir -p "$LOG_DIR"

echo "Running add_email_to_graphdb.py with:"
echo "  PYTHON_BIN=$PYTHON_BIN"
echo "  GRAPHDB_STATEMENTS_URL=$GRAPHDB_STATEMENTS_URL"
echo "  GRAPHDB_NAMED_GRAPH=$GRAPHDB_NAMED_GRAPH"
echo "  CSV_FILE=$CSV_FILE"
echo "  CHUNK_SIZE=$CHUNK_SIZE"
echo "  LOG_FILE=$LOG_FILE"

cd "$SCRIPT_DIR"
"$PYTHON_BIN" add_email_to_graphdb.py 2>&1 | tee "$LOG_FILE"