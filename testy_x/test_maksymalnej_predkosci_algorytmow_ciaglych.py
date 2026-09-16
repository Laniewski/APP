import sys
import csv
import time
import math
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
    / "test_maksymalnej_predkosci_mpc_L"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# IMPORTY
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

# Referencja co 5°
REFERENCE_STEP_DEG = 5.0


# ============================================================
# PRĘDKOŚCI MPC
# ============================================================

MPC_SPEEDS_DEG_S = [
    0.5,
    1.0,
    1.5,
    2.0,
    3.0,
    4.0,
    5.0,
]

MPC_COMMAND_INTERVAL_S = 0.12
MPC_SETTLE_S = 0.8


# ============================================================
# PIEZO
# ============================================================

PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0

PIEZO_SPEED_V_S = 20.0

PIEZO_COMMAND_INTERVAL_S = 0.05
PIEZO_SETTLE_S = 0.5

HALF_CYCLE_TIME_S = (
    PIEZO_MAX_V - PIEZO_MIN_V
) / PIEZO_SPEED_V_S


# ============================================================
# ADS
# ============================================================

SAMPLE_INTERVAL_S = 0.20

DISCARD_SAMPLES = 4


# ============================================================
# KRYTERIA JAKOŚCI
# ============================================================

MAX_MEAN_ERROR_PCT = 5.0
MIN_CORRELATION = 0.98


# ============================================================
# FUNKCJE MPC
# ============================================================

def read_paddle_angle(mpc, paddle):

    raw = mpc.read_position_units(paddle)

    return raw_position_to_angle(raw)


def move_both_and_wait(
    mpc,
    p1,
    p2,
):

    mpc.move_absolute_units(
        1,
        angle_to_command(p1),
    )

    mpc.move_absolute_units(
        2,
        angle_to_command(p2),
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    time.sleep(MPC_SETTLE_S)

    return (
        read_paddle_angle(mpc, 1),
        read_paddle_angle(mpc, 2),
    )


# ============================================================
# MDT
# ============================================================

def fast_set_voltage(mdt, voltage):

    mdt._send_command(
        f"xvoltage={voltage:.3f}"
    )


def ramp_piezo(
    mdt,
    start_v,
    end_v,
    speed_v_s,
):

    duration = abs(
        end_v - start_v
    ) / speed_v_s

    start_t = time.monotonic()

    while True:

        elapsed = (
            time.monotonic()
            - start_t
        )

        progress = min(
            elapsed / duration,
            1.0,
        )

        voltage = (
            start_v
            +
            (end_v - start_v)
            * progress
        )

        fast_set_voltage(
            mdt,
            voltage,
        )

        if progress >= 1.0:
            break

        time.sleep(
            PIEZO_COMMAND_INTERVAL_S
        )


def condition_piezo(mdt):

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    ramp_piezo(
        mdt,
        PIEZO_MIN_V,
        PIEZO_MAX_V,
        PIEZO_SPEED_V_S,
    )

    time.sleep(0.2)

    ramp_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_SPEED_V_S,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )


# ============================================================
# ADS
# ============================================================

def connect_ads():

    ads = ADS1263Driver()

    if hasattr(
        ads,
        "connect",
    ):
        ads.connect()

    ads.start_measurement()

    return ads


def discard_ads_samples(
    ads,
    count=DISCARD_SAMPLES,
):

    for _ in range(count):

        ads.read_sample()

        time.sleep(
            SAMPLE_INTERVAL_S
        )


def close_ads(ads):

    if ads is None:
        return

    try:
        ads.stop_measurement()
    except Exception:
        pass

    if hasattr(
        ads,
        "disconnect",
    ):

        try:
            ads.disconnect()
        except Exception:
            pass

    elif hasattr(
        ads,
        "close",
    ):

        try:
            ads.close()
        except Exception:
            pass


# ============================================================
# METRYKA POLARYZACJI
# ============================================================

