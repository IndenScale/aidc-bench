#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l5b_eco_major_pivot" \
  --workspace /workspace \
  --output-dir /logs/verifier
