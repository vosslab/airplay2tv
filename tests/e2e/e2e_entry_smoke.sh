#!/usr/bin/env bash
# Smoke test: verify the repo-root stream.py launcher entry point works.
# Runs from the repo root. Exits non-zero on failure, zero on success.

set -eo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "[e2e_entry_smoke] Testing: source source_me.sh && python3 stream.py --help"
source source_me.sh && python3 stream.py --help > /dev/null
echo "[e2e_entry_smoke] PASS: python3 stream.py --help exited 0"

echo "[e2e_entry_smoke] Testing: ./stream.py --help (shebang + exec bit)"
./stream.py --help > /dev/null
echo "[e2e_entry_smoke] PASS: ./stream.py --help exited 0"

echo "[e2e_entry_smoke] All checks passed."