def calculate_metrics(samples):

    if len(samples) < 5:

        return {
            "diff_amplitude_v": float("nan"),
            "score": float("nan"),
            "samples": len(samples),
        }

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

    diff = in0 - in1

    amplitude = (
        np.percentile(diff, 95)
        -
        np.percentile(diff, 5)
    ) / 2.0

    total = in0 + in1

    valid = (
        np.abs(total)
        > 1e-9
    )

    norm = (
        diff[valid]
        /
        total[valid]
    )

    if len(norm) >= 5:

        score = (
            np.percentile(norm, 95)
            -
            np.percentile(norm, 5)
        ) / 2.0

    else:

        score = float("nan")

    return {
        "diff_amplitude_v":
            float(amplitude),

        "score":
            float(score),

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

    duration = HALF_CYCLE_TIME_S

    start_t = time.monotonic()
    next_piezo = start_t
    next_sample = start_t

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_t
        )

        progress = min(
            elapsed / duration,
            1.0,
        )

        if now >= next_piezo:

            voltage = (
                PIEZO_MIN_V
                +
                (
                    PIEZO_MAX_V
                    - PIEZO_MIN_V
                )
                * progress
            )

            fast_set_voltage(
                mdt,
                voltage,
            )

            next_piezo = (
                now
                +
                PIEZO_COMMAND_INTERVAL_S
            )

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

            samples.append(
                {
                    "in0_v":
                        float(in0),

                    "in1_v":
                        float(in1),
                }
            )

            next_sample = (
                now
                +
                SAMPLE_INTERVAL_S
            )

        if progress >= 1.0:
            break

        time.sleep(0.001)

    # powrót bez pomiaru
    ramp_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_SPEED_V_S,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    return calculate_metrics(
        samples
    )


# ============================================================
# REFERENCJA L
# ============================================================

def build_reference_points():

    points = []

    values = np.arange(
        100.0,
        140.0 + 0.01,
        REFERENCE_STEP_DEG,
    )

    # pierwsze ramię
    for p1 in values:

        points.append(
            (
                float(p1),
                100.0,
            )
        )

    # drugie ramię
    # pomijamy narożnik,
    # bo już jest na końcu ramienia 1
    for p2 in values[1:]:

        points.append(
            (
                140.0,
                float(p2),
            )
        )

    return points


def path_coordinate(
    p1,
    p2,
):

    # ramię 1
    if p1 < 139.0:

        return (
            p1 - 100.0
        )

    # ramię 2
    return (
        40.0
        +
        (p2 - 100.0)
    )


def run_point_reference(
    mpc,
    mdt,
    ads,
):

    print()
    print("=" * 80)
    print("REFERENCJA PUNKTOWA")
    print("=" * 80)

    rows = []

    points = (
        build_reference_points()
    )

    for i, (p1, p2) in enumerate(
        points,
        start=1,
    ):

        actual1, actual2 = (
            move_both_and_wait(
                mpc,
                p1,
                p2,
            )
        )

        metrics = (
            measure_stationary_point(
                mdt,
                ads,
            )
        )

        s = path_coordinate(
            actual1,
            actual2,
        )

        row = {
            "point_id": i,

            "p1_deg":
                actual1,

            "p2_deg":
                actual2,

            "s_deg":
                s,

            "diff_amplitude_v":
                metrics[
                    "diff_amplitude_v"
                ],

            "score":
                metrics["score"],

            "samples":
                metrics["samples"],
        }

        rows.append(row)

        print(
            f"[{i:02d}/{len(points)}] "
            f"P1={actual1:7.3f}° "
            f"P2={actual2:7.3f}° "
            f"A_D={metrics['diff_amplitude_v']:.5f} V"
        )

    save_csv(
        OUTPUT_DIR
        / "reference_pointwise.csv",
        rows,
    )

    return rows


# ============================================================
# CIĄGŁY PÓŁCYKL
# ============================================================

