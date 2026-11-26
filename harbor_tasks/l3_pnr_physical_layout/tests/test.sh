#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l3_pnr_physical_layout" \
  --workspace /workspace \
  --output-dir /logs/verifier
