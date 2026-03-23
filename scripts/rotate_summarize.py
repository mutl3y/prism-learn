#!/usr/bin/env python3
"""
rotate_summarize.py
Auto-summarize & rotate chat history (JSONL).
History format (chat_history.jsonl): one JSON per line: {"role":"user|assistant|system","content":"...","ts":162...}
Snapshots written to snapshots.jsonl: {"snapshot_id": "...", "summary":"...", "range":[start_idx,end_idx], "ts":...}
"""

import os, json, time, uuid, sys
from typing import List
import openai

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
openai.api_key = os.environ.get("OPENAI_API_KEY")

HISTORY_PATH = os.environ.get("CHAT_HISTORY", "chat_history.jsonl")
SNAPSHOT_PATH = os.environ.get("SNAPSHOT_FILE", "snapshots.jsonl")
CHAR_THRESHOLD = int(os.environ.get("CHAR_THRESHOLD", 22000))  # approximate trigger (chars)
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 8))  # messages to summarize at once
SUMMARY_PLACEHOLDER_TEMPLATE = "Summary(snapshot_id={id})"

def load_history(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def save_history(path: str, messages: List[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

def append_snapshot(snapshot: dict):
    with open(SNAPSHOT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

def approx_chars(messages: List[dict]) -> int:
    return sum(len(m.get("content","")) for m in messages)

def summarize_messages(messages: List[dict]) -> str:
    if not openai.api_key:
        raise RuntimeError("OPENAI_API_KEY is required when rotation is needed.")

    # Build a prompt with the messages (only content and role)
    system = {
        "role": "system",
        "content": (
            "You are a concise summarizer. Produce a short, structured summary "
            "of the conversation segment: include main intents, unresolved actions, "
            "and important facts. Keep it <= 200 words."
        )
    }
    chat_msgs = [system] + [{"role": m["role"], "content": m["content"]} for m in messages]
    resp = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=chat_msgs,
        temperature=0.2,
        max_tokens=400,
    )
    return resp.choices[0].message["content"].strip()

def rotate_and_summarize():
    msgs = load_history(HISTORY_PATH)
    if not msgs:
        print(f"No history messages found at {HISTORY_PATH}; nothing to rotate.")
        return

    total_chars = approx_chars(msgs)
    if total_chars <= CHAR_THRESHOLD:
        print(
            f"No rotation needed: approx_chars={total_chars} <= CHAR_THRESHOLD={CHAR_THRESHOLD}."
        )
        return

    # find oldest chunk to summarize
    chunk = msgs[:CHUNK_SIZE]
    summary_text = summarize_messages(chunk)
    snap_id = str(uuid.uuid4())
    snapshot = {
        "snapshot_id": snap_id,
        "summary": summary_text,
        "range": [0, len(chunk)-1],
        "created_ts": int(time.time()),
        "source_count": len(chunk)
    }
    append_snapshot(snapshot)

    # replace chunk with a single summary placeholder message from system
    placeholder = {
        "role": "system",
        "content": SUMMARY_PLACEHOLDER_TEMPLATE.format(id=snap_id),
        "ts": int(time.time())
    }
    new_msgs = [placeholder] + msgs[len(chunk):]

    # Save rotated history
    save_history(HISTORY_PATH, new_msgs)
    print(f"Rotated {len(chunk)} messages into snapshot {snap_id}")

if __name__ == "__main__":
    try:
        rotate_and_summarize()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
