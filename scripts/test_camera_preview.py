#!/usr/bin/env python3
"""
Minimal camera test: list devices or show a live preview using LeRobot camera backends.

Usage:
  # List OpenCV + RealSense cameras
  python scripts/test_camera_preview.py --list

  # Live preview, OpenCV device index 0 (default)
  python scripts/test_camera_preview.py --opencv 0

  # Several cameras at once — separate windows, q to quit
  python scripts/test_camera_preview.py --opencv 0 1 2
  python scripts/test_camera_preview.py --all-opencv

  # Laptop: built-in webcam is often index 0; three USB cameras often 1,2,3
  python scripts/test_camera_preview.py --opencv 0 1 2 3
  # Same three USB only (skip built-in): --no-webcam omits index 0
  python scripts/test_camera_preview.py --all-opencv --no-webcam
  python scripts/test_camera_preview.py --opencv 0 1 2 3 --no-webcam

  # Live preview, RealSense by serial (use lerobot-find-cameras realsense to see IDs)
  python scripts/test_camera_preview.py --realsense YOUR_SERIAL

  # One frame only (no GUI), useful over SSH
  python scripts/test_camera_preview.py --opencv 0 --no-preview

  # If several USB cameras fail in one process, one Python process per device (distinct indices)
  python scripts/test_camera_preview.py --opencv 1 2 3 --separate-processes
  python scripts/test_camera_preview.py --all-opencv --separate-processes
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Allow running from repo root without install
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import cv2
import numpy as np

from lerobot.cameras.configs import ColorMode
from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig


def _list_cameras() -> None:
    from lerobot.find_cameras import find_and_print_cameras

    find_and_print_cameras(camera_type_filter=None)


def _rgb_to_bgr_for_display(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        return frame
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def _parse_opencv_index_or_path(value: int | str | Path) -> int | Path:
    if isinstance(value, int):
        return value
    if isinstance(value, Path):
        return value
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    return Path(s)


def _read_retry(cam: OpenCVCamera, *, attempts: int = 50, delay_s: float = 0.05) -> np.ndarray:
    """USB multi-cam: first frames often fail until the device settles; retry briefly."""
    last: RuntimeError | None = None
    for _ in range(attempts):
        try:
            return cam.read()
        except RuntimeError as e:
            last = e
            time.sleep(delay_s)
    assert last is not None
    raise last


def _dedupe_camera_ids(sources: list[int | str | Path]) -> list[int | str | Path]:
    """Same physical device only once (stable key: parsed index or path)."""
    seen: set[int | Path] = set()
    out: list[int | str | Path] = []
    for s in sources:
        k = _parse_opencv_index_or_path(s)
        if k in seen:
            print(f"Aviso: se omite id duplicado (misma cámara): {s!r}", file=sys.stderr)
            continue
        seen.add(k)
        out.append(s)
    return out


def _apply_exclude(sources: list[int | str | Path], exclude: list[int | str | Path] | None) -> list[int | str | Path]:
    if not exclude:
        return list(sources)
    excluded = {_parse_opencv_index_or_path(x) for x in exclude}
    out: list[int | str | Path] = []
    for s in sources:
        if _parse_opencv_index_or_path(s) not in excluded:
            out.append(s)
    return out


def _run_opencv_many(sources: list[int | str | Path], no_preview: bool) -> None:
    if not sources:
        return
    indices: list[int | Path] = [_parse_opencv_index_or_path(s) for s in sources]
    multi = len(indices) > 1
    cams: list[OpenCVCamera] = []
    for i, idx in enumerate(indices):
        config = OpenCVCameraConfig(index_or_path=idx, color_mode=ColorMode.RGB)
        cam = OpenCVCamera(config)
        # Never use connect(warmup=True) here: LeRobot's warmup calls read() in a loop and many USB
        # devices fail (especially the 3rd cam, or any single-cam subprocess from --separate-processes).
        # We warm up with _read_retry in _grab instead.
        cam.connect(warmup=False)
        cams.append(cam)
        if multi and i + 1 < len(indices):
            time.sleep(0.5)

    def _label(i: int, idx: int | Path) -> str:
        return f"LeRobot OpenCV [{i}] {idx} — q to quit"

    def _grab(cam: OpenCVCamera) -> np.ndarray:
        return _read_retry(cam)

    try:
        for i, (idx, cam) in enumerate(zip(indices, cams, strict=True)):
            frame = _grab(cam)
            print(f"Camera {i} ({idx}): shape {frame.shape}, dtype {frame.dtype}")
        if no_preview:
            return
        for i, idx in enumerate(indices):
            cv2.namedWindow(_label(i, idx), cv2.WINDOW_NORMAL)
        while True:
            for i, (idx, cam) in enumerate(zip(indices, cams, strict=True)):
                frame = _grab(cam)
                cv2.imshow(_label(i, idx), _rgb_to_bgr_for_display(frame))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        for cam in cams:
            if cam.is_connected:
                cam.disconnect()
        cv2.destroyAllWindows()


def _run_opencv_separate_processes(ids: list[int | str | Path], no_preview: bool) -> None:
    """Un proceso por cámara: cada uno solo abre un VideoCapture (mejor con varias USB)."""
    script = Path(__file__).resolve()
    procs: list[subprocess.Popen[bytes]] = []
    popen_kw: dict = {}
    if sys.platform != "win32":
        popen_kw["start_new_session"] = True
    n = len(ids)
    for i, raw in enumerate(ids):
        cmd = [sys.executable, str(script), "--opencv", str(raw)]
        if no_preview:
            cmd.append("--no-preview")
        print(f"Proceso {i + 1}/{n}: cámara {raw!r}")
        procs.append(subprocess.Popen(cmd, **popen_kw))
        if i + 1 < n:
            time.sleep(0.35)
    print(
        "Cada proceso tiene su propia ventana (q para cerrar). "
        "Este script espera a que terminen todos los procesos.",
        file=sys.stderr,
    )
    try:
        for pr in procs:
            pr.wait()
    except KeyboardInterrupt:
        for pr in procs:
            if pr.poll() is None:
                pr.terminate()
        raise


def _run_realsense(serial_or_name: str, no_preview: bool) -> None:
    from lerobot.cameras.realsense.camera_realsense import RealSenseCamera
    from lerobot.cameras.realsense.configuration_realsense import RealSenseCameraConfig

    config = RealSenseCameraConfig(serial_number_or_name=serial_or_name, color_mode=ColorMode.RGB)
    cam = RealSenseCamera(config)
    cam.connect(warmup=True)
    try:
        frame = cam.read()
        print(f"Frame shape: {frame.shape}, dtype: {frame.dtype}")
        if no_preview:
            return
        win = "LeRobot camera test (RealSense) — q to quit"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        while True:
            frame = cam.read()
            cv2.imshow(win, _rgb_to_bgr_for_display(frame))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        if cam.is_connected:
            cam.disconnect()
        cv2.destroyAllWindows()


def main() -> None:
    p = argparse.ArgumentParser(description="Test LeRobot cameras with a live preview or one frame.")
    p.add_argument("--list", action="store_true", help="Print detected OpenCV and RealSense cameras and exit.")
    p.add_argument(
        "--opencv",
        nargs="+",
        default=None,
        metavar="INDEX_OR_PATH",
        help="One or more OpenCV cameras: indices or paths (e.g. --opencv 0 1 2).",
    )
    p.add_argument(
        "--all-opencv",
        action="store_true",
        help="Detect and open every OpenCV camera found (good for several USB webcams).",
    )
    p.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        metavar="INDEX_OR_PATH",
        help="Skip these devices (e.g. 0 = built-in webcam on many laptops). Use with --opencv or --all-opencv.",
    )
    p.add_argument(
        "--no-webcam",
        action="store_true",
        help="Shortcut: exclude index 0 (typical laptop built-in). Combine with --opencv … or --all-opencv.",
    )
    p.add_argument("--realsense", default=None, metavar="SERIAL_OR_NAME", help="RealSense serial number or unique name.")
    p.add_argument(
        "--no-preview",
        action="store_true",
        help="Grab one frame and print shape only (no OpenCV window).",
    )
    p.add_argument(
        "--separate-processes",
        action="store_true",
        help="Open each OpenCV device in a separate process (one camera per process; helps flaky multi-USB).",
    )
    args = p.parse_args()

    if args.list:
        _list_cameras()
        return

    exclude_extra: list[int | str | Path] = list(args.exclude) if args.exclude else []
    if args.no_webcam:
        exclude_extra.append(0)

    if args.exclude and args.opencv is None and not args.all_opencv:
        p.error("--exclude needs --opencv … or --all-opencv.")
    if args.no_webcam and args.opencv is None and not args.all_opencv:
        p.error("--no-webcam needs --opencv … or --all-opencv (nothing to skip otherwise).")

    if args.realsense and (args.opencv is not None or args.all_opencv):
        p.error("Use either --opencv / --all-opencv or --realsense, not both.")
    if args.all_opencv and args.opencv is not None:
        p.error("Use either --all-opencv or explicit --opencv indices, not both.")
    if args.separate_processes and args.realsense:
        p.error("--separate-processes applies to OpenCV only.")
    if args.realsense:
        _run_realsense(args.realsense, args.no_preview)
    elif args.all_opencv:
        found = OpenCVCamera.find_cameras()
        if not found:
            print("No OpenCV cameras detected. Try --list or set indices manually with --opencv.")
            return
        ids = [m["id"] for m in found]
        ids = _apply_exclude(ids, exclude_extra if exclude_extra else None)
        ids = _dedupe_camera_ids(ids)
        if not ids:
            print("After --exclude / --no-webcam, no cameras left. Try --list to see indices.")
            return
        print(f"Opening {len(ids)} OpenCV camera(s): {ids}")
        if args.separate_processes:
            _run_opencv_separate_processes(ids, args.no_preview)
        else:
            _run_opencv_many(ids, args.no_preview)
    elif args.opencv is not None:
        ids = _apply_exclude(args.opencv, exclude_extra if exclude_extra else None)
        ids = _dedupe_camera_ids(ids)
        if not ids:
            print("After --exclude / --no-webcam, no cameras left.")
            return
        if args.separate_processes:
            _run_opencv_separate_processes(ids, args.no_preview)
        else:
            _run_opencv_many(ids, args.no_preview)
    else:
        if args.separate_processes:
            _run_opencv_separate_processes([0], args.no_preview)
        else:
            _run_opencv_many([0], args.no_preview)


if __name__ == "__main__":
    main()
