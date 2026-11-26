#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l4_control_ops_eol" \
  --workspace /workspace \
  --output-dir /logs/verifier