def run_continuous_window(
    mpc,
    mdt,
    ads,
    speed_deg_s,
    segment,
    direction_up,
):

    samples = []

    start_t = time.monotonic()

    next_mpc = start_t
    next_piezo = start_t
    next_sample = start_t

    duration = HALF_CYCLE_TIME_S

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_t
        )

        progress = min(
            elapsed / duration,
            1.0,
        )

        # --------------------------------------------
        # MPC
        # --------------------------------------------

        if now >= next_mpc:

            if segment == 1:

                actual_p1 = (
                    read_paddle_angle(
                        mpc,
                        1,
                    )
                )

                target_p1 = min(
                    actual_p1
                    +
                    speed_deg_s
                    *
                    MPC_COMMAND_INTERVAL_S,
                    140.0,
                )

                mpc.move_absolute_units(
                    1,
                    angle_to_command(
                        target_p1
                    ),
                )

            else:

                actual_p2 = (
                    read_paddle_angle(
                        mpc,
                        2,
                    )
                )

                target_p2 = min(
                    actual_p2
                    +
                    speed_deg_s
                    *
                    MPC_COMMAND_INTERVAL_S,
                    140.0,
                )

                mpc.move_absolute_units(
                    2,
                    angle_to_command(
                        target_p2
                    ),
                )

            next_mpc = (
                now
                +
                MPC_COMMAND_INTERVAL_S
            )

        # --------------------------------------------
        # PIEZO
        # --------------------------------------------

        if now >= next_piezo:

            if direction_up:

                voltage = (
                    PIEZO_MIN_V
                    +
                    (
                        PIEZO_MAX_V
                        - PIEZO_MIN_V
                    )
                    * progress
                )

            else:

                voltage = (
                    PIEZO_MAX_V
                    -
                    (
                        PIEZO_MAX_V
                        - PIEZO_MIN_V
                    )
                    * progress
                )

            fast_set_voltage(
                mdt,
                voltage,
            )

            next_piezo = (
                now
                +
                PIEZO_COMMAND_INTERVAL_S
            )

        # --------------------------------------------
        # ADS
        # --------------------------------------------

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

            p1_actual = (
                read_paddle_angle(
                    mpc,
                    1,
                )
            )

            p2_actual = (
                read_paddle_angle(
                    mpc,
                    2,
                )
            )

            samples.append(
                {
                    "time_s":
                        elapsed,

                    "p1_deg":
                        p1_actual,

                    "p2_deg":
                        p2_actual,

                    "in0_v":
                        float(in0),

                    "in1_v":
                        float(in1),
                }
            )

            next_sample = (
                now
                +
                SAMPLE_INTERVAL_S
            )

        if progress >= 1.0:
            break

        time.sleep(0.001)

    if direction_up:

        fast_set_voltage(
            mdt,
            PIEZO_MAX_V,
        )

    else:

        fast_set_voltage(
            mdt,
            PIEZO_MIN_V,
        )

    metrics = (
        calculate_metrics(
            samples
        )
    )

    if samples:

        p1_values = np.array(
            [
                s["p1_deg"]
                for s in samples
            ]
        )

        p2_values = np.array(
            [
                s["p2_deg"]
                for s in samples
            ]
        )

        p1_mean = float(
            np.mean(p1_values)
        )

        p2_mean = float(
            np.mean(p2_values)
        )

    else:

        p1_mean = float("nan")
        p2_mean = float("nan")

    return {
        "p1_mean_deg":
            p1_mean,

        "p2_mean_deg":
            p2_mean,

        "diff_amplitude_v":
            metrics[
                "diff_amplitude_v"
            ],

        "score":
            metrics["score"],

        "samples":
            metrics["samples"],
    }


# ============================================================
# CIĄGŁY PRZEJAZD L
# ============================================================

def run_continuous_L(
    mpc,
    mdt,
    ads,
    speed_deg_s,
):

    print()
    print("=" * 80)
    print(
        f"CIĄGŁY TEST L — "
        f"{speed_deg_s:.2f}°/s"
    )
    print("=" * 80)

    move_both_and_wait(
        mpc,
        *L_START,
    )

    condition_piezo(mdt)
    discard_ads_samples(ads)

    rows = []

    direction_up = True
    window_id = 0

    # ========================================================
    # RAMIĘ 1
    # ========================================================

    while True:

        p1 = read_paddle_angle(
            mpc,
            1,
        )

        if p1 >= 139.8:
            break

        window_id += 1

        result = (
            run_continuous_window(
                mpc,
                mdt,
                ads,
                speed_deg_s,
                segment=1,
                direction_up=direction_up,
            )
        )

        direction_up = (
            not direction_up
        )

        s = path_coordinate(
            result[
                "p1_mean_deg"
            ],
            result[
                "p2_mean_deg"
            ],
        )

        row = {
            "window_id":
                window_id,

            "speed_deg_s":
                speed_deg_s,

            "segment":
                1,

            "p1_mean_deg":
                result[
                    "p1_mean_deg"
                ],

            "p2_mean_deg":
                result[
                    "p2_mean_deg"
                ],

            "s_deg":
                s,

            "diff_amplitude_v":
                result[
                    "diff_amplitude_v"
                ],

            "score":
                result[
                    "score"
                ],

            "samples":
                result[
                    "samples"
                ],
        }

        rows.append(row)

        print(
            f"W{window_id:02d} "
            f"s={s:6.2f}° "
            f"A_D="
            f"{result['diff_amplitude_v']:.5f} V"
        )

    # narożnik dokładnie
    move_both_and_wait(
        mpc,
        *L_CORNER,
    )

    # ========================================================
    # RAMIĘ 2
    # ========================================================

    while True:

        p2 = read_paddle_angle(
            mpc,
            2,
        )

        if p2 >= 139.8:
            break

        window_id += 1

        result = (
            run_continuous_window(
                mpc,
                mdt,
                ads,
                speed_deg_s,
                segment=2,
                direction_up=direction_up,
            )
        )

        direction_up = (
            not direction_up
        )

        s = path_coordinate(
            result[
                "p1_mean_deg"
            ],
            result[
                "p2_mean_deg"
            ],
        )

        row = {
            "window_id":
                window_id,

            "speed_deg_s":
                speed_deg_s,

            "segment":
                2,

            "p1_mean_deg":
                result[
                    "p1_mean_deg"
                ],

            "p2_mean_deg":
                result[
                    "p2_mean_deg"
                ],

            "s_deg":
                s,

            "diff_amplitude_v":
                result[
                    "diff_amplitude_v"
                ],

            "score":
                result[
                    "score"
                ],

            "samples":
                result[
                    "samples"
                ],
        }

        rows.append(row)

        print(
            f"W{window_id:02d} "
            f"s={s:6.2f}° "
            f"A_D="
            f"{result['diff_amplitude_v']:.5f} V"
        )

    move_both_and_wait(
        mpc,
        *L_END,
    )

    filename = (
        OUTPUT_DIR
        /
        f"continuous_{speed_deg_s:.1f}_deg_s.csv"
    )

    save_csv(
        filename,
        rows,
    )

    return rows


