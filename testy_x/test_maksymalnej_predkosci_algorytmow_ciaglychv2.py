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
    / "test_maksymalnej_predkosci_mpc_L"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# IMPORTY
# ============================================================

from modules.mpc220.driver import MPC220Driver
from modules.mpc220.calibration import (
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

ANGLE_MIN = 100.0
ANGLE_MAX = 140.0


# ============================================================
# TESTOWANE PRĘDKOŚCI
# ============================================================

MPC_SPEEDS_DEG_S = [
    2.0,
    3.0,
    4.0,
    5.0,
]

MPC_COMMAND_INTERVAL_S = 0.12
MPC_SETTLE_S = 0.8


# ============================================================
# REFERENCJA
# ============================================================

REFERENCE_STEP_DEG = 5.0


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
# MPC
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
# MDT / PIEZO
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

    duration = (
        abs(end_v - start_v)
        / PIEZO_SPEED_V_S
    )

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

    fast_set_voltage(
        mdt,
        end_v,
    )


def condition_piezo(mdt):

    print("Kondycjonowanie piezo...")

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
    )

    time.sleep(0.2)

    ramp_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )


# ============================================================
# ADS
# ============================================================

def connect_ads():

    ads = ADS1263Driver()

    if hasattr(ads, "connect"):
        ads.connect()

    ads.start_measurement()

    return ads


def discard_ads_samples(ads):

    for _ in range(DISCARD_SAMPLES):

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

    if hasattr(ads, "disconnect"):

        try:
            ads.disconnect()
        except Exception:
            pass

    elif hasattr(ads, "close"):

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
        [x["in0_v"] for x in samples],
        dtype=float,
    )

    in1 = np.array(
        [x["in1_v"] for x in samples],
        dtype=float,
    )

    diff = in0 - in1

    diff_amplitude = (
        np.percentile(diff, 95)
        -
        np.percentile(diff, 5)
    ) / 2.0

    total = in0 + in1

    valid = (
        np.abs(total) > 1e-9
    )

    normalized = (
        diff[valid]
        /
        total[valid]
    )

    if len(normalized) >= 5:

        score = (
            np.percentile(
                normalized,
                95,
            )
            -
            np.percentile(
                normalized,
                5,
            )
        ) / 2.0

    else:

        score = float("nan")

    return {
        "diff_amplitude_v":
            float(diff_amplitude),

        "score":
            float(score),

        "samples":
            len(samples),
    }


# ============================================================
# WSPÓŁRZĘDNA WZDŁUŻ L
#
# s = 0   -> (100,100)
# s = 40  -> (140,100)
# s = 80  -> (140,140)
# ============================================================

