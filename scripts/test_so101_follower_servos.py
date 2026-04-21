#!/usr/bin/env python3
"""Quick servo diagnostics for a SO101 follower arm."""

from __future__ import annotations

import argparse
import sys
import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


def build_bus(port: str) -> FeetechMotorsBus:
    motors = {
        "shoulder_pan": Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
        "shoulder_lift": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
        "elbow_flex": Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_flex": Motor(4, "sts3215", MotorNormMode.RANGE_M100_100),
        "wrist_roll": Motor(5, "sts3215", MotorNormMode.RANGE_M100_100),
        "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
    }
    return FeetechMotorsBus(port=port, motors=motors)


def test_one_motor(bus: FeetechMotorsBus, motor_name: str, retries: int) -> tuple[bool, int | None]:
    motor = bus.motors[motor_name]
    print(f"\n- {motor_name} (id={motor.id})")
    try:
        model_number = bus.ping(motor_name, num_retry=retries, raise_on_error=True)
        pos_raw = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
        load_raw = bus.read("Present_Load", motor_name, normalize=False, num_retry=retries)
        current_raw = bus.read("Present_Current", motor_name, normalize=False, num_retry=retries)
        print(f"  OK  model={model_number} pos_raw={pos_raw} load_raw={load_raw} current_raw={current_raw}")
        return True, pos_raw
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL {type(err).__name__}: {err}")
        return False, None


def move_one_motor(bus: FeetechMotorsBus, motor_name: str, delta_raw: int, retries: int) -> bool:
    print(f"\nMove test for {motor_name}: delta_raw={delta_raw}")
    try:
        start_pos = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
        target_pos = max(0, min(4095, start_pos + delta_raw))
        print(f"  start_pos={start_pos} target_pos={target_pos}")

        bus.write("Goal_Position", motor_name, target_pos, normalize=False, num_retry=retries)
        time.sleep(0.4)
        after_pos = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
        load_raw = bus.read("Present_Load", motor_name, normalize=False, num_retry=retries)
        current_raw = bus.read("Present_Current", motor_name, normalize=False, num_retry=retries)
        print(f"  after_pos={after_pos} load_raw={load_raw} current_raw={current_raw}")

        # Return to start for safety.
        bus.write("Goal_Position", motor_name, start_pos, normalize=False, num_retry=retries)
        time.sleep(0.4)
        back_pos = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
        print(f"  returned_pos={back_pos}")
        return True
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL move test {type(err).__name__}: {err}")
        return False


def stress_test_one_motor(
    bus: FeetechMotorsBus,
    motor_name: str,
    delta_raw: int,
    cycles: int,
    settle_s: float,
    retries: int,
) -> bool:
    print(
        f"\nStress test for {motor_name}: cycles={cycles} "
        f"delta_raw={delta_raw} settle_s={settle_s}"
    )
    try:
        start_pos = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
        target_pos = max(0, min(4095, start_pos + delta_raw))
        print(f"  start_pos={start_pos} target_pos={target_pos}")

        step_failures = 0
        max_abs_load = 0
        max_current = 0

        for i in range(1, cycles + 1):
            try:
                bus.write("Goal_Position", motor_name, target_pos, normalize=False, num_retry=retries)
                time.sleep(settle_s)
                p1 = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
                load1 = bus.read("Present_Load", motor_name, normalize=False, num_retry=retries)
                current1 = bus.read("Present_Current", motor_name, normalize=False, num_retry=retries)

                bus.write("Goal_Position", motor_name, start_pos, normalize=False, num_retry=retries)
                time.sleep(settle_s)
                p2 = bus.read("Present_Position", motor_name, normalize=False, num_retry=retries)
                load2 = bus.read("Present_Load", motor_name, normalize=False, num_retry=retries)
                current2 = bus.read("Present_Current", motor_name, normalize=False, num_retry=retries)

                max_abs_load = max(max_abs_load, abs(load1), abs(load2))
                max_current = max(max_current, current1, current2)
                print(
                    f"  cycle {i:03d}/{cycles}: to={p1} back={p2} "
                    f"load_max={max(abs(load1), abs(load2))} current_max={max(current1, current2)}"
                )
            except Exception as err:  # noqa: BLE001
                step_failures += 1
                print(f"  cycle {i:03d}/{cycles}: FAIL {type(err).__name__}: {err}")

        # Ensure we leave motor near initial pose.
        try:
            bus.write("Goal_Position", motor_name, start_pos, normalize=False, num_retry=retries)
        except Exception:  # noqa: BLE001
            pass

        print(
            f"  stress summary: step_failures={step_failures}/{cycles} "
            f"max_abs_load={max_abs_load} max_current={max_current}"
        )
        return step_failures == 0
    except Exception as err:  # noqa: BLE001
        print(f"  FAIL stress setup {type(err).__name__}: {err}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Test SO101 follower servos on one serial port.")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/cu.usbmodemXXXX")
    parser.add_argument("--retries", type=int, default=2, help="Retries for each read/ping (default: 2)")
    parser.add_argument(
        "--motor",
        choices=["all", "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"],
        default="all",
        help="Test only one motor or all (default: all)",
    )
    parser.add_argument(
        "--move-delta-raw",
        type=int,
        default=0,
        help="If non-zero, move tested motor by this raw delta then return to start (safe small value: 30-80).",
    )
    parser.add_argument(
        "--stress-cycles",
        type=int,
        default=0,
        help="If >0 and --motor is a single motor, run repetitive stress cycles.",
    )
    parser.add_argument(
        "--stress-settle-s",
        type=float,
        default=0.25,
        help="Wait time after each move during stress test.",
    )
    args = parser.parse_args()

    bus = build_bus(args.port)
    print(f"Connecting to follower bus on {args.port} ...")
    bus.connect()

    failures: list[str] = []
    try:
        print("\nPer-servo test:")
        motor_names = list(bus.motors.keys()) if args.motor == "all" else [args.motor]
        for motor_name in motor_names:
            ok, _ = test_one_motor(bus, motor_name, retries=args.retries)
            if not ok:
                failures.append(motor_name)

        if args.move_delta_raw != 0:
            if args.motor == "all":
                print("\nSkipping move test because --motor=all. Choose one motor to move.")
            else:
                moved = move_one_motor(bus, args.motor, args.move_delta_raw, retries=args.retries)
                if not moved:
                    failures.append(f"move_{args.motor}")

        if args.stress_cycles > 0:
            if args.motor == "all":
                print("\nSkipping stress test because --motor=all. Choose one motor to stress.")
            else:
                delta = args.move_delta_raw if args.move_delta_raw != 0 else 40
                stressed = stress_test_one_motor(
                    bus,
                    args.motor,
                    delta_raw=delta,
                    cycles=args.stress_cycles,
                    settle_s=args.stress_settle_s,
                    retries=args.retries,
                )
                if not stressed:
                    failures.append(f"stress_{args.motor}")

        print("\nBus sync_read test (all servos):")
        try:
            pos = bus.sync_read("Present_Position", normalize=False, num_retry=args.retries)
            print(f"  OK  positions={pos}")
        except Exception as err:  # noqa: BLE001
            failures.append("sync_read_all")
            print(f"  FAIL {type(err).__name__}: {err}")
    finally:
        try:
            bus.disconnect(disable_torque=False)
        except Exception as err:  # noqa: BLE001
            print(f"\nWarning: disconnect issue: {err}")

    print("\n=== Result ===")
    if failures:
        print(f"FAILED checks: {sorted(set(failures))}")
        return 1

    print("All servo checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
