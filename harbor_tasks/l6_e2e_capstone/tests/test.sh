#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l6_e2e_capstone" \
  --workspace /workspace \
  --output-dir /logs/verifier
