#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l1_site_brownfield" \
  --workspace /workspace \
  --output-dir /logs/verifier
