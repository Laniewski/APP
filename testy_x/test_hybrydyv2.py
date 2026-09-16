import sys
import csv
import math
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
    / "test_hybrydy_multistart_prog_045"
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
# MPC
# ============================================================

MPC_MIN_DEG = 1.0
MPC_MAX_DEG = 160.0

MPC_COMMAND_INTERVAL_S = 0.12
MPC_SETTLE_S = 0.8


# ============================================================
# PUNKTY STARTOWE
# ============================================================

START_POINTS = [
    {
        "name": "lower_left",
        "p1": 25.0,
        "p2": 45.0,
    },
    {
        "name": "lower_right",
        "p1": 125.0,
        "p2": 50.0,
    },
    {
        "name": "upper_left",
        "p1": 20.0,
        "p2": 125.0,
    },
    {
        "name": "upper_right",
        "p1": 140.0,
        "p2": 140.0,
    },
]


# ============================================================
# COORDINATE
# ============================================================

COORDINATE_SPEED_DEG_S = 5.0

# NOWY PRÓG
COORDINATE_TARGET_V = 0.45

# Maksymalny czas Coordinate dla jednego punktu startowego.
COORDINATE_MAX_TIME_S = 40.0

COORDINATE_DIRECTIONS = [
    (+1.0, 0.0),
    (-1.0, 0.0),
    (0.0, +1.0),
    (0.0, -1.0),
]


# ============================================================
# ADAPTIVE
# ============================================================

ADAPTIVE_SPEED_DEG_S = 2.0

# Adaptive uruchamia się po przekroczeniu 0.45 V.
ADAPTIVE_TARGET_V = 0.45

# Maksymalnie 10 sekund lokalnego szukania maksimum.
ADAPTIVE_MAX_TIME_S = 10.0

ADAPTIVE_DIRECTION_STEP_DEG = 45.0


# ============================================================
# DETEKCJA MAKSIMUM
# ============================================================

# Adaptive NIE zatrzymuje się przy 0.45 V.
#
# Zapamiętuje najlepsze A_D.
# Jeżeli wynik spadnie o ponad 10 mV względem best,
# uznajemy, że przejechaliśmy przez maksimum.

MAXIMUM_DEPARTURE_V = 0.010

# Dwa kolejne okna z wyraźnym spadkiem.
MAX_DEPARTURE_WINDOWS = 2


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
# MPC - FUNKCJE
# ============================================================

def clamp_angle(angle):
    return max(
        MPC_MIN_DEG,
        min(MPC_MAX_DEG, angle),
    )


def read_paddle_angle(mpc, paddle):
    raw = mpc.read_position_units(paddle)
    return raw_position_to_angle(raw)


def read_both_angles(mpc):
    return (
        read_paddle_angle(mpc, 1),
        read_paddle_angle(mpc, 2),
    )