# ============================================================
# PORÓWNANIE Z REFERENCJĄ
# ============================================================

def compare_to_reference(
    reference,
    continuous,
    speed,
):

    ref_s = np.array(
        [
            r["s_deg"]
            for r in reference
        ],
        dtype=float,
    )

    ref_a = np.array(
        [
            r["diff_amplitude_v"]
            for r in reference
        ],
        dtype=float,
    )

    order = np.argsort(
        ref_s
    )

    ref_s = ref_s[order]
    ref_a = ref_a[order]

    rows = []

    measured_values = []
    reference_values = []

    for row in continuous:

        s = float(
            row["s_deg"]
        )

        if (
            s < ref_s.min()
            or
            s > ref_s.max()
        ):
            continue

        ref_value = float(
            np.interp(
                s,
                ref_s,
                ref_a,
            )
        )

        measured = float(
            row[
                "diff_amplitude_v"
            ]
        )

        error_v = (
            measured
            -
            ref_value
        )

        relative_error = (
            abs(error_v)
            /
            ref_value
            *
            100.0
        )

        measured_values.append(
            measured
        )

        reference_values.append(
            ref_value
        )

        rows.append(
            {
                "speed_deg_s":
                    speed,

                "s_deg":
                    s,

                "measured_A_D_v":
                    measured,

                "reference_A_D_v":
                    ref_value,

                "error_v":
                    error_v,

                "abs_error_v":
                    abs(error_v),

                "relative_error_pct":
                    relative_error,
            }
        )

    if len(rows) < 2:

        return None, rows

    measured_values = np.array(
        measured_values
    )

    reference_values = np.array(
        reference_values
    )

    errors = (
        measured_values
        -
        reference_values
    )

    relative_errors = (
        np.abs(errors)
        /
        reference_values
        *
        100.0
    )

    mae = float(
        np.mean(
            np.abs(errors)
        )
    )

    rmse = float(
        np.sqrt(
            np.mean(
                errors ** 2
            )
        )
    )

    mean_error_pct = float(
        np.mean(
            relative_errors
        )
    )

    max_error_pct = float(
        np.max(
            relative_errors
        )
    )

    correlation = float(
        np.corrcoef(
            measured_values,
            reference_values,
        )[0, 1]
    )

    acceptable = (
        mean_error_pct
        <=
        MAX_MEAN_ERROR_PCT
        and
        correlation
        >=
        MIN_CORRELATION
    )

    summary = {
        "speed_deg_s":
            speed,

        "windows":
            len(rows),

        "spatial_window_deg":
            speed
            *
            HALF_CYCLE_TIME_S,

        "mae_v":
            mae,

        "rmse_v":
            rmse,

        "mean_relative_error_pct":
            mean_error_pct,

        "max_relative_error_pct":
            max_error_pct,

        "correlation":
            correlation,

        "acceptable":
            int(acceptable),
    }

    return (
        summary,
        rows,
    )


# ============================================================
# CSV
# ============================================================

