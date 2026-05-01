#!/usr/bin/env python3
"""
Guided setup for bimanual SO-101: map 4 serial arms, optional calibration,
and print a `lerobot-teleoperate` command (`bi_so101_*`).

Uses the same unplug/replug idea as `map_so101_ports.py` for serial devices.

Camera mapping (OpenCV unplug/replug) is commented out in this file; add
``--robot.cameras=...`` manually or use ``lerobot-find-cameras`` if you need vision.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import FrozenSet

# This script lives in ``scripts/``; local package is ``../src/lerobot``.
REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_SRC = REPO_ROOT / "src"


def use_repo_src_for_cli() -> bool:
    return (REPO_SRC / "lerobot").is_dir()


def env_with_repo_src() -> dict[str, str]:
    env = os.environ.copy()
    prefix = str(REPO_SRC)
    if (prev := env.get("PYTHONPATH")):
        prefix = f"{prefix}{os.pathsep}{prev}"
    env["PYTHONPATH"] = prefix
    return env


def list_arm_serial_ports() -> list[str]:
    """Serial ports used by SO-101 USB boards (macOS cu.* / Linux ttyACM ttyUSB)."""
    dev = Path("/dev")
    if platform.system() == "Darwin":
        patterns = ("cu.usbmodem*", "cu.usbserial*", "cu.usbserial-*")
    else:
        patterns = ("ttyACM*", "ttyUSB*", "ttyUSB-*")
    paths: set[str] = set()
    for pat in patterns:
        paths.update(str(p) for p in dev.glob(pat))
    return sorted(paths)


def wait_for_serial_change(
    before: FrozenSet[str], timeout_s: float = 25.0
) -> tuple[set[str], set[str]]:
    start = time.time()
    while time.time() - start < timeout_s:
        now = frozenset(list_arm_serial_ports())
        added = set(now - before)
        removed = set(before - now)
        if added or removed:
            return added, removed
        time.sleep(0.2)
    return set(), set()


# def get_opencv_id_set() -> frozenset:
#     from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
#
#     found = OpenCVCamera.find_cameras()
#     return frozenset(info["id"] for info in found)
#
#
# def wait_for_single_added(since: FrozenSet, timeout_s: float = 30.0):
#     start = time.time()
#     while time.time() - start < timeout_s:
#         now = get_opencv_id_set()
#         added = set(now - since)
#         if len(added) == 1:
#             return next(iter(added))
#         if len(added) > 1:
#             raise RuntimeError(
#                 f"Multiple new camera endpoints appeared at once: {sorted(added, key=str)}. "
#                 "Reconnect only one device at a time."
#             )
#         time.sleep(0.25)
#     raise RuntimeError(
#         "Timed out waiting for the camera to reappear. Check the cable and try again."
#     )
#
#

def detect_serial_for(label: str) -> str:
    print(f"\n--- Serial: {label} ---")
    print("1) Disconnect ONLY this arm (USB) now.")
    input("   Press Enter when disconnected...")
    baseline = frozenset(list_arm_serial_ports())
    print(f"   Ports still present: {sorted(baseline) or 'none'}")
    print("2) Reconnect ONLY this arm now.")
    input("   Press Enter right after reconnecting...")

    added, _ = wait_for_serial_change(baseline)
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


# def detect_opencv_for(label: str) -> int | str:
#     print(f"\n--- Camera: {label} ---")
#     print("1) Disconnect ONLY this camera (USB) now.")
#     input("   Press Enter when disconnected...")
#     after_disconnect = get_opencv_id_set()
#     print(f"   OpenCV endpoints still present ({len(after_disconnect)}): {sorted(after_disconnect, key=str)}")
#     print("2) Reconnect ONLY this camera now.")
#     input("   Press Enter right after reconnecting...")
#
#     cam_id = wait_for_single_added(after_disconnect)
#     print(f"   Detected {label} as OpenCV id: {cam_id!r}")
#     return cam_id
#
#

def run_cmd(cmd: list[str], env: dict[str, str] | None = None) -> int:
    print(f"\n$ {' '.join(cmd)}")
    if env is not None and env.get("PYTHONPATH", "").startswith(str(REPO_SRC)):
        print(f"   (PYTHONPATH includes {REPO_SRC} so `bi_so101_*` types resolve from this repo.)")
    return subprocess.run(cmd, check=False, env=env).returncode


def calibrate_bimanual(
    left_leader: str,
    right_leader: str,
    left_follower: str,
    right_follower: str,
    robot_id: str,
    teleop_id: str,
) -> bool:
    print("\n=== Calibration (bimanual SO-101) ===")
    print("Keep all four arms powered and connected.")
    do_cal = input("Run calibration now? [Y/n]: ").strip().lower()
    if do_cal in {"n", "no"}:
        print("Skipping calibration.")
        return True

    calibrate_bin = shutil.which("lerobot-calibrate")
    py = shutil.which("python3") or shutil.which("python") or "python3"
    # ``lerobot-calibrate`` on PATH often points at a different install (e.g. PyPI) that
    # does not register ``bi_so101_*``. Prefer this repo's ``src`` with ``python -m``.
    cal_env: dict[str, str] | None = env_with_repo_src() if use_repo_src_for_cli() else None
    use_module = cal_env is not None or calibrate_bin is None
    interpreter = sys.executable if cal_env is not None else py

    def leaders_cmd() -> list[str]:
        if use_module:
            return [
                interpreter,
                "-m",
                "lerobot.calibrate",
                "--teleop.type=bi_so101_leader",
                f"--teleop.left_arm_port={left_leader}",
                f"--teleop.right_arm_port={right_leader}",
                f"--teleop.id={teleop_id}",
            ]
        return [
            calibrate_bin,  # type: ignore[list-item]
            "--teleop.type=bi_so101_leader",
            f"--teleop.left_arm_port={left_leader}",
            f"--teleop.right_arm_port={right_leader}",
            f"--teleop.id={teleop_id}",
        ]

    def followers_cmd() -> list[str]:
        if use_module:
            return [
                interpreter,
                "-m",
                "lerobot.calibrate",
                "--robot.type=bi_so101_follower",
                f"--robot.left_arm_port={left_follower}",
                f"--robot.right_arm_port={right_follower}",
                f"--robot.id={robot_id}",
            ]
        return [
            calibrate_bin,  # type: ignore[list-item]
            "--robot.type=bi_so101_follower",
            f"--robot.left_arm_port={left_follower}",
            f"--robot.right_arm_port={right_follower}",
            f"--robot.id={robot_id}",
        ]

    # Same order as single-arm helper: leaders (teleop) first, then followers (robot).
    if run_cmd(leaders_cmd(), env=cal_env) != 0:
        print("Leader (master) bimanual calibration failed.")
        return False
    if run_cmd(followers_cmd(), env=cal_env) != 0:
        print("Follower bimanual calibration failed.")
        return False
    print("Calibration finished successfully.")
    return True


# def build_cameras_json(
#     name_to_id: dict[str, int | str], width: int, height: int, fps: int
# ) -> str:
#     payload = {
#         name: {
#             "type": "opencv",
#             "index_or_path": idx,
#             "width": width,
#             "height": height,
#             "fps": fps,
#         }
#         for name, idx in name_to_id.items()
#     }
#     return json.dumps(payload, separators=(",", ":"))
#
#
# def preview_cameras(name_to_id: dict[str, int | str], seconds: float) -> None:
#     import cv2
#
#     print(f"\nOpening preview for ~{seconds:.0f}s (q or ESC to quit early)...")
#     t_end = time.time() + seconds
#     while time.time() < t_end:
#         frames: dict[str, object] = {}
#         for name, idx in name_to_id.items():
#             cap = cv2.VideoCapture(idx)
#             if not cap.isOpened():
#                 print(f"  WARN: could not open {name} ({idx!r})")
#                 continue
#             ok, frame = cap.read()
#             cap.release()
#             if ok:
#                 frames[name] = frame
#         if not frames:
#             print("No frames; abort preview.")
#             return
#         target_h = 360
#         resized = []
#         for name in sorted(frames.keys()):
#             img = frames[name]
#             h, w = img.shape[:2]
#             scale = target_h / float(h)
#             resized.append(cv2.resize(img, (int(w * scale), target_h)))
#             cv2.putText(
#                 resized[-1],
#                 name,
#                 (10, 28),
#                 cv2.FONT_HERSHEY_SIMPLEX,
#                 0.8,
#                 (0, 255, 0),
#                 2,
#             )
#         tile = cv2.hconcat(resized)
#         cv2.imshow("SO101 bimanual camera preview (q to quit)", tile)
#         key = cv2.waitKey(1) & 0xFF
#         if key in (ord("q"), 27):
#             break
#         time.sleep(0.05)
#     cv2.destroyAllWindows()
#
#

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map 4 SO-101 serial ports, optional calibration, print teleop command (no cameras)."
    )
    parser.add_argument("--skip-serial", action="store_true", help="Do not run serial unplug/replug mapping.")
    # parser.add_argument("--skip-cameras", action="store_true", help="Skip camera mapping.")
    # parser.add_argument("--num-cameras", type=int, default=3, help="How many cameras to map (default: 3).")
    # parser.add_argument(
    #     "--camera-labels",
    #     type=str,
    #     default="cam_a,cam_b,cam_c",
    #     help="Comma-separated observation keys for cameras (default: cam_a,cam_b,cam_c).",
    # )
    parser.add_argument("--skip-calibration", action="store_true", help="Skip lerobot-calibrate steps.")
    parser.add_argument("--robot-id", type=str, default="so101_bimanual_follower")
    parser.add_argument("--teleop-id", type=str, default="so101_bimanual_leader")
    # parser.add_argument("--cam-width", type=int, default=1280)
    # parser.add_argument("--cam-height", type=int, default=720)
    # parser.add_argument("--cam-fps", type=int, default=30)
    # parser.add_argument(
    #     "--preview-seconds",
    #     type=float,
    #     default=0.0,
    #     help="If >0, show a tiled OpenCV preview after mapping cameras.",
    # )
    args = parser.parse_args()

    print("SO101 bimanual mapper (serial + calibration only; cameras disabled in this script)")
    print(f"Platform: {platform.system()} — initial serial ports: {list_arm_serial_ports() or 'none'}")

    ports: dict[str, str] = {}
    if not args.skip_serial:
        try:
            ports["LEFT_LEADER"] = detect_serial_for("LEFT master (leader, left)")
            ports["RIGHT_LEADER"] = detect_serial_for("RIGHT master (leader, right)")
            ports["LEFT_FOLLOWER"] = detect_serial_for("LEFT follower")
            ports["RIGHT_FOLLOWER"] = detect_serial_for("RIGHT follower")
        except RuntimeError as err:
            print(f"\nError: {err}")
            return 1
    else:
        print("\nSkipping serial mapping (--skip-serial). Fill ports manually in the printed command.")

    # cam_labels = [x.strip() for x in args.camera_labels.split(",") if x.strip()]
    # while len(cam_labels) < args.num_cameras:
    #     cam_labels.append(f"cam_{len(cam_labels)}")
    # n_cams = args.num_cameras if cam_labels else 0
    #
    # cam_map: dict[str, int | str] = {}
    # if not args.skip_cameras and n_cams > 0:
    #     print("\n=== USB cameras (OpenCV) ===")
    #     print("Unplug/replug one camera at a time, same idea as the arms.")
    #     try:
    #         for i in range(n_cams):
    #             label = cam_labels[i]
    #             cam_map[label] = detect_opencv_for(label)
    #     except RuntimeError as err:
    #         print(f"\nError: {err}")
    #         return 1
    #
    # if args.preview_seconds > 0 and cam_map:
    #     try:
    #         preview_cameras(cam_map, args.preview_seconds)
    #     except Exception as err:
    #         print(f"Preview failed: {err}")

    print("\n=== Result ===")
    if ports:
        for k, v in ports.items():
            print(f"{k}_PORT={v}")

    if ports and not args.skip_calibration:
        if not calibrate_bimanual(
            ports["LEFT_LEADER"],
            ports["RIGHT_LEADER"],
            ports["LEFT_FOLLOWER"],
            ports["RIGHT_FOLLOWER"],
            args.robot_id,
            args.teleop_id,
        ):
            return 1
    elif not args.skip_calibration and not ports:
        print("Calibration skipped (no mapped serial ports).")

    if use_repo_src_for_cli():
        teleop_inv = f'PYTHONPATH="{REPO_SRC}" {sys.executable} -m lerobot.teleoperate'
    else:
        teleop_bin = shutil.which("lerobot-teleoperate") or "lerobot-teleoperate"
        teleop_inv = teleop_bin
    # if ports and cam_map:
    #     cam_json = build_cameras_json(cam_map, args.cam_width, args.cam_height, args.cam_fps)
    #     cmd = (
    #         f"{teleop_bin} "
    #         "--robot.type=bi_so101_follower "
    #         f"--robot.left_arm_port={ports['LEFT_FOLLOWER']} "
    #         f"--robot.right_arm_port={ports['RIGHT_FOLLOWER']} "
    #         f"--robot.id={args.robot_id} "
    #         f"--robot.cameras='{cam_json}' "
    #         "--teleop.type=bi_so101_leader "
    #         f"--teleop.left_arm_port={ports['LEFT_LEADER']} "
    #         f"--teleop.right_arm_port={ports['RIGHT_LEADER']} "
    #         f"--teleop.id={args.teleop_id} "
    #         "--display_data=true"
    #     )
    if ports:
        cmd = (
            f"{teleop_inv} "
            "--robot.type=bi_so101_follower "
            f"--robot.left_arm_port={ports['LEFT_FOLLOWER']} "
            f"--robot.right_arm_port={ports['RIGHT_FOLLOWER']} "
            f"--robot.id={args.robot_id} "
            "--teleop.type=bi_so101_leader "
            f"--teleop.left_arm_port={ports['LEFT_LEADER']} "
            f"--teleop.right_arm_port={ports['RIGHT_LEADER']} "
            f"--teleop.id={args.teleop_id} "
            "--display_data=true"
        )
    else:
        cmd = f"""{teleop_inv} \\
  --robot.type=bi_so101_follower \\
  --robot.left_arm_port=LEFT_FOLLOWER_PORT \\
  --robot.right_arm_port=RIGHT_FOLLOWER_PORT \\
  --robot.id={args.robot_id} \\
  --teleop.type=bi_so101_leader \\
  --teleop.left_arm_port=LEFT_LEADER_PORT \\
  --teleop.right_arm_port=RIGHT_LEADER_PORT \\
  --teleop.id={args.teleop_id} \\
  --display_data=true"""

    print("\nRun teleoperation:\n")
    print(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