def move_both_and_wait(mpc, p1_deg, p2_deg):

    p1_deg = clamp_angle(p1_deg)
    p2_deg = clamp_angle(p2_deg)

    mpc.move_absolute_units(
        1,
        angle_to_command(p1_deg),
    )

    mpc.move_absolute_units(
        2,
        angle_to_command(p2_deg),
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    time.sleep(MPC_SETTLE_S)

    return read_both_angles(mpc)


# ============================================================
# PIEZO
# ============================================================

def fast_set_voltage(mdt, voltage):
    mdt._send_command(
        f"xvoltage={voltage:.3f}"
    )


def ramp_piezo(mdt, start_v, end_v):

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
            + (end_v - start_v)
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
# METRYKA
# ============================================================

def calculate_metrics(samples):

    if len(samples) < 5:

        return {
            "diff_amplitude_v": float("nan"),
            "score": float("nan"),
            "mean_sum_v": float("nan"),
        }

    in0 = np.array(
        [row["in0_v"] for row in samples],
        dtype=float,
    )

    in1 = np.array(
        [row["in1_v"] for row in samples],
        dtype=float,
    )

    diff = in0 - in1

    diff_amplitude = (
        np.percentile(diff, 95)
        - np.percentile(diff, 5)
    ) / 2.0

    total = in0 + in1

    valid = (
        np.abs(total) > 1e-9
    )

    normalized = (
        diff[valid]
        / total[valid]
    )

    if len(normalized) >= 5:

        score = (
            np.percentile(normalized, 95)
            - np.percentile(normalized, 5)
        ) / 2.0

    else:

        score = float("nan")

    return {
        "diff_amplitude_v":
            float(diff_amplitude),

        "score":
            float(score),

        "mean_sum_v":
            float(np.mean(total)),
    }


# ============================================================
# CSV
# ============================================================

def save_csv(path, rows):

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
        writer.writerows(rows)


# ============================================================
# POJEDYNCZE OKNO POMIAROWE
# ============================================================

def run_motion_window(
    mpc,
    mdt,
    ads,
    direction_p1,
    direction_p2,
    speed_deg_s,
    piezo_up,
    phase,
    seed_id,
    seed_name,
    window_id,
    algorithm_start_t,
):

    norm = math.hypot(
        direction_p1,
        direction_p2,
    )

    if norm < 1e-9:

        raise ValueError(
            "Kierunek ruchu ma długość 0."
        )

    direction_p1 /= norm
    direction_p2 /= norm

    start_p1, start_p2 = (
        read_both_angles(mpc)
    )

    samples = []

    window_start_t = (
        time.monotonic()
    )

    next_mpc = window_start_t
    next_piezo = window_start_t
    next_sample = window_start_t

    while True:

        now = time.monotonic()

        elapsed = (
            now - window_start_t
        )

        progress = min(
            elapsed / HALF_CYCLE_TIME_S,
            1.0,
        )

        # ====================================================
        # MPC
        # ====================================================

        if now >= next_mpc:

            distance = (
                speed_deg_s
                * elapsed
            )

            target_p1 = clamp_angle(
                start_p1
                + direction_p1
                * distance
            )

            target_p2 = clamp_angle(
                start_p2
                + direction_p2
                * distance
            )

            mpc.move_absolute_units(
                1,
                angle_to_command(
                    target_p1
                ),
            )

            mpc.move_absolute_units(
                2,
                angle_to_command(
                    target_p2
                ),
            )

            next_mpc = (
                now
                + MPC_COMMAND_INTERVAL_S
            )

        # ====================================================
        # PIEZO
        # ====================================================

        if now >= next_piezo:

            if piezo_up:

                voltage = (
                    PIEZO_MIN_V
                    + (
                        PIEZO_MAX_V
                        - PIEZO_MIN_V
                    )
                    * progress
                )

            else:

                voltage = (
                    PIEZO_MAX_V
                    - (
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
                + PIEZO_COMMAND_INTERVAL_S
            )

        # ====================================================
        # ADS
        # ====================================================

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

            p1, p2 = (
                read_both_angles(
                    mpc
                )
            )

            samples.append(
                {
                    "seed_id":
                        seed_id,

                    "seed_name":
                        seed_name,

                    "phase":
                        phase,

                    "window_id":
                        window_id,

                    "algorithm_time_s":
                        now - algorithm_start_t,

                    "time_in_window_s":
                        elapsed,

                    "speed_deg_s":
                        speed_deg_s,

                    "piezo_direction":
                        (
                            "up"
                            if piezo_up
                            else "down"
                        ),

                    "p1_deg":
                        float(p1),

                    "p2_deg":
                        float(p2),

                    "in0_v":
                        float(in0),

                    "in1_v":
                        float(in1),

                    "diff_v":
                        float(in0 - in1),
                }
            )

            next_sample = (
                now
                + SAMPLE_INTERVAL_S
            )

        if progress >= 1.0:
            break

        time.sleep(0.001)

    # ========================================================
    # KOŃCOWE NAPIĘCIE PIEZO
    # ========================================================

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
        [
            row["p1_deg"]
            for row in samples
        ]
    )

    p2_values = np.array(
        [
            row["p2_deg"]
            for row in samples
        ]
    )

    end_p1, end_p2 = (
        read_both_angles(mpc)
    )

    summary = {

        "seed_id":
            seed_id,

        "seed_name":
            seed_name,

        "phase":
            phase,

        "window_id":
            window_id,

        "algorithm_time_s":
            time.monotonic()
            - algorithm_start_t,

        "speed_deg_s":
            speed_deg_s,

        "piezo_direction":
            (
                "up"
                if piezo_up
                else "down"
            ),

        "p1_start_deg":
            float(start_p1),

        "p2_start_deg":
            float(start_p2),

        "p1_end_deg":
            float(end_p1),

        "p2_end_deg":
            float(end_p2),

        "p1_mean_deg":
            float(
                np.mean(p1_values)
            ),

        "p2_mean_deg":
            float(
                np.mean(p2_values)
            ),

        "diff_amplitude_v":
            metrics[
                "diff_amplitude_v"
            ],

        "score":
            metrics["score"],

        "mean_sum_v":
            metrics[
                "mean_sum_v"
            ],

        "samples":
            len(samples),
    }

    return summary, samples


# ============================================================
# LOG
# ============================================================

def print_window(row):

    print(
        f"W{row['window_id']:03d} | "
        f"seed={row['seed_id']} | "
        f"{row['phase']:10s} | "
        f"v={row['speed_deg_s']:.1f}°/s | "
        f"P1={row['p1_mean_deg']:7.2f}° | "
        f"P2={row['p2_mean_deg']:7.2f}° | "
        f"A_D={row['diff_amplitude_v']:.6f} V | "
        f"t={row['algorithm_time_s']:.1f}s"
    )


# ============================================================
# COORDINATE
# ============================================================

def run_coordinate_phase(
    mpc,
    mdt,
    ads,
    seed_id,
    seed_name,
    algorithm_start_t,
    window_id_start,
    piezo_up_start,
):

    direction_index = 0
    previous_amplitude = None

    coordinate_start_t = (
        time.monotonic()
    )

    window_id = (
        window_id_start
    )

    piezo_up = (
        piezo_up_start
    )

    windows = []
    raw_rows = []

    best_amplitude = -np.inf
    best_p1 = float("nan")
    best_p2 = float("nan")

    while True:

        coordinate_elapsed = (
            time.monotonic()
            - coordinate_start_t
        )

        if (
            coordinate_elapsed
            >= COORDINATE_MAX_TIME_S
        ):

            return {
                "success": False,
                "reason":
                    "coordinate_timeout",

                "windows":
                    windows,

                "raw":
                    raw_rows,

                "window_id":
                    window_id,

                "piezo_up":
                    piezo_up,

                "direction_index":
                    direction_index,

                "best_amplitude":
                    best_amplitude,

                "best_p1":
                    best_p1,

                "best_p2":
                    best_p2,
            }

        dx, dy = (
            COORDINATE_DIRECTIONS[
                direction_index
            ]
        )

        window_id += 1

        row, samples = (
            run_motion_window(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                direction_p1=dx,
                direction_p2=dy,

                speed_deg_s=
                    COORDINATE_SPEED_DEG_S,

                piezo_up=
                    piezo_up,

                phase=
                    "COORDINATE",

                seed_id=
                    seed_id,

                seed_name=
                    seed_name,

                window_id=
                    window_id,

                algorithm_start_t=
                    algorithm_start_t,
            )
        )

        piezo_up = (
            not piezo_up
        )

        windows.append(row)
        raw_rows.extend(samples)

        print_window(row)

        amplitude = (
            row["diff_amplitude_v"]
        )

        # ====================================================
        # BEST
        # ====================================================

        if amplitude > best_amplitude:

            best_amplitude = amplitude

            best_p1 = row[
                "p1_mean_deg"
            ]

            best_p2 = row[
                "p2_mean_deg"
            ]

        # ====================================================
        # PRÓG 0.45 V
        # ====================================================

        if (
            amplitude
            >= COORDINATE_TARGET_V
        ):

            return {
                "success": True,

                "reason":
                    "coordinate_target_found",

                "windows":
                    windows,

                "raw":
                    raw_rows,

                "window_id":
                    window_id,

                "piezo_up":
                    piezo_up,

                "direction_index":
                    direction_index,

                "amplitude":
                    amplitude,

                "p1":
                    row["p1_mean_deg"],

                "p2":
                    row["p2_mean_deg"],

                "best_amplitude":
                    best_amplitude,

                "best_p1":
                    best_p1,

                "best_p2":
                    best_p2,
            }

        # ====================================================
        # LOGIKA COORDINATE
        # ====================================================

        if (
            previous_amplitude
            is not None
        ):

            if (
                amplitude
                <
                previous_amplitude
            ):

                direction_index = (
                    direction_index
                    + 1
                ) % len(
                    COORDINATE_DIRECTIONS
                )

        previous_amplitude = (
            amplitude
        )

        # ====================================================
        # GRANICE
        # ====================================================

        p1, p2 = (
            read_both_angles(mpc)
        )

        margin = (
            COORDINATE_SPEED_DEG_S
            * HALF_CYCLE_TIME_S
            + 1.0
        )

        if (
            p1 <= MPC_MIN_DEG + margin
            or
            p1 >= MPC_MAX_DEG - margin
            or
            p2 <= MPC_MIN_DEG + margin
            or
            p2 >= MPC_MAX_DEG - margin
        ):

            direction_index = (
                direction_index
                + 1
            ) % len(
                COORDINATE_DIRECTIONS
            )


# ============================================================
# ADAPTIVE
# ============================================================

def run_adaptive_phase(
    mpc,
    mdt,
    ads,
    seed_id,
    seed_name,
    algorithm_start_t,
    window_id_start,
    piezo_up_start,
    initial_direction_index,
    starting_amplitude,
):

    dx, dy = (
        COORDINATE_DIRECTIONS[
            initial_direction_index
        ]
    )

    direction_deg = (
        math.degrees(
            math.atan2(dy, dx)
        )
    )

    previous_amplitude = (
        starting_amplitude
    )

    best_amplitude = (
        starting_amplitude
    )

    best_p1, best_p2 = (
        read_both_angles(mpc)
    )

    best_time_s = (
        time.monotonic()
        - algorithm_start_t
    )

    # Coordinate już przekroczył 0.45 V.
    target_reached = True

    departure_count = 0

    rotation_sign = 1.0

    adaptive_start_t = (
        time.monotonic()
    )

    window_id = (
        window_id_start
    )

    piezo_up = (
        piezo_up_start
    )

    windows = []
    raw_rows = []

    while True:

        adaptive_elapsed = (
            time.monotonic()
            - adaptive_start_t
        )

        if (
            adaptive_elapsed
            >= ADAPTIVE_MAX_TIME_S
        ):

            return {
                "success": False,

                "reason":
                    "adaptive_timeout",

                "windows":
                    windows,

                "raw":
                    raw_rows,

                "window_id":
                    window_id,

                "piezo_up":
                    piezo_up,

                "best_amplitude":
                    best_amplitude,

                "best_p1":
                    best_p1,

                "best_p2":
                    best_p2,

                "best_time_s":
                    best_time_s,
            }

        direction_rad = (
            math.radians(
                direction_deg
            )
        )

        dx = math.cos(
            direction_rad
        )

        dy = math.sin(
            direction_rad
        )

        window_id += 1

        row, samples = (
            run_motion_window(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                direction_p1=dx,
                direction_p2=dy,

                speed_deg_s=
                    ADAPTIVE_SPEED_DEG_S,

                piezo_up=
                    piezo_up,

                phase=
                    "ADAPTIVE",

                seed_id=
                    seed_id,

                seed_name=
                    seed_name,

                window_id=
                    window_id,

                algorithm_start_t=
                    algorithm_start_t,
            )
        )

        piezo_up = (
            not piezo_up
        )

        windows.append(row)
        raw_rows.extend(samples)

        print_window(row)

        amplitude = (
            row["diff_amplitude_v"]
        )

        # ====================================================
        # NOWE MAKSIMUM
        # ====================================================

        if amplitude > best_amplitude:

            best_amplitude = amplitude

            best_p1 = row[
                "p1_mean_deg"
            ]

            best_p2 = row[
                "p2_mean_deg"
            ]

            best_time_s = row[
                "algorithm_time_s"
            ]

            departure_count = 0

            print(
                f"   >>> nowe best: "
                f"{best_amplitude:.6f} V"
            )

        # ====================================================
        # SPRAWDZENIE ODEJŚCIA
        # ====================================================

        if target_reached:

            departure = (
                best_amplitude
                - amplitude
            )

            if (
                departure
                > MAXIMUM_DEPARTURE_V
            ):

                departure_count += 1

                print(
                    f"   >>> odejście od best: "
                    f"{departure:.6f} V | "
                    f"{departure_count}/"
                    f"{MAX_DEPARTURE_WINDOWS}"
                )

            else:

                departure_count = 0

            if (
                departure_count
                >= MAX_DEPARTURE_WINDOWS
            ):

                return {
                    "success": True,

                    "reason":
                        "maximum_found",

                    "windows":
                        windows,

                    "raw":
                        raw_rows,

                    "window_id":
                        window_id,

                    "piezo_up":
                        piezo_up,

                    "best_amplitude":
                        best_amplitude,

                    "best_p1":
                        best_p1,

                    "best_p2":
                        best_p2,

                    "best_time_s":
                        best_time_s,
                }

        # ====================================================
        # ADAPTACJA KIERUNKU
        # ====================================================

        if (
            amplitude
            < previous_amplitude
        ):

            direction_deg += (
                rotation_sign
                * ADAPTIVE_DIRECTION_STEP_DEG
            )

            rotation_sign *= -1.0

        previous_amplitude = (
            amplitude
        )

        direction_deg %= 360.0

        # ====================================================
        # GRANICE
        # ====================================================

        p1, p2 = (
            read_both_angles(mpc)
        )

        margin = (
            ADAPTIVE_SPEED_DEG_S
            * HALF_CYCLE_TIME_S
            + 2.0
        )

        if (
            p1 <= MPC_MIN_DEG + margin
            or
            p1 >= MPC_MAX_DEG - margin
            or
            p2 <= MPC_MIN_DEG + margin
            or
            p2 >= MPC_MAX_DEG - margin
        ):

            direction_deg += 135.0
            direction_deg %= 360.0


# ============================================================
# MULTISTART
# ============================================================

def run_multistart_hybrid(
    mpc,
    mdt,
    ads,
):

    algorithm_start_t = (
        time.monotonic()
    )

    all_windows = []
    all_raw = []

    attempts = []

    window_id = 0
    piezo_up = True

    global_best = -np.inf

    global_best_p1 = float("nan")
    global_best_p2 = float("nan")
    global_best_time = float("nan")

    # ========================================================
    # KOLEJNE STARTY
    # ========================================================

    for seed_id, seed in enumerate(
        START_POINTS,
        start=1,
    ):

        print()
        print("=" * 80)

        print(
            f"START {seed_id}/"
            f"{len(START_POINTS)}"
        )

        print(
            f"{seed['name']}"
        )

        print(
            f"P1={seed['p1']:.1f}°, "
            f"P2={seed['p2']:.1f}°"
        )

        print("=" * 80)

        # ====================================================
        # PRZEJAZD DO NOWEGO STARTU
        # ====================================================

        actual_p1, actual_p2 = (
            move_both_and_wait(
                mpc,
                seed["p1"],
                seed["p2"],
            )
        )

        print(
            f"Pozycja rzeczywista: "
            f"P1={actual_p1:.2f}°, "
            f"P2={actual_p2:.2f}°"
        )

        fast_set_voltage(
            mdt,
            PIEZO_MIN_V,
        )

        time.sleep(
            PIEZO_SETTLE_S
        )

        discard_ads_samples(
            ads
        )

        attempt_start_t = (
            time.monotonic()
        )

        # ====================================================
        # COORDINATE
        # ====================================================

        coordinate_result = (
            run_coordinate_phase(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                seed_id=
                    seed_id,

                seed_name=
                    seed["name"],

                algorithm_start_t=
                    algorithm_start_t,

                window_id_start=
                    window_id,

                piezo_up_start=
                    piezo_up,
            )
        )

        window_id = (
            coordinate_result[
                "window_id"
            ]
        )

        piezo_up = (
            coordinate_result[
                "piezo_up"
            ]
        )

        all_windows.extend(
            coordinate_result[
                "windows"
            ]
        )

        all_raw.extend(
            coordinate_result[
                "raw"
            ]
        )

        # ====================================================
        # GLOBAL BEST Z COORDINATE
        # ====================================================

        if (
            coordinate_result[
                "best_amplitude"
            ]
            > global_best
        ):

            global_best = (
                coordinate_result[
                    "best_amplitude"
                ]
            )

            global_best_p1 = (
                coordinate_result[
                    "best_p1"
                ]
            )

            global_best_p2 = (
                coordinate_result[
                    "best_p2"
                ]
            )

        # ====================================================
        # TIMEOUT COORDINATE
        # ====================================================

        if (
            not coordinate_result[
                "success"
            ]
        ):

            print()

            print(
                f"Coordinate nie osiągnął "
                f"{COORDINATE_TARGET_V:.2f} V "
                f"w {COORDINATE_MAX_TIME_S:.0f} s."
            )

            print(
                f"Najlepsze w tej próbie: "
                f"{coordinate_result['best_amplitude']:.6f} V"
            )

            print(
                "Przechodzę do następnego startu."
            )

            attempts.append(
                {
                    "seed_id":
                        seed_id,

                    "seed_name":
                        seed["name"],

                    "seed_p1_deg":
                        seed["p1"],

                    "seed_p2_deg":
                        seed["p2"],

                    "result":
                        "coordinate_timeout",

                    "best_A_D_v":
                        coordinate_result[
                            "best_amplitude"
                        ],

                    "best_p1_deg":
                        coordinate_result[
                            "best_p1"
                        ],

                    "best_p2_deg":
                        coordinate_result[
                            "best_p2"
                        ],

                    "attempt_time_s":
                        time.monotonic()
                        - attempt_start_t,
                }
            )

            continue

        # ====================================================
        # PRZEJŚCIE DO ADAPTIVE
        # ====================================================

        print()
        print("=" * 70)

        print(
            "COORDINATE -> ADAPTIVE"
        )

        print(
            f"A_D = "
            f"{coordinate_result['amplitude']:.6f} V"
        )

        print(
            f"P1 = "
            f"{coordinate_result['p1']:.2f}°"
        )

        print(
            f"P2 = "
            f"{coordinate_result['p2']:.2f}°"
        )

        print(
            f"5°/s -> 2°/s"
        )

        print(
            "Adaptive jedzie dalej przez maksimum."
        )

        print("=" * 70)
        print()

        # ====================================================
        # ADAPTIVE
        # ====================================================

        adaptive_result = (
            run_adaptive_phase(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                seed_id=
                    seed_id,

                seed_name=
                    seed["name"],

                algorithm_start_t=
                    algorithm_start_t,

                window_id_start=
                    window_id,

                piezo_up_start=
                    piezo_up,

                initial_direction_index=
                    coordinate_result[
                        "direction_index"
                    ],

                starting_amplitude=
                    coordinate_result[
                        "amplitude"
                    ],
            )
        )

        window_id = (
            adaptive_result[
                "window_id"
            ]
        )

        piezo_up = (
            adaptive_result[
                "piezo_up"
            ]
        )

        all_windows.extend(
            adaptive_result[
                "windows"
            ]
        )

        all_raw.extend(
            adaptive_result[
                "raw"
            ]
        )

        # ====================================================
        # GLOBAL BEST
        # ====================================================

        if (
            adaptive_result[
                "best_amplitude"
            ]
            > global_best
        ):

            global_best = (
                adaptive_result[
                    "best_amplitude"
                ]
            )

            global_best_p1 = (
                adaptive_result[
                    "best_p1"
                ]
            )

            global_best_p2 = (
                adaptive_result[
                    "best_p2"
                ]
            )

            global_best_time = (
                adaptive_result[
                    "best_time_s"
                ]
            )

        attempts.append(
            {
                "seed_id":
                    seed_id,

                "seed_name":
                    seed["name"],

                "seed_p1_deg":
                    seed["p1"],

                "seed_p2_deg":
                    seed["p2"],

                "result":
                    adaptive_result[
                        "reason"
                    ],

                "best_A_D_v":
                    adaptive_result[
                        "best_amplitude"
                    ],

                "best_p1_deg":
                    adaptive_result[
                        "best_p1"
                    ],

                "best_p2_deg":
                    adaptive_result[
                        "best_p2"
                    ],

                "attempt_time_s":
                    time.monotonic()
                    - attempt_start_t,
            }
        )

        # ====================================================
        # MAKSIMUM POTWIERDZONE
        # ====================================================

        if (
            adaptive_result[
                "success"
            ]
        ):

            total_time_s = (
                time.monotonic()
                - algorithm_start_t
            )

            summary = {

                "stop_reason":
                    "maximum_found",

                "successful_seed_id":
                    seed_id,

                "successful_seed_name":
                    seed["name"],

                "best_A_D_v":
                    adaptive_result[
                        "best_amplitude"
                    ],

                "best_p1_deg":
                    adaptive_result[
                        "best_p1"
                    ],

                "best_p2_deg":
                    adaptive_result[
                        "best_p2"
                    ],

                "best_measurement_time_s":
                    adaptive_result[
                        "best_time_s"
                    ],

                "total_time_s":
                    total_time_s,

                "windows_total":
                    len(all_windows),

                "starts_used":
                    seed_id,
            }

            return (
                all_windows,
                all_raw,
                attempts,
                summary,
            )

        # ====================================================
        # ADAPTIVE TIMEOUT
        # ====================================================

        print()

        print(
            f"Adaptive nie potwierdził maksimum "
            f"w {ADAPTIVE_MAX_TIME_S:.0f} s."
        )

        print(
            f"Najlepsze A_D: "
            f"{adaptive_result['best_amplitude']:.6f} V"
        )

        print(
            "Przechodzę do następnego startu."
        )

    # ========================================================
    # KONIEC WSZYSTKICH STARTÓW
    # ========================================================

    total_time_s = (
        time.monotonic()
        - algorithm_start_t
    )

    # Szukamy dokładnego globalnego best także z wszystkich okien.
    if all_windows:

        best_row = max(
            all_windows,
            key=lambda row:
                row["diff_amplitude_v"]
        )

        if (
            best_row["diff_amplitude_v"]
            > global_best
        ):

            global_best = (
                best_row[
                    "diff_amplitude_v"
                ]
            )

            global_best_p1 = (
                best_row[
                    "p1_mean_deg"
                ]
            )

            global_best_p2 = (
                best_row[
                    "p2_mean_deg"
                ]
            )

            global_best_time = (
                best_row[
                    "algorithm_time_s"
                ]
            )

    summary = {

        "stop_reason":
            "all_start_points_exhausted",

        "successful_seed_id":
            "",

        "successful_seed_name":
            "",

        "best_A_D_v":
            global_best,

        "best_p1_deg":
            global_best_p1,

        "best_p2_deg":
            global_best_p2,

        "best_measurement_time_s":
            global_best_time,

        "total_time_s":
            total_time_s,

        "windows_total":
            len(all_windows),

        "starts_used":
            len(START_POINTS),
    }

    return (
        all_windows,
        all_raw,
        attempts,
        summary,
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
            "TEST HYBRYDY MULTISTART - PRÓG 0.45 V"
        )

        print("=" * 80)

        print(
            f"Coordinate: "
            f"{COORDINATE_SPEED_DEG_S:.1f}°/s "
            f"do {COORDINATE_TARGET_V:.2f} V"
        )

        print(
            f"Coordinate timeout/start: "
            f"{COORDINATE_MAX_TIME_S:.0f} s"
        )

        print(
            f"Adaptive: "
            f"{ADAPTIVE_SPEED_DEG_S:.1f}°/s"
        )

        print(
            f"Adaptive timeout: "
            f"{ADAPTIVE_MAX_TIME_S:.0f} s"
        )

        print(
            f"STOP po spadku > "
            f"{MAXIMUM_DEPARTURE_V:.3f} V "
            f"przez "
            f"{MAX_DEPARTURE_WINDOWS} okna"
        )

        print()

        print("Punkty startowe:")

        for i, seed in enumerate(
            START_POINTS,
            start=1,
        ):

            print(
                f"{i}. "
                f"P1={seed['p1']:.1f}°, "
                f"P2={seed['p2']:.1f}° "
                f"({seed['name']})"
            )

        print()

        # ====================================================
        # CONNECT MPC
        # ====================================================

        print("Łączenie MPC220...")

        mpc = MPC220Driver(
            MPC_PORT
        )

        mpc.connect()

        print("MPC220 OK")
        print()

        # ====================================================
        # CONNECT MDT
        # ====================================================

        print("Łączenie MDT694B...")

        mdt = MDT694BDriver(
            MDT_PORT
        )

        mdt.connect()

        print("MDT694B OK")
        print()

        # ====================================================
        # CONNECT ADS
        # ====================================================

        print("Łączenie ADS1263...")

        ads = connect_ads()

        print("ADS1263 OK")
        print()

        # ====================================================
        # CONDITIONING
        # ====================================================

        condition_piezo(
            mdt
        )

        # ====================================================
        # TEST
        # ====================================================

        (
            windows,
            raw,
            attempts,
            summary,
        ) = run_multistart_hybrid(
            mpc,
            mdt,
            ads,
        )

        # ====================================================
        # SAVE
        # ====================================================

        save_csv(
            OUTPUT_DIR
            / "hybrid_windows.csv",
            windows,
        )

        save_csv(
            OUTPUT_DIR
            / "hybrid_raw.csv",
            raw,
        )

        save_csv(
            OUTPUT_DIR
            / "hybrid_attempts.csv",
            attempts,
        )

        save_csv(
            OUTPUT_DIR
            / "hybrid_summary.csv",
            [summary],
        )

        # ====================================================
        # FINAL
        # ====================================================

        print()
        print("=" * 80)

        print(
            "WYNIK TESTU 0.45 V"
        )

        print("=" * 80)

        print(
            f"STOP: "
            f"{summary['stop_reason']}"
        )

        print(
            f"Najlepsze A_D: "
            f"{summary['best_A_D_v']:.6f} V"
        )

        print(
            f"Najlepsza pozycja: "
            f"P1={summary['best_p1_deg']:.2f}°, "
            f"P2={summary['best_p2_deg']:.2f}°"
        )

        print(
            f"Najlepszy pomiar po: "
            f"{summary['best_measurement_time_s']:.2f} s"
        )

        print(
            f"Całkowity czas: "
            f"{summary['total_time_s']:.2f} s"
        )

        print(
            f"Użyte starty: "
            f"{summary['starts_used']}"
        )

        print(
            f"Liczba okien: "
            f"{summary['windows_total']}"
        )

        print()

        print(
            "Wyniki zapisano w:"
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

        close_ads(
            ads
        )

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