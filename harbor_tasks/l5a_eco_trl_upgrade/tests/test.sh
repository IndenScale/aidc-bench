#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l5a_eco_trl_upgrade" \
  --workspace /workspace \
  --output-dir /logs/verifier
