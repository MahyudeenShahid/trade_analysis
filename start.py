#!/usr/bin/env python
"""
Quick start script for trading bot backend.

Usage:
    python start.py

Or with custom settings:
    python start.py --host 0.0.0.0 --port 8000
    python start.py --reload
"""

import subprocess
import sys

def main():
    # Default uvicorn settings
    args = [
        "uvicorn",
        "main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
    ]

    # Add any additional arguments passed by user
    if len(sys.argv) > 1:
        args.extend(sys.argv[1:])

    print("=" * 60)
    print("🚀 Starting Trading Bot Backend")
    print("=" * 60)
    print(f"Command: {' '.join(args)}")
    print()

    # Run uvicorn
    try:
        subprocess.run(args, check=True)
    except KeyboardInterrupt:
        print("\n\n[Shutdown] Backend stopped by user.")
    except Exception as e:
        print(f"\n[Error] Failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