def path_coordinate(
    segment,
    p1,
    p2,
):

    if segment == 1:

        return p1 - 100.0

    return (
        40.0
        +
        (p2 - 100.0)
    )


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

    start_t = time.monotonic()

    next_piezo = start_t
    next_sample = start_t

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_t
        )

        progress = min(
            elapsed / HALF_CYCLE_TIME_S,
            1.0,
        )

        # --------------------------------------------
        # PIEZO 80 -> 150 V
        # --------------------------------------------

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

        # --------------------------------------------
        # ADS
        # --------------------------------------------

        if now >= next_sample:

            in0, in1 = ads.read_sample()

            samples.append(
                {
                    "in0_v": float(in0),
                    "in1_v": float(in1),
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

    fast_set_voltage(
        mdt,
        PIEZO_MAX_V,
    )

    # powrót 150 -> 80 bez pomiaru
    ramp_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    return calculate_metrics(
        samples
    )


# ============================================================
# REFERENCJA PUNKTOWA L
# ============================================================

def run_reference(
    mpc,
    mdt,
    ads,
):

    print()
    print("=" * 80)
    print("REFERENCJA PUNKTOWA L")
    print("=" * 80)

    rows = []

    point_id = 0

    angles = np.arange(
        100.0,
        140.001,
        REFERENCE_STEP_DEG,
    )

    # ========================================================
    # RAMIĘ 1
    # (100,100) -> (140,100)
    # ========================================================

    for p1 in angles:

        point_id += 1

        actual1, actual2 = (
            move_both_and_wait(
                mpc,
                float(p1),
                100.0,
            )
        )

        result = (
            measure_stationary_point(
                mdt,
                ads,
            )
        )

        s = path_coordinate(
            1,
            actual1,
            actual2,
        )

        row = {
            "point_id":
                point_id,

            "segment":
                1,

            "p1_deg":
                actual1,

            "p2_deg":
                actual2,

            "s_deg":
                s,

            "diff_amplitude_v":
                result[
                    "diff_amplitude_v"
                ],

            "score":
                result["score"],

            "samples":
                result["samples"],
        }

        rows.append(row)

        print(
            f"REF {point_id:02d} | "
            f"P1={actual1:7.3f}° | "
            f"P2={actual2:7.3f}° | "
            f"A_D="
            f"{result['diff_amplitude_v']:.6f} V"
        )

    # ========================================================
    # RAMIĘ 2
    # (140,105) -> (140,140)
    # ========================================================

    for p2 in angles[1:]:

        point_id += 1

        actual1, actual2 = (
            move_both_and_wait(
                mpc,
                140.0,
                float(p2),
            )
        )

        result = (
            measure_stationary_point(
                mdt,
                ads,
            )
        )

        s = path_coordinate(
            2,
            actual1,
            actual2,
        )

        row = {
            "point_id":
                point_id,

            "segment":
                2,

            "p1_deg":
                actual1,

            "p2_deg":
                actual2,

            "s_deg":
                s,

            "diff_amplitude_v":
                result[
                    "diff_amplitude_v"
                ],

            "score":
                result["score"],

            "samples":
                result["samples"],
        }

        rows.append(row)

        print(
            f"REF {point_id:02d} | "
            f"P1={actual1:7.3f}° | "
            f"P2={actual2:7.3f}° | "
            f"A_D="
            f"{result['diff_amplitude_v']:.6f} V"
        )

    save_csv(
        OUTPUT_DIR
        / "reference_L_2_3_4_5.csv",
        rows,
    )

    return rows


# ============================================================
# JEDNO CIĄGŁE OKNO = JEDEN PÓŁCYKL PIEZO
# ============================================================

def run_continuous_window(
    mpc,
    mdt,
    ads,
    paddle,
    start_angle,
    move_sign,
    speed_deg_s,
    piezo_up,
):

    samples = []

    start_t = time.monotonic()

    next_mpc = start_t
    next_piezo = start_t
    next_sample = start_t

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_t
        )

        progress = min(
            elapsed / HALF_CYCLE_TIME_S,
            1.0,
        )

        # ====================================================
        # RUCH MPC
        # ====================================================

        if now >= next_mpc:

            target = (
                start_angle
                +
                move_sign
                *
                speed_deg_s
                *
                elapsed
            )

            target = max(
                ANGLE_MIN,
                min(
                    ANGLE_MAX,
                    target,
                )
            )

            mpc.move_absolute_units(
                paddle,
                angle_to_command(target),
            )

            next_mpc = (
                now
                +
                MPC_COMMAND_INTERVAL_S
            )

        # ====================================================
        # PIEZO
        # ====================================================

        if now >= next_piezo:

            if piezo_up:

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

        # ====================================================
        # ADS
        # ====================================================

        if now >= next_sample:

            in0, in1 = ads.read_sample()

            p1 = read_paddle_angle(
                mpc,
                1,
            )

            p2 = read_paddle_angle(
                mpc,
                2,
            )

            samples.append(
                {
                    "time_s":
                        elapsed,

                    "p1_deg":
                        p1,

                    "p2_deg":
                        p2,

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

    # Ustawiamy dokładny koniec półcyklu piezo.

    if piezo_up:

        fast_set_voltage(
            mdt,
            PIEZO_MAX_V,
        )

    else:

        fast_set_voltage(
            mdt,
            PIEZO_MIN_V,
        )

    metrics = calculate_metrics(
        samples
    )

    p1_values = np.array(
        [x["p1_deg"] for x in samples],
        dtype=float,
    )

    p2_values = np.array(
        [x["p2_deg"] for x in samples],
        dtype=float,
    )

    return {
        "p1_start_deg":
            float(p1_values[0]),

        "p1_end_deg":
            float(p1_values[-1]),

        "p1_mean_deg":
            float(np.mean(p1_values)),

        "p2_start_deg":
            float(p2_values[0]),

        "p2_end_deg":
            float(p2_values[-1]),

        "p2_mean_deg":
            float(np.mean(p2_values)),

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
# JEDEN SEGMENT L
# ============================================================

def run_segment(
    mpc,
    mdt,
    ads,
    speed,
    segment,
    move_sign,
    piezo_up,
    travel_direction,
    start_window_id,
):

    rows = []

    window_id = start_window_id

    if segment == 1:

        paddle = 1

    else:

        paddle = 2

    while True:

        current = read_paddle_angle(
            mpc,
            paddle,
        )

        # --------------------------------------------
        # Ile zostało do końca ramienia?
        # --------------------------------------------

        if move_sign > 0:

            remaining = (
                ANGLE_MAX
                - current
            )

        else:

            remaining = (
                current
                - ANGLE_MIN
            )

        # --------------------------------------------
        # Pełne okno wymaga przejazdu:
        #
        # speed * 3.5 s
        #
        # Nie mierzymy niepełnego półcyklu.
        # --------------------------------------------

        window_distance = (
            speed
            *
            HALF_CYCLE_TIME_S
        )

        if remaining < (
            window_distance * 0.95
        ):
            break

        window_id += 1

        result = (
            run_continuous_window(
                mpc,
                mdt,
                ads,
                paddle,
                current,
                move_sign,
                speed,
                piezo_up,
            )
        )

        piezo_direction = (
            "up"
            if piezo_up
            else
            "down"
        )

        piezo_up = not piezo_up

        s = path_coordinate(
            segment,
            result[
                "p1_mean_deg"
            ],
            result[
                "p2_mean_deg"
            ],
        )

        row = {
            "speed_deg_s":
                speed,

            "travel_direction":
                travel_direction,

            "window_id":
                window_id,

            "segment":
                segment,

            "piezo_direction":
                piezo_direction,

            "p1_start_deg":
                result[
                    "p1_start_deg"
                ],

            "p1_end_deg":
                result[
                    "p1_end_deg"
                ],

            "p1_mean_deg":
                result[
                    "p1_mean_deg"
                ],

            "p2_start_deg":
                result[
                    "p2_start_deg"
                ],

            "p2_end_deg":
                result[
                    "p2_end_deg"
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
                result["score"],

            "samples":
                result["samples"],
        }

        rows.append(row)

        print(
            f"{speed:.1f}°/s | "
            f"{travel_direction:7s} | "
            f"seg={segment} | "
            f"W{window_id:02d} | "
            f"s={s:6.2f}° | "
            f"A_D="
            f"{result['diff_amplitude_v']:.6f} V"
        )

    return (
        rows,
        piezo_up,
        window_id,
    )


# ============================================================
# L TAM I Z POWROTEM
# ============================================================

def run_L_roundtrip(
    mpc,
    mdt,
    ads,
    speed,
):

    print()
    print("=" * 80)

    print(
        f"TEST L TAM I Z POWROTEM | "
        f"{speed:.1f}°/s"
    )

    print(
        f"Jedno okno obejmuje około "
        f"{speed * HALF_CYCLE_TIME_S:.1f}°"
    )

    print("=" * 80)

    rows = []

    window_id = 0
    piezo_up = True

    # ========================================================
    # START
    # ========================================================

    move_both_and_wait(
        mpc,
        *L_START,
    )

    condition_piezo(mdt)
    discard_ads_samples(ads)

    # ========================================================
    # FORWARD
    #
    # (100,100) -> (140,100)
    # ========================================================

    part, piezo_up, window_id = run_segment(
        mpc,
        mdt,
        ads,
        speed,
        segment=1,
        move_sign=+1,
        piezo_up=piezo_up,
        travel_direction="forward",
        start_window_id=window_id,
    )

    rows.extend(part)

    # Dokładnie ustaw narożnik.

    move_both_and_wait(
        mpc,
        *L_CORNER,
    )

    # ========================================================
    # FORWARD
    #
    # (140,100) -> (140,140)
    # ========================================================

    part, piezo_up, window_id = run_segment(
        mpc,
        mdt,
        ads,
        speed,
        segment=2,
        move_sign=+1,
        piezo_up=piezo_up,
        travel_direction="forward",
        start_window_id=window_id,
    )

    rows.extend(part)

    move_both_and_wait(
        mpc,
        *L_END,
    )

    # ========================================================
    # REVERSE
    #
    # (140,140) -> (140,100)
    # ========================================================

    part, piezo_up, window_id = run_segment(
        mpc,
        mdt,
        ads,
        speed,
        segment=2,
        move_sign=-1,
        piezo_up=piezo_up,
        travel_direction="reverse",
        start_window_id=window_id,
    )

    rows.extend(part)

    move_both_and_wait(
        mpc,
        *L_CORNER,
    )

    # ========================================================
    # REVERSE
    #
    # (140,100) -> (100,100)
    # ========================================================

    part, piezo_up, window_id = run_segment(
        mpc,
        mdt,
        ads,
        speed,
        segment=1,
        move_sign=-1,
        piezo_up=piezo_up,
        travel_direction="reverse",
        start_window_id=window_id,
    )

    rows.extend(part)

    move_both_and_wait(
        mpc,
        *L_START,
    )

    filename = (
        OUTPUT_DIR
        /
        f"L_{speed:.1f}_deg_s_tam_i_z_powrotem.csv"
    )

    save_csv(
        filename,
        rows,
    )

    return rows


# ============================================================
# PORÓWNANIE Z REFERENCJĄ
# ============================================================

def compare_with_reference(
    reference,
    measurements,
):

    ref_s = np.array(
        [
            x["s_deg"]
            for x in reference
        ],
        dtype=float,
    )

    ref_a = np.array(
        [
            x["diff_amplitude_v"]
            for x in reference
        ],
        dtype=float,
    )

    order = np.argsort(ref_s)

    ref_s = ref_s[order]
    ref_a = ref_a[order]

    rows = []

    for measurement in measurements:

        s = float(
            measurement["s_deg"]
        )

        reference_value = float(
            np.interp(
                s,
                ref_s,
                ref_a,
            )
        )

        measured_value = float(
            measurement[
                "diff_amplitude_v"
            ]
        )

        error_v = (
            measured_value
            - reference_value
        )

        error_pct = (
            abs(error_v)
            /
            reference_value
            *
            100.0
        )

        rows.append(
            {
                "speed_deg_s":
                    measurement[
                        "speed_deg_s"
                    ],

                "travel_direction":
                    measurement[
                        "travel_direction"
                    ],

                "window_id":
                    measurement[
                        "window_id"
                    ],

                "segment":
                    measurement[
                        "segment"
                    ],

                "s_deg":
                    s,

                "measured_A_D_v":
                    measured_value,

                "reference_A_D_v":
                    reference_value,

                "error_v":
                    error_v,

                "relative_error_pct":
                    error_pct,
            }
        )

    return rows


# ============================================================
# PODSUMOWANIE
# ============================================================

def make_summary(
    comparisons,
):

    rows = []

    for speed in MPC_SPEEDS_DEG_S:

        group = [
            x
            for x in comparisons
            if x[
                "speed_deg_s"
            ] == speed
        ]

        if not group:
            continue

        forward = [
            x
            for x in group
            if x[
                "travel_direction"
            ] == "forward"
        ]

        reverse = [
            x
            for x in group
            if x[
                "travel_direction"
            ] == "reverse"
        ]

        all_errors = np.array(
            [
                x[
                    "relative_error_pct"
                ]
                for x in group
            ],
            dtype=float,
        )

        forward_errors = np.array(
            [
                x[
                    "relative_error_pct"
                ]
                for x in forward
            ],
            dtype=float,
        )

        reverse_errors = np.array(
            [
                x[
                    "relative_error_pct"
                ]
                for x in reverse
            ],
            dtype=float,
        )

        forward_A = np.array(
            [
                x["measured_A_D_v"]
                for x in forward
            ],
            dtype=float,
        )

        reverse_A = np.array(
            [
                x["measured_A_D_v"]
                for x in reverse
            ],
            dtype=float,
        )

        # Korelacja z referencją
        measured = np.array(
            [
                x["measured_A_D_v"]
                for x in group
            ],
            dtype=float,
        )

        reference_values = np.array(
            [
                x["reference_A_D_v"]
                for x in group
            ],
            dtype=float,
        )

        if len(measured) >= 2:

            correlation = float(
                np.corrcoef(
                    measured,
                    reference_values,
                )[0, 1]
            )

        else:

            correlation = float("nan")

        rows.append(
            {
                "speed_deg_s":
                    speed,

                "spatial_window_deg":
                    speed
                    *
                    HALF_CYCLE_TIME_S,

                "windows_total":
                    len(group),

                "windows_forward":
                    len(forward),

                "windows_reverse":
                    len(reverse),

                "mean_error_all_pct":
                    float(
                        np.mean(
                            all_errors
                        )
                    ),

                "max_error_all_pct":
                    float(
                        np.max(
                            all_errors
                        )
                    ),

                "mean_error_forward_pct":
                    float(
                        np.mean(
                            forward_errors
                        )
                    )
                    if len(
                        forward_errors
                    )
                    else
                    float("nan"),

                "mean_error_reverse_pct":
                    float(
                        np.mean(
                            reverse_errors
                        )
                    )
                    if len(
                        reverse_errors
                    )
                    else
                    float("nan"),

                "correlation_reference":
                    correlation,
            }
        )

    return rows


# ============================================================
# CSV
# ============================================================

def save_csv(
    filepath,
    rows,
):

    if not rows:
        return

    with open(
        filepath,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(rows)


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
            "TEST PRĘDKOŚCI MPC "
            "2 / 3 / 4 / 5°/s"
        )
        print("=" * 80)

        print()

        print(
            f"Piezo: "
            f"{PIEZO_MIN_V:.0f}"
            f"–"
            f"{PIEZO_MAX_V:.0f} V"
        )

        print(
            f"Prędkość piezo: "
            f"{PIEZO_SPEED_V_S:.1f} V/s"
        )

        print(
            f"Półcykl piezo: "
            f"{HALF_CYCLE_TIME_S:.2f} s"
        )

        print()

        for speed in MPC_SPEEDS_DEG_S:

            print(
                f"{speed:.1f}°/s -> "
                f"ruch MPC w jednym pomiarze "
                f"~"
                f"{speed * HALF_CYCLE_TIME_S:.1f}°"
            )

        # ====================================================
        # MPC
        # ====================================================

        print()
        print("Łączenie MPC220...")

        mpc = MPC220Driver(
            MPC_PORT
        )

        mpc.connect()

        print("MPC220 OK")

        # ====================================================
        # MDT
        # ====================================================

        print()
        print("Łączenie MDT694B...")

        mdt = MDT694BDriver(
            MDT_PORT
        )

        mdt.connect()

        print("MDT694B OK")

        # ====================================================
        # ADS
        # ====================================================

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

        reference = run_reference(
            mpc,
            mdt,
            ads,
        )

        # ====================================================
        # TESTY
        # ====================================================

        all_measurements = []
        all_comparisons = []

        for speed in MPC_SPEEDS_DEG_S:

            measurements = (
                run_L_roundtrip(
                    mpc,
                    mdt,
                    ads,
                    speed,
                )
            )

            all_measurements.extend(
                measurements
            )

            comparison = (
                compare_with_reference(
                    reference,
                    measurements,
                )
            )

            all_comparisons.extend(
                comparison
            )

        # ====================================================
        # ZAPIS ŁĄCZNY
        # ====================================================

        save_csv(
            OUTPUT_DIR
            /
            "L_2_3_4_5_all_measurements.csv",
            all_measurements,
        )

        save_csv(
            OUTPUT_DIR
            /
            "L_2_3_4_5_comparison.csv",
            all_comparisons,
        )

        # ====================================================
        # PODSUMOWANIE
        # ====================================================

        summary = make_summary(
            all_comparisons
        )

        save_csv(
            OUTPUT_DIR
            /
            "L_2_3_4_5_summary.csv",
            summary,
        )

        print()
        print("=" * 80)
        print("PODSUMOWANIE")
        print("=" * 80)

        for row in summary:

            print()

            print(
                f"{row['speed_deg_s']:.1f}°/s"
            )

            print(
                f"  okno przestrzenne: "
                f"{row['spatial_window_deg']:.1f}°"
            )

            print(
                f"  liczba okien: "
                f"{row['windows_total']}"
            )

            print(
                f"  błąd średni: "
                f"{row['mean_error_all_pct']:.2f}%"
            )

            print(
                f"  forward: "
                f"{row['mean_error_forward_pct']:.2f}%"
            )

            print(
                f"  reverse: "
                f"{row['mean_error_reverse_pct']:.2f}%"
            )

            print(
                f"  błąd max: "
                f"{row['max_error_all_pct']:.2f}%"
            )

            print(
                f"  korelacja: "
                f"{row['correlation_reference']:.4f}"
            )

        print()
        print("=" * 80)
        print("TEST ZAKOŃCZONY")
        print("=" * 80)

        print()

        print(
            "Najważniejszy plik:"
        )

        print(
            OUTPUT_DIR
            /
            "L_2_3_4_5_summary.csv"
        )

    finally:

        print()
        print("Zamykanie urządzeń...")

        # ====================================================
        # PIEZO -> 80 V
        # ====================================================

        if mdt is not None:

            try:

                fast_set_voltage(
                    mdt,
                    PIEZO_MIN_V,
                )

            except Exception:
                pass

        # ====================================================
        # ADS
        # ====================================================

        close_ads(ads)

        # ====================================================
        # MDT
        # ====================================================

        if mdt is not None:

            try:

                mdt.close()

            except Exception:

                try:
                    mdt.disconnect()
                except Exception:
                    pass

        # ====================================================
        # MPC
        # ====================================================

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