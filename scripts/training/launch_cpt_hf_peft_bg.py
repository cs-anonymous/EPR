#!/usr/bin/env python3
"""Launch HF+PEFT CPT training in background and print PID/log path."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if not args.cmd:
        raise ValueError("No command provided")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = args.log.open("ab", buffering=0)
    proc = subprocess.Popen(
        args.cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=os.getcwd(),
        start_new_session=True,
        env=os.environ.copy(),
    )
    print(proc.pid)
    print(args.log)


if __name__ == "__main__":
    main()
