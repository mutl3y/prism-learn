# tools/run-rotate.sh
#!/usr/bin/env bash
export OPENAI_API_KEY="${GITHUB_TOKEN}"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
export CHAT_HISTORY="${CHAT_HISTORY:-.local/tmp_context/chat_history.jsonl}"
export SNAPSHOT_FILE="${SNAPSHOT_FILE:-.local/tmp_context/snapshots.jsonl}"

# Prefer project virtualenv when present so dependencies are resolved reliably.
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
	PYTHON_BIN="python3"
fi

mkdir -p "$(dirname "${CHAT_HISTORY}")"
mkdir -p "$(dirname "${SNAPSHOT_FILE}")"

"${PYTHON_BIN}" scripts/rotate_summarize.py