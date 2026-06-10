#!/usr/bin/env bash
# Record an asciinema demo of the quickstart flow.
#
# Usage:
#   ./scripts/record-demo.sh            # records demo.cast in the repo root
#   agg demo.cast demo.gif              # optional: convert to GIF (https://github.com/asciinema/agg)
#
# Requires: asciinema (https://asciinema.org), uv, and the repo's dev extras.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v asciinema >/dev/null 2>&1; then
    echo "asciinema not found. Install it first: https://docs.asciinema.org/manual/cli/installation/" >&2
    exit 1
fi

DEMO_SCRIPT=$(mktemp)
trap 'rm -f "$DEMO_SCRIPT"' EXIT
cat > "$DEMO_SCRIPT" <<'EOF'
set -e
WORKSPACE=$(mktemp -d)
echo "\$ skill-eval list"
uv run skill-eval list
sleep 1
echo
echo "\$ skill-eval validate examples/write-release-notes/evals/evals.json"
uv run skill-eval validate examples/write-release-notes/evals/evals.json
sleep 1
echo
echo "\$ skill-eval run --skill skills/write-release-notes --evals examples/write-release-notes/evals/evals.json --agent claude-code --agent-model claude-code=haiku"
uv run skill-eval run \
    --skill skills/write-release-notes \
    --evals examples/write-release-notes/evals/evals.json \
    --agent claude-code \
    --agent-model claude-code=haiku \
    --workspace "$WORKSPACE"
sleep 1
echo
echo "\$ skill-eval report --workspace $WORKSPACE/write-release-notes-workspace"
uv run skill-eval report --workspace "$WORKSPACE/write-release-notes-workspace"
EOF

asciinema rec --overwrite -c "bash $DEMO_SCRIPT" demo.cast
echo "Recorded demo.cast. Convert with: agg demo.cast demo.gif"
