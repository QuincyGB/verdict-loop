#!/usr/bin/env bash
# Daily live demo run for verdict-loop.
#
# Executes one LIVE pass (real USDC on Base from the agent wallet,
# behind the in-code $0.10/day spend cap and the balance guard),
# appends the dated entry to docs/live-log.md, and commits + pushes
# the log to the public repo.
#
# Signer: AGENT_KEY_FILE (default: $HOME/.evm-wallet/key). The key is
# only ever read by the loop from the environment — never printed,
# never committed (.gitignore excludes *.key / .env, and the budget
# ledger is gitignored too).
#
# Exit status is the loop's own exit code:
#   0 = pass completed, 1 = completed with service errors,
#   2 = no signer / bad config, 3 = insufficient funds (clean stop).
set -uo pipefail
cd "$(dirname "$0")/.."

KEY_FILE="${AGENT_KEY_FILE:-$HOME/.evm-wallet/key}"
if [ ! -f "$KEY_FILE" ]; then
  echo "run_daily: no key file at $KEY_FILE (set AGENT_KEY_FILE)" >&2
  exit 2
fi

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

AGENT_KEY_FILE="$KEY_FILE" .venv/bin/python -m verdict_loop \
  --config config.json --live >"$OUT" 2>&1
CODE=$?
cat "$OUT"

.venv/bin/python scripts/append_log.py \
  --output "$OUT" --exit-code "$CODE" || exit 1

git add docs/live-log.md
if git diff --cached --quiet; then
  echo "run_daily: log unchanged — nothing to commit"
else
  git commit -q -m "live demo run $(date -u +%F)"
  git push -q origin HEAD
  echo "run_daily: log committed and pushed"
fi
exit "$CODE"