def save_csv(
    path,
    rows,
):

    if not rows:
        return

    with open(
        path,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(
            rows
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
        print(
            "TEST MAKSYMALNEJ UŻYTECZNEJ "
            "PRĘDKOŚCI MPC"
        )
        print("=" * 80)

        print()
        print(
            f"Piezo: {PIEZO_SPEED_V_S:.1f} V/s"
        )

        print(
            f"Półcykl piezo: "
            f"{HALF_CYCLE_TIME_S:.2f} s"
        )

        print()

        for speed in (
            MPC_SPEEDS_DEG_S
        ):

            spatial_window = (
                speed
                *
                HALF_CYCLE_TIME_S
            )

            print(
                f"{speed:4.1f}°/s -> "
                f"okno przestrzenne "
                f"{spatial_window:.2f}°"
            )

        # ====================================================
        # POŁĄCZENIA
        # ====================================================

        print()
        print("Łączenie MPC220...")

        mpc = MPC220Driver(
            MPC_PORT
        )

        mpc.connect()

        print("MPC220 OK")

        print()
        print("Łączenie MDT694B...")

        mdt = MDT694BDriver(
            MDT_PORT
        )

        mdt.connect()

        print("MDT694B OK")

        print()
        print("Łączenie ADS1263...")

        ads = connect_ads()

        print("ADS1263 OK")

        # ====================================================
        # PRZYGOTOWANIE
        # ====================================================

        move_both_and_wait(
            mpc,
            *L_START,
        )

        condition_piezo(mdt)
        discard_ads_samples(ads)

        # ====================================================
        # REFERENCJA
        # ====================================================

        reference = (
            run_point_reference(
                mpc,
                mdt,
                ads,
            )
        )

        # ====================================================
        # TESTY PRĘDKOŚCI
        # ====================================================

        summaries = []

        all_comparisons = []

        for speed in (
            MPC_SPEEDS_DEG_S
        ):

            continuous = (
                run_continuous_L(
                    mpc,
                    mdt,
                    ads,
                    speed,
                )
            )

            summary, comparison = (
                compare_to_reference(
                    reference,
                    continuous,
                    speed,
                )
            )

            if summary is not None:

                summaries.append(
                    summary
                )

                all_comparisons.extend(
                    comparison
                )

                print()
                print(
                    f"WYNIK {speed:.1f}°/s"
                )

                print(
                    f"  okno MPC: "
                    f"{summary['spatial_window_deg']:.2f}°"
                )

                print(
                    f"  MAE: "
                    f"{summary['mae_v']:.5f} V"
                )

                print(
                    f"  średni błąd: "
                    f"{summary['mean_relative_error_pct']:.2f}%"
                )

                print(
                    f"  max błąd: "
                    f"{summary['max_relative_error_pct']:.2f}%"
                )

                print(
                    f"  korelacja: "
                    f"{summary['correlation']:.4f}"
                )

                print(
                    "  wynik: "
                    +
                    (
                        "OK"
                        if summary[
                            "acceptable"
                        ]
                        else
                        "NIE"
                    )
                )

        save_csv(
            OUTPUT_DIR
            / "comparison_all.csv",
            all_comparisons,
        )

        save_csv(
            OUTPUT_DIR
            / "speed_summary.csv",
            summaries,
        )

        # ====================================================
        # MAKSYMALNA PRĘDKOŚĆ
        # ====================================================

        acceptable = [
            r
            for r in summaries
            if r[
                "acceptable"
            ]
            ==
            1
        ]

        print()
        print("=" * 80)
        print("WYNIK KOŃCOWY")
        print("=" * 80)

        if acceptable:

            best = max(
                acceptable,
                key=lambda r:
                    r["speed_deg_s"],
            )

            print()
            print(
                "Największa zwalidowana "
                "prędkość:"
            )

            print(
                f"  {best['speed_deg_s']:.2f}°/s"
            )

            print(
                f"Średni błąd:"
                f" {best['mean_relative_error_pct']:.2f}%"
            )

            print(
                f"Korelacja:"
                f" {best['correlation']:.4f}"
            )

            print(
                f"Okno przestrzenne:"
                f" {best['spatial_window_deg']:.2f}°"
            )

            if (
                best[
                    "speed_deg_s"
                ]
                ==
                max(
                    MPC_SPEEDS_DEG_S
                )
            ):

                print()
                print(
                    "UWAGA: najwyższa "
                    "testowana prędkość nadal "
                    "spełnia kryterium."
                )

                print(
                    "To oznacza, że rzeczywiste "
                    "maksimum może być jeszcze wyższe."
                )

        else:

            print()
            print(
                "Żadna prędkość nie spełniła "
                "ustalonego kryterium."
            )

        print()
        print(
            f"Wyniki zapisane w:"
        )

        print(
            OUTPUT_DIR
        )

    finally:

        print()
        print("Zamykanie urządzeń...")

        if mdt is not None:

            try:
                fast_set_voltage(
                    mdt,
                    PIEZO_MIN_V,
                )
            except Exception:
                pass

        close_ads(ads)

        if mdt is not None:

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

        print("Koniec.")


if __name__ == "__main__":
    main()