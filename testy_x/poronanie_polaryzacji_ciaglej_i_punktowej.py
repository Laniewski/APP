import sys
import csv
import time
from pathlib import Path

import numpy as np


# ============================================================
# ŚCIEŻKI
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = (
    SCRIPT_DIR
    / "dane"
    / "test_L_ciagly_vs_punktowy"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

CONTINUOUS_FILE = (
    OUTPUT_DIR
    / "ciagly_L.csv"
)

POINT_FILE = (
    OUTPUT_DIR
    / "punktowy_L.csv"
)


# ============================================================
# IMPORTY Z PROJEKTU
# ============================================================

from modules.mpc220.driver import MPC220Driver

from modules.mpc220.calibration import (
    MPC_UNITS_PER_DEGREE,
    angle_to_command,
    raw_position_to_angle,
)

from modules.mdt694b.driver import MDT694BDriver
from modules.measurement.driver import ADS1263Driver


# ============================================================
# PORTY
# ============================================================

MPC_PORT = "/dev/ttyUSB0"
MDT_PORT = "/dev/ttyACM0"


# ============================================================
# TRASA L
# ============================================================

L_START = (100.0, 100.0)
L_CORNER = (140.0, 100.0)
L_END = (140.0, 140.0)


# ============================================================
# MPC - RUCH QUASI-CIĄGŁY
# ============================================================

MPC_STEP_UNITS = 1

# 1 unit ≈ 0.11952°
# 1 unit co 0.12 s ≈ 1°/s
MPC_STEP_INTERVAL_S = 0.12

MPC_SETTLE_S = 0.8


# ============================================================
# PIEZO
# ============================================================

PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0

PIEZO_SPEED_V_S = 20.0

# komendy piezo
PIEZO_COMMAND_INTERVAL_S = 0.05

# ADS
SAMPLE_INTERVAL_S = 0.20

PIEZO_SETTLE_S = 0.5


# ============================================================
# POMIAR PUNKTOWY
# ============================================================

POINTS = [
    (100.0, 100.0),
    (110.0, 100.0),
    (120.0, 100.0),
    (130.0, 100.0),
    (140.0, 100.0),
    (140.0, 110.0),
    (140.0, 120.0),
    (140.0, 130.0),
    (140.0, 140.0),
]


# ============================================================
# FUNKCJE MPC
# ============================================================

def read_paddle_angle(mpc, paddle):
    raw = mpc.read_position_units(
        paddle
    )

    return raw_position_to_angle(
        raw
    )


def move_paddle_and_wait(
    mpc,
    paddle,
    angle,
):
    command = angle_to_command(
        angle
    )

    mpc.move_absolute_units(
        paddle,
        command,
    )

    mpc.wait_until_stopped(
        paddle
    )

    return read_paddle_angle(
        mpc,
        paddle,
    )


def move_both_and_wait(
    mpc,
    angle1,
    angle2,
):
    # wysyłamy oba ruchy praktycznie jeden po drugim
    mpc.move_absolute_units(
        1,
        angle_to_command(angle1),
    )

    mpc.move_absolute_units(
        2,
        angle_to_command(angle2),
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    actual1 = read_paddle_angle(
        mpc,
        1,
    )

    actual2 = read_paddle_angle(
        mpc,
        2,
    )

    return actual1, actual2


# ============================================================
# FUNKCJE PIEZO
# ============================================================

def fast_set_voltage(
    mdt,
    voltage,
):
    mdt._send_command(
        f"xvoltage={voltage:.3f}"
    )


def ramp_piezo(
    mdt,
    start_v,
    end_v,
):
    distance = abs(
        end_v - start_v
    )

    duration = (
        distance
        / PIEZO_SPEED_V_S
    )

    direction = (
        1.0
        if end_v >= start_v
        else -1.0
    )

    start_time = time.monotonic()

    next_command = start_time

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_time
        )

        fraction = min(
            elapsed / duration,
            1.0,
        )

        voltage = (
            start_v
            + direction
            * distance
            * fraction
        )

        if now >= next_command:

            fast_set_voltage(
                mdt,
                voltage,
            )

            next_command += (
                PIEZO_COMMAND_INTERVAL_S
            )

        if fraction >= 1.0:
            break

        time.sleep(
            0.002
        )

    fast_set_voltage(
        mdt,
        end_v,
    )


# ============================================================
# METRYKI
# ============================================================

def calculate_metrics(
    samples,
):
    if len(samples) < 5:
        return None

    in0 = np.array(
        [
            s["in0_v"]
            for s in samples
        ],
        dtype=float,
    )

    in1 = np.array(
        [
            s["in1_v"]
            for s in samples
        ],
        dtype=float,
    )

    diff = (
        in0 - in1
    )

    total = (
        in0 + in1
    )

    diff_p05 = np.percentile(
        diff,
        5,
    )

    diff_p95 = np.percentile(
        diff,
        95,
    )

    diff_amplitude = (
        diff_p95
        - diff_p05
    ) / 2.0

    in0_amplitude = (
        np.percentile(in0, 95)
        - np.percentile(in0, 5)
    ) / 2.0

    in1_amplitude = (
        np.percentile(in1, 95)
        - np.percentile(in1, 5)
    ) / 2.0

    mean_sum = float(
        np.mean(total)
    )

    valid = (
        np.abs(total) > 1e-9
    )

    normalized = np.zeros_like(
        diff
    )

    normalized[valid] = (
        diff[valid]
        / total[valid]
    )

    score = (
        np.percentile(
            normalized,
            95,
        )
        - np.percentile(
            normalized,
            5,
        )
    ) / 2.0

    return {
        "diff_amplitude_v":
            float(diff_amplitude),

        "score":
            float(score),

        "in0_amplitude_v":
            float(in0_amplitude),

        "in1_amplitude_v":
            float(in1_amplitude),

        "mean_sum_v":
            float(mean_sum),

        "samples":
            len(samples),
    }


# ============================================================
# POMIAR PUNKTOWY
# ============================================================

def measure_stationary_point(
    mdt,
    ads,
):
    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    samples = []

    duration = (
        PIEZO_MAX_V
        - PIEZO_MIN_V
    ) / PIEZO_SPEED_V_S

    start_time = time.monotonic()

    next_piezo = start_time
    next_sample = start_time

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_time
        )

        fraction = min(
            elapsed / duration,
            1.0,
        )

        voltage = (
            PIEZO_MIN_V
            + (
                PIEZO_MAX_V
                - PIEZO_MIN_V
            )
            * fraction
        )

        if now >= next_piezo:

            fast_set_voltage(
                mdt,
                voltage,
            )

            next_piezo += (
                PIEZO_COMMAND_INTERVAL_S
            )

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

            samples.append(
                {
                    "time_s": elapsed,
                    "piezo_v": voltage,
                    "in0_v": in0,
                    "in1_v": in1,
                }
            )

            next_sample += (
                SAMPLE_INTERVAL_S
            )

        if fraction >= 1.0:
            break

        time.sleep(
            0.002
        )

    fast_set_voltage(
        mdt,
        PIEZO_MAX_V,
    )

    metrics = calculate_metrics(
        samples
    )

    # powrót piezo
    ramp_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    return metrics


