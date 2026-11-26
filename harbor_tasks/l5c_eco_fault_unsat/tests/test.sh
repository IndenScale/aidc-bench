#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l5c_eco_fault_unsat" \
  --workspace /workspace \
  --output-dir /logs/verifier
