#!/usr/bin/env python3
"""Guided mapper for SO101 leader/follower serial ports on macOS/Linux."""

from __future__ import annotations

import sys
import time
import subprocess
import shutil
from pathlib import Path


def list_modem_ports() -> list[str]:
    return sorted(str(p) for p in Path("/dev").glob("cu.usbmodem*"))


def wait_for_port_change(before: set[str], timeout_s: float = 20.0) -> tuple[set[str], set[str]]:
    start = time.time()
    while time.time() - start < timeout_s:
        now = set(list_modem_ports())
        added = now - before
        removed = before - now
        if added or removed:
            return added, removed
        time.sleep(0.2)
    return set(), set()


def detect_port_for(label: str) -> str:
    print(f"\n--- Detecting {label} port ---")
    print("1) Disconnect ONLY this device now.")
    input("   Press Enter when disconnected...")
    baseline = set(list_modem_ports())
    print(f"   Current ports: {sorted(baseline) or 'none'}")
    print("2) Reconnect ONLY this device now.")
    input("   Press Enter right after reconnecting...")

    added, removed = wait_for_port_change(baseline)
    if len(added) == 1:
        port = next(iter(added))
        print(f"   Detected {label} on: {port}")
        return port

    if len(added) == 0:
        raise RuntimeError(
            f"Could not detect {label}: no new port appeared. "
            "Try again and press Enter immediately after reconnecting."
        )

    raise RuntimeError(f"Could not detect {label}: multiple new ports appeared: {sorted(added)}")


def run_cmd(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    return result.returncode


def calibrate_so101(leader_port: str, follower_port: str) -> bool:
    print("\n=== Calibration ===")
    print("Keep both arms powered and connected.")
    do_calibrate = input("Run calibration now? [Y/n]: ").strip().lower()
    if do_calibrate in {"n", "no"}:
        print("Skipping calibration.")
        return True

    calibrate_bin = shutil.which("lerobot-calibrate")
    if calibrate_bin:
        leader_cmd = [
            calibrate_bin,
            "--teleop.type=so101_leader",
            f"--teleop.port={leader_port}",
        ]
        follower_cmd = [
            calibrate_bin,
            "--robot.type=so101_follower",
            f"--robot.port={follower_port}",
        ]
    else:
        print("`lerobot-calibrate` not found, using `python -m lerobot.calibrate` fallback.")
        leader_cmd = [
            "python",
            "-m",
            "lerobot.calibrate",
            "--teleop.type=so101_leader",
            f"--teleop.port={leader_port}",
        ]
        follower_cmd = [
            "python",
            "-m",
            "lerobot.calibrate",
            "--robot.type=so101_follower",
            f"--robot.port={follower_port}",
        ]

    if run_cmd(leader_cmd) != 0:
        print("Leader calibration failed.")
        return False
    if run_cmd(follower_cmd) != 0:
        print("Follower calibration failed.")
        return False
    print("Calibration finished successfully.")
    return True


def main() -> int:
    print("SO101 Port Mapper (leader/follower)")
    print("This script identifies each arm by unplug/replug.")
    print(f"Initial modem ports: {list_modem_ports() or 'none'}")

    try:
        leader_port = detect_port_for("LEADER")
        follower_port = detect_port_for("FOLLOWER")
    except RuntimeError as err:
        print(f"\nError: {err}")
        return 1

    print("\n=== Result ===")
    print(f"LEADER_PORT={leader_port}")
    print(f"FOLLOWER_PORT={follower_port}")
    if not calibrate_so101(leader_port, follower_port):
        return 1
    print("\nRun this command:")
    print(
        "lerobot-teleoperate "
        "--robot.type=so101_follower "
        f"--robot.port={follower_port} "
        "--teleop.type=so101_leader "
        f"--teleop.port={leader_port} "
        "--display_data=true"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
