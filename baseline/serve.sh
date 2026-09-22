#!/usr/bin/env bash
# Serve the stack in DEST (default ./vllm) with the published champion v0 settings, for local testing.
# Needs one GPU of the profile's type for numbers that mean anything; RamCove measures only on its workers.
set -euo pipefail
DEST=${1:-vllm}
HERE=$(cd "$(dirname "$0")" && pwd)
pip install -e "$DEST"
ARGS=$(python3 -c "
import json
d = json.load(open('$HERE/engine_args.json'))
out = []
for k, v in d['args'].items():
    if v is True:
        out.append('--' + k)
    elif v is not False:
        out += ['--' + k, str(v)]
print(' '.join(out))")
MODEL=$(python3 -c "import json; print(json.load(open('$HERE/engine_args.json'))['model']['repo'])")
REV=$(python3 -c "import json; print(json.load(open('$HERE/engine_args.json'))['model']['revision'])")
exec vllm serve "$MODEL" --revision "$REV" $ARGS
