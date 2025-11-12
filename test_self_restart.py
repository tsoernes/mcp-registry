#!/usr/bin/env python3
"""Test self-restart mechanism for MCP servers."""

import os
import sys

def self_restart():
    """Restart the current process by replacing it with a new instance.
    
    This uses os.execv() to replace the current process, which:
    - Keeps the same PID
    - Preserves file descriptors (stdin/stdout/stderr)
    - Reloads all Python modules
    - Doesn't break stdio connections
    """
    python = sys.executable
    args = [python] + sys.argv
    
    print(f"Restarting: {' '.join(args)}", file=sys.stderr)
    
    # os.execv replaces the current process
    # File descriptors 0, 1, 2 (stdin, stdout, stderr) are preserved
    os.execv(python, args)
    
    # This line never executes because the process was replaced

if __name__ == "__main__":
    import time
    
    # Simulate a running server
    start_time = time.time()
    
    print(f"Server started at {start_time}")
    print("Type 'restart' to restart, 'quit' to exit")
    
    for line in sys.stdin:
        line = line.strip()
        
        if line == "restart":
            print("Initiating self-restart...")
            self_restart()  # This replaces the process!
            
        elif line == "quit":
            print("Exiting...")
            break
            
        else:
            uptime = time.time() - start_time
            print(f"Echo: {line} (uptime: {uptime:.1f}s)")
