#!/usr/bin/env python3
"""Demonstrate self-restart preserves state."""

import os
import sys
import json
from pathlib import Path

STATE_FILE = "/tmp/restart_demo_state.json"

def save_state(counter):
    """Save state to file."""
    Path(STATE_FILE).write_text(json.dumps({"counter": counter}))

def load_state():
    """Load state from file."""
    if Path(STATE_FILE).exists():
        data = json.loads(Path(STATE_FILE).read_text())
        return data.get("counter", 0)
    return 0

def self_restart():
    """Restart the process."""
    os.execv(sys.executable, [sys.executable] + sys.argv)

def main():
    # Load previous state
    counter = load_state()
    counter += 1
    
    print(f"Execution #{counter} - PID: {os.getpid()}", file=sys.stderr)
    print(f"Python version: {sys.version}", file=sys.stderr)
    
    # Save state
    save_state(counter)
    
    # Restart after 3 iterations
    if counter < 3:
        print(f"Restarting (iteration {counter}/3)...", file=sys.stderr)
        self_restart()
    else:
        print("Done! Cleaned up state.", file=sys.stderr)
        Path(STATE_FILE).unlink(missing_ok=True)

if __name__ == "__main__":
    main()