# ============================================================
# CIĄGŁY ODCINEK L
# ============================================================

def continuous_segment(
    mpc,
    mdt,
    ads,
    moving_paddle,
    start_angle,
    end_angle,
    fixed_angle,
    segment_name,
    cycle_id_start,
):
    results = []

    # --------------------------------------------------------
    # ustawienie początku segmentu
    # --------------------------------------------------------

    if moving_paddle == 1:

        move_both_and_wait(
            mpc,
            start_angle,
            fixed_angle,
        )

    else:

        move_both_and_wait(
            mpc,
            fixed_angle,
            start_angle,
        )

    time.sleep(
        MPC_SETTLE_S
    )

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    # --------------------------------------------------------
    # MPC
    # --------------------------------------------------------

    start_command = angle_to_command(
        start_angle
    )

    end_command = angle_to_command(
        end_angle
    )

    direction = (
        1
        if end_command >= start_command
        else -1
    )

    current_command = (
        start_command
    )

    last_command = (
        start_command
    )

    # --------------------------------------------------------
    # PIEZO
    # --------------------------------------------------------

    piezo_direction = 1

    piezo_leg_start_v = (
        PIEZO_MIN_V
    )

    piezo_leg_end_v = (
        PIEZO_MAX_V
    )

    piezo_leg_start_time = (
        time.monotonic()
    )

    piezo_leg_duration = (
        abs(
            piezo_leg_end_v
            - piezo_leg_start_v
        )
        / PIEZO_SPEED_V_S
    )

    cycle_samples = []

    cycle_id = (
        cycle_id_start
    )

    cycle_start_angle_1 = None
    cycle_start_angle_2 = None

    global_start = (
        time.monotonic()
    )

    next_mpc_command = (
        global_start
    )

    next_piezo_command = (
        global_start
    )

    next_sample = (
        global_start
    )

    finished_mpc = False

    print()
    print(
        f"Segment {segment_name}"
    )

    # --------------------------------------------------------
    # PĘTLA GŁÓWNA
    # --------------------------------------------------------

    while True:

        now = time.monotonic()

        # ====================================================
        # MPC
        # ====================================================

        if (
            not finished_mpc
            and
            now >= next_mpc_command
        ):

            mpc.move_absolute_units(
                moving_paddle,
                current_command,
            )

            last_command = (
                current_command
            )

            if current_command == end_command:

                finished_mpc = True

            else:

                current_command += (
                    direction
                    * MPC_STEP_UNITS
                )

                if direction > 0:

                    current_command = min(
                        current_command,
                        end_command,
                    )

                else:

                    current_command = max(
                        current_command,
                        end_command,
                    )

            next_mpc_command += (
                MPC_STEP_INTERVAL_S
            )

        # ====================================================
        # PIEZO
        # ====================================================

        piezo_elapsed = (
            now
            - piezo_leg_start_time
        )

        fraction = min(
            piezo_elapsed
            / piezo_leg_duration,
            1.0,
        )

        piezo_voltage = (
            piezo_leg_start_v
            + (
                piezo_leg_end_v
                - piezo_leg_start_v
            )
            * fraction
        )

        if now >= next_piezo_command:

            fast_set_voltage(
                mdt,
                piezo_voltage,
            )

            next_piezo_command += (
                PIEZO_COMMAND_INTERVAL_S
            )

        # ====================================================
        # ADS
        # ====================================================

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

            angle1 = (
                read_paddle_angle(
                    mpc,
                    1,
                )
            )

            angle2 = (
                read_paddle_angle(
                    mpc,
                    2,
                )
            )

            if (
                cycle_start_angle_1
                is None
            ):
                cycle_start_angle_1 = (
                    angle1
                )

                cycle_start_angle_2 = (
                    angle2
                )

            cycle_samples.append(
                {
                    "time_s":
                        now
                        - global_start,

                    "piezo_v":
                        piezo_voltage,

                    "in0_v":
                        in0,

                    "in1_v":
                        in1,

                    "angle1_deg":
                        angle1,

                    "angle2_deg":
                        angle2,
                }
            )

            next_sample += (
                SAMPLE_INTERVAL_S
            )

        # ====================================================
        # KONIEC POŁOWY RAMPY PIEZO
        # ====================================================

        if fraction >= 1.0:

            fast_set_voltage(
                mdt,
                piezo_leg_end_v,
            )

            # przejście 150 -> 80
            if piezo_direction == 1:

                piezo_direction = -1

                piezo_leg_start_v = (
                    PIEZO_MAX_V
                )

                piezo_leg_end_v = (
                    PIEZO_MIN_V
                )

                piezo_leg_start_time = (
                    now
                )

            # zakończenie pełnego cyklu 80->150->80
            else:

                metrics = (
                    calculate_metrics(
                        cycle_samples
                    )
                )

                if (
                    metrics is not None
                    and
                    len(cycle_samples) > 0
                ):

                    p1_values = [
                        s["angle1_deg"]
                        for s
                        in cycle_samples
                    ]

                    p2_values = [
                        s["angle2_deg"]
                        for s
                        in cycle_samples
                    ]

                    result = {
                        "cycle_id":
                            cycle_id,

                        "segment":
                            segment_name,

                        "p1_start_deg":
                            min(p1_values),

                        "p1_end_deg":
                            max(p1_values),

                        "p1_mean_deg":
                            float(
                                np.mean(
                                    p1_values
                                )
                            ),

                        "p2_start_deg":
                            min(p2_values),

                        "p2_end_deg":
                            max(p2_values),

                        "p2_mean_deg":
                            float(
                                np.mean(
                                    p2_values
                                )
                            ),

                        **metrics,
                    }

                    results.append(
                        result
                    )

                    print(
                        f"cykl {cycle_id:02d} | "
                        f"P1={result['p1_mean_deg']:.2f}° | "
                        f"P2={result['p2_mean_deg']:.2f}° | "
                        f"A_D={result['diff_amplitude_v']:.4f} V"
                    )

                    cycle_id += 1

                cycle_samples = []

                cycle_start_angle_1 = None
                cycle_start_angle_2 = None

                piezo_direction = 1

                piezo_leg_start_v = (
                    PIEZO_MIN_V
                )

                piezo_leg_end_v = (
                    PIEZO_MAX_V
                )

                piezo_leg_start_time = (
                    now
                )

            piezo_leg_duration = (
                abs(
                    piezo_leg_end_v
                    - piezo_leg_start_v
                )
                / PIEZO_SPEED_V_S
            )

        # ====================================================
        # KONIEC SEGMENTU
        # ====================================================

        if finished_mpc:

            actual = (
                read_paddle_angle(
                    mpc,
                    moving_paddle,
                )
            )

            if (
                abs(
                    actual
                    - end_angle
                )
                < 0.2
            ):
                break

        time.sleep(
            0.001
        )

    mpc.wait_until_stopped(
        moving_paddle
    )

    return (
        results,
        cycle_id,
    )


