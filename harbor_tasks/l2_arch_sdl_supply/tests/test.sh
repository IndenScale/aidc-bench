#!/bin/bash
set -euo pipefail
python3 /opt/aidc-bench/judge/v3/verify_harbor.py \
  --task-id "l2_arch_sdl_supply" \
  --workspace /workspace \
  --output-dir /logs/verifier
