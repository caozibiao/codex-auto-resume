#!/usr/bin/env python3
import json
import sys


def main():
    if len(sys.argv) != 6:
        raise SystemExit("usage: write_config.py PATH SESSION WORKSPACE MINUTES CODEX")
    path, session, workspace, minutes, codex = sys.argv[1:]
    value = {
        "version": 2,
        "codex_bin": codex,
        "default_workspace": workspace,
        "default_interval_seconds": int(minutes) * 60,
        "tasks": [{
            "id": session,
            "name": "My Codex task",
            "workspace": workspace,
            "interval_seconds": int(minutes) * 60,
            "enabled": True,
        }],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