# ============================================================
# TEST CIĄGŁY L
# ============================================================

def run_continuous_L(
    mpc,
    mdt,
    ads,
):
    print()
    print("=" * 80)
    print("TEST 1: CIĄGŁY PRZEJAZD PO L")
    print("=" * 80)

    results = []

    cycle_id = 1

    # --------------------------------------------------------
    # ODCINEK 1:
    # (100,100) -> (140,100)
    # --------------------------------------------------------

    segment_results, cycle_id = (
        continuous_segment(
            mpc=mpc,
            mdt=mdt,
            ads=ads,
            moving_paddle=1,
            start_angle=100.0,
            end_angle=140.0,
            fixed_angle=100.0,
            segment_name="P1_100_140_P2_100",
            cycle_id_start=cycle_id,
        )
    )

    results.extend(
        segment_results
    )

    # --------------------------------------------------------
    # ODCINEK 2:
    # (140,100) -> (140,140)
    # --------------------------------------------------------

    segment_results, cycle_id = (
        continuous_segment(
            mpc=mpc,
            mdt=mdt,
            ads=ads,
            moving_paddle=2,
            start_angle=100.0,
            end_angle=140.0,
            fixed_angle=140.0,
            segment_name="P1_140_P2_100_140",
            cycle_id_start=cycle_id,
        )
    )

    results.extend(
        segment_results
    )

    return results


