#!/usr/bin/env bash
# Fetch the baseline engine at the pinned commit and, optionally, apply the champion's patches on top.
#
#   baseline/fetch.sh [DEST] [PATCH_DIR]
#
# DEST defaults to ./vllm. PATCH_DIR is a folder of numbered champion patches as written by
# `ramcove-miner champion-code --out PATCH_DIR`; they are applied in order, oldest first. The result is the
# stack a new challenger must build on: champion version 0 when PATCH_DIR is empty or omitted.
set -euo pipefail
COMMIT=98dff2a81d747d1dba01a47f939f48c3526d4206
DEST=${1:-vllm}
PATCHES=${2:-}
if [ ! -d "$DEST/.git" ]; then
  git clone --filter=blob:none https://github.com/vllm-project/vllm.git "$DEST"
fi
git -C "$DEST" fetch --quiet origin "$COMMIT"
git -C "$DEST" checkout --quiet --detach "$COMMIT"
test "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT"
echo "baseline: vllm-project/vllm at $COMMIT in $DEST"
if [ -n "$PATCHES" ]; then
  for p in $(ls "$PATCHES"/*.diff 2>/dev/null | sort); do
    git -C "$DEST" apply --index "$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
    echo "applied $(basename "$p")"
  done
fi
