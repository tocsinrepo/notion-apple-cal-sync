"""Tiny JSON mapping store.

`sync_state.json` records the links between Notion pages and Apple events plus
the last-known "canonical" fingerprint of each side, so we can tell what changed
between runs. It is committed back to the repo by the GitHub Action.
"""
import json
import os


def load_state(path):
    if not os.path.exists(path):
        return {"links": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "links" not in data:
            data["links"] = []
        return data
    except (json.JSONDecodeError, OSError):
        return {"links": []}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