# ============================================================
# TEST PUNKTOWY
# ============================================================

def run_point_test(
    mpc,
    mdt,
    ads,
):
    print()
    print("=" * 80)
    print("TEST 2: PUNKTOWY POMIAR TEJ SAMEJ TRASY")
    print("=" * 80)

    results = []

    for index, (
        angle1,
        angle2,
    ) in enumerate(
        POINTS,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(POINTS)}] "
            f"P1={angle1:.1f}° "
            f"P2={angle2:.1f}°"
        )

        actual1, actual2 = (
            move_both_and_wait(
                mpc,
                angle1,
                angle2,
            )
        )

        time.sleep(
            MPC_SETTLE_S
        )

        metrics = (
            measure_stationary_point(
                mdt,
                ads,
            )
        )

        if metrics is None:
            continue

        row = {
            "point_id":
                index,

            "p1_deg":
                actual1,

            "p2_deg":
                actual2,

            **metrics,
        }

        results.append(
            row
        )

        print(
            f"A_D = "
            f"{metrics['diff_amplitude_v']:.4f} V"
        )

    return results


# ============================================================
# CSV
# ============================================================

def save_continuous_csv(
    results,
):
    fields = [
        "cycle_id",
        "segment",

        "p1_start_deg",
        "p1_end_deg",
        "p1_mean_deg",

        "p2_start_deg",
        "p2_end_deg",
        "p2_mean_deg",

        "diff_amplitude_v",
        "score",

        "in0_amplitude_v",
        "in1_amplitude_v",

        "mean_sum_v",
        "samples",
    ]

    with open(
        CONTINUOUS_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        writer.writerows(
            results
        )


def save_point_csv(
    results,
):
    fields = [
        "point_id",

        "p1_deg",
        "p2_deg",

        "diff_amplitude_v",
        "score",

        "in0_amplitude_v",
        "in1_amplitude_v",

        "mean_sum_v",
        "samples",
    ]

    with open(
        POINT_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        writer.writerows(
            results
        )


# ============================================================
# MAIN
# ============================================================

def main():

    mpc = None
    mdt = None
    ads = None

    try:

        print()
        print("=" * 80)
        print("L: CIĄGŁY VS PUNKTOWY POMIAR POLARYZACJI")
        print("=" * 80)

        print()
        print(
            "Trasa:"
        )

        print(
            "(100°,100°)"
            " -> "
            "(140°,100°)"
            " -> "
            "(140°,140°)"
        )

        print()
        print(
            f"Wyniki:"
        )

        print(
            CONTINUOUS_FILE
        )

        print(
            POINT_FILE
        )

        # ====================================================
        # MPC
        # ====================================================

        print()
        print(
            "Łączenie MPC220..."
        )

        mpc = MPC220Driver(
            MPC_PORT
        )

        mpc.connect()

        print(
            "MPC220 OK"
        )

        # ====================================================
        # MDT
        # ====================================================

        print(
            "Łączenie MDT694B..."
        )

        mdt = MDT694BDriver(
            port=MDT_PORT
        )

        mdt.connect()

        print(
            "MDT694B OK"
        )

        # ====================================================
        # ADS
        # ====================================================

        print(
            "Łączenie ADS1263..."
        )

        ads = ADS1263Driver()

        ads.connect()

        ads.start_measurement()

        print(
            "ADS1263 OK"
        )

        # ====================================================
        # WARUNKI POCZĄTKOWE
        # ====================================================

        fast_set_voltage(
            mdt,
            PIEZO_MIN_V,
        )

        move_both_and_wait(
            mpc,
            100.0,
            100.0,
        )

        time.sleep(
            1.0
        )

        # ====================================================
        # CIĄGŁY
        # ====================================================

        continuous_results = (
            run_continuous_L(
                mpc,
                mdt,
                ads,
            )
        )

        save_continuous_csv(
            continuous_results
        )

        print()
        print(
            f"Zapisano: "
            f"{CONTINUOUS_FILE}"
        )

        # ====================================================
        # RESET
        # ====================================================

        print()
        print(
            "Reset przed pomiarem punktowym..."
        )

        fast_set_voltage(
            mdt,
            PIEZO_MIN_V,
        )

        move_both_and_wait(
            mpc,
            100.0,
            100.0,
        )

        time.sleep(
            1.0
        )

        # ====================================================
        # PUNKTOWY
        # ====================================================

        point_results = (
            run_point_test(
                mpc,
                mdt,
                ads,
            )
        )

        save_point_csv(
            point_results
        )

        print()
        print(
            f"Zapisano: "
            f"{POINT_FILE}"
        )

        # ====================================================
        # KONIEC
        # ====================================================

        print()
        print("=" * 80)
        print("TEST ZAKOŃCZONY")
        print("=" * 80)

        print(
            f"Ciągłych cykli: "
            f"{len(continuous_results)}"
        )

        print(
            f"Punktów referencyjnych: "
            f"{len(point_results)}"
        )

    finally:

        if ads is not None:

            try:
                ads.stop_measurement()
            except Exception:
                pass

        if mdt is not None:

            try:
                fast_set_voltage(
                    mdt,
                    PIEZO_MIN_V,
                )
            except Exception:
                pass

            try:
                mdt.close()
            except Exception:
                try:
                    mdt.disconnect()
                except Exception:
                    pass

        if mpc is not None:

            try:
                mpc.close()
            except Exception:
                try:
                    mpc.disconnect()
                except Exception:
                    pass


if __name__ == "__main__":
    main()