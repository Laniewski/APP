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
    / "test_ciaglych_algorytmow_polaryzacji"
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
# MPC220
# ============================================================

MPC_MIN_DEG = 1.0
MPC_MAX_DEG = 160.0

START_P1 = 80.0
START_P2 = 80.0

MPC_COMMAND_INTERVAL_S = 0.12
MPC_SETTLE_S = 0.50


# ============================================================
# PIEZO
# ============================================================

PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0

PIEZO_SPEED_V_S = 20.0

PIEZO_COMMAND_INTERVAL_S = 0.05
PIEZO_SETTLE_S = 0.30

HALF_CYCLE_TIME_S = (
    PIEZO_MAX_V
    - PIEZO_MIN_V
) / PIEZO_SPEED_V_S


# ============================================================
# ADS1263
# ============================================================

SAMPLE_INTERVAL_S = 0.20


# ============================================================
# REFERENCJA - CONTINUOUS RASTER
# ============================================================

RUN_REFERENCE = True

# 9 poziomów P2.
# P1 natomiast jedzie CAŁKOWICIE CIĄGLE.
REFERENCE_ROWS_P2 = [
    1.0,
    21.0,
    41.0,
    61.0,
    81.0,
    101.0,
    121.0,
    141.0,
    160.0,
]

# Pierwszy test robimy bezpiecznie i dokładnie.
REFERENCE_P1_SPEED_DEG_S = 1.0


# ============================================================
# ALGORYTMY
# ============================================================

RUN_SPIRAL = True
RUN_ADAPTIVE = True
RUN_COORDINATE = True

TARGET_AMPLITUDE_V = 0.400

MAX_ALGORITHM_TIME_S = 240.0

MIN_IMPROVEMENT_V = 0.005

CONFIRM_TARGET = True
CONFIRM_TOLERANCE_V = 0.10


# ============================================================
# SPIRALA
# ============================================================

SPIRAL_CENTER_P1 = START_P1
SPIRAL_CENTER_P2 = START_P2

SPIRAL_MAX_RADIUS_DEG = 78.0
SPIRAL_TURNS = 3.0

SPIRAL_PATH_SPEED_DEG_S = 1.0


# ============================================================
# ALGORYTM ADAPTACYJNY
# ============================================================

ADAPTIVE_RADIUS_DEG = 6.0
ADAPTIVE_MIN_RADIUS_DEG = 2.0

ADAPTIVE_CENTER_STEP_DEG = 5.0
ADAPTIVE_MIN_CENTER_STEP_DEG = 1.0

# 4 półcykle piezo = jeden pełny obieg
ADAPTIVE_WINDOWS_PER_ORBIT = 4


# ============================================================
# COORDINATE SEARCH
# ============================================================

COORDINATE_SPEEDS_DEG_S = [
    1.0,
    0.5,
    0.25,
]

COORDINATE_MAX_WINDOWS_DIRECTION = 10

FALLING_WINDOWS_TO_REVERSE = 2


# ============================================================
# STOPIEŃ PRZESZUKANIA
# ============================================================

SEARCH_GRID_SIZE = 9


# ============================================================
# POMOCNICZE
# ============================================================

def clamp(value, minimum, maximum):

    return max(
        minimum,
        min(maximum, value),
    )


def read_paddle_angle(mpc, paddle):

    raw = mpc.read_position_units(
        paddle
    )

    return raw_position_to_angle(
        raw
    )


def send_mpc_target(
    mpc,
    p1,
    p2,
):

    p1 = clamp(
        p1,
        MPC_MIN_DEG,
        MPC_MAX_DEG,
    )

    p2 = clamp(
        p2,
        MPC_MIN_DEG,
        MPC_MAX_DEG,
    )

    # Obie komendy prawie jednocześnie.
    # Bez wait_until_stopped pomiędzy nimi.

    mpc.move_absolute_units(
        1,
        angle_to_command(p1),
    )

    mpc.move_absolute_units(
        2,
        angle_to_command(p2),
    )


def move_both_and_wait(
    mpc,
    p1,
    p2,
):

    send_mpc_target(
        mpc,
        p1,
        p2,
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    time.sleep(
        MPC_SETTLE_S
    )

    actual1 = read_paddle_angle(
        mpc,
        1,
    )

    actual2 = read_paddle_angle(
        mpc,
        2,
    )

    return (
        actual1,
        actual2,
    )


def fast_set_voltage(
    mdt,
    voltage,
):

    mdt._send_command(
        f"xvoltage={voltage:.3f}"
    )


def controlled_piezo_ramp(
    mdt,
    start_v,
    end_v,
):

    start_v = float(start_v)
    end_v = float(end_v)

    delta = (
        end_v
        - start_v
    )

    if abs(delta) < 0.001:
        return

    duration = (
        abs(delta)
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
            + delta * progress
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


# ============================================================
# ADS - POPRAWIONA INICJALIZACJA
# ============================================================

def connect_ads():

    print()
    print("Uruchamianie ADS1263...")

    ads = ADS1263Driver()

    # To było pominięte w poprzedniej wersji.
    if hasattr(ads, "connect"):

        print("ADS1263: connect()...")

        ads.connect()

    else:

        print(
            "ADS1263Driver nie posiada connect(). "
            "Zakładam inicjalizację w konstruktorze."
        )

    print(
        "ADS1263: start_measurement()..."
    )

    ads.start_measurement()

    print("ADS1263 OK")

    return ads


def close_ads(ads):

    if ads is None:
        return

    try:

        ads.stop_measurement()

    except Exception as e:

        print(
            f"ADS stop_measurement: {e}"
        )

    if hasattr(ads, "disconnect"):

        try:

            ads.disconnect()

        except Exception as e:

            print(
                f"ADS disconnect: {e}"
            )

    elif hasattr(ads, "close"):

        try:

            ads.close()

        except Exception as e:

            print(
                f"ADS close: {e}"
            )


# ============================================================
# METRYKI POLARYZACJI
# ============================================================

def calculate_metrics(samples):

    if len(samples) < 5:

        return {
            "diff_amplitude_v":
                float("nan"),

            "score":
                float("nan"),

            "in0_amplitude_v":
                float("nan"),

            "in1_amplitude_v":
                float("nan"),

            "mean_sum_v":
                float("nan"),

            "samples":
                len(samples),
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

    diff = (
        in0
        - in1
    )

    total = (
        in0
        + in1
    )

    diff_amplitude = (
        np.percentile(diff, 95)
        -
        np.percentile(diff, 5)
    ) / 2.0

    in0_amplitude = (
        np.percentile(in0, 95)
        -
        np.percentile(in0, 5)
    ) / 2.0

    in1_amplitude = (
        np.percentile(in1, 95)
        -
        np.percentile(in1, 5)
    ) / 2.0

    valid = (
        np.abs(total)
        > 1e-9
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

        "in0_amplitude_v":
            float(in0_amplitude),

        "in1_amplitude_v":
            float(in1_amplitude),

        "mean_sum_v":
            float(np.mean(total)),

        "samples":
            len(samples),
    }


# ============================================================
# TRACKER TRAJEKTORII
# ============================================================

class PathTracker:

    def __init__(self):

        self.last_point = None

        self.path_length_deg = 0.0

        self.visited_cells = set()

        self.rows = []


    def register(
        self,
        p1,
        p2,
        time_s=None,
    ):

        p1 = float(
            clamp(
                p1,
                MPC_MIN_DEG,
                MPC_MAX_DEG,
            )
        )

        p2 = float(
            clamp(
                p2,
                MPC_MIN_DEG,
                MPC_MAX_DEG,
            )
        )

        if self.last_point is not None:

            dp1 = (
                p1
                - self.last_point[0]
            )

            dp2 = (
                p2
                - self.last_point[1]
            )

            self.path_length_deg += (
                math.sqrt(
                    dp1**2
                    + dp2**2
                )
            )

        self.last_point = (
            p1,
            p2,
        )

        # --------------------------------------------
        # stopień przeszukania
        # --------------------------------------------

        span = (
            MPC_MAX_DEG
            - MPC_MIN_DEG
        )

        i = int(
            (
                p1
                - MPC_MIN_DEG
            )
            /
            span
            *
            SEARCH_GRID_SIZE
        )

        j = int(
            (
                p2
                - MPC_MIN_DEG
            )
            /
            span
            *
            SEARCH_GRID_SIZE
        )

        i = max(
            0,
            min(
                SEARCH_GRID_SIZE - 1,
                i,
            ),
        )

        j = max(
            0,
            min(
                SEARCH_GRID_SIZE - 1,
                j,
            ),
        )

        self.visited_cells.add(
            (
                i,
                j,
            )
        )

        self.rows.append(
            {
                "time_s":
                    time_s,

                "p1_deg":
                    p1,

                "p2_deg":
                    p2,
            }
        )


    @property
    def search_degree_pct(self):

        total = (
            SEARCH_GRID_SIZE
            * SEARCH_GRID_SIZE
        )

        return (
            len(
                self.visited_cells
            )
            /
            total
            *
            100.0
        )


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
# CIĄGŁE OKNO POMIAROWE = PÓŁ CYKLU PIEZO
# ============================================================

def run_halfcycle_window(
    mpc,
    mdt,
    ads,
    path_function,
    piezo_start_v,
    piezo_end_v,
    tracker=None,
    global_start_time=None,
    raw_rows=None,
):

    samples = []

    start_t = time.monotonic()

    next_mpc = start_t
    next_piezo = start_t
    next_sample = start_t

    last_p1 = None
    last_p2 = None

    last_voltage = (
        piezo_start_v
    )

    while True:

        now = time.monotonic()

        elapsed = (
            now
            - start_t
        )

        progress = min(
            elapsed
            / HALF_CYCLE_TIME_S,
            1.0,
        )

        # ------------------------------------------------
        # MPC
        # ------------------------------------------------

        if now >= next_mpc:

            p1, p2 = (
                path_function(
                    progress
                )
            )

            p1 = clamp(
                p1,
                MPC_MIN_DEG,
                MPC_MAX_DEG,
            )

            p2 = clamp(
                p2,
                MPC_MIN_DEG,
                MPC_MAX_DEG,
            )

            send_mpc_target(
                mpc,
                p1,
                p2,
            )

            last_p1 = (
                p1
            )

            last_p2 = (
                p2
            )

            if tracker is not None:

                if global_start_time is None:

                    tracker_time = (
                        elapsed
                    )

                else:

                    tracker_time = (
                        now
                        - global_start_time
                    )

                tracker.register(
                    p1,
                    p2,
                    tracker_time,
                )

            next_mpc += (
                MPC_COMMAND_INTERVAL_S
            )

        # ------------------------------------------------
        # PIEZO
        # ------------------------------------------------

        if now >= next_piezo:

            voltage = (
                piezo_start_v
                +
                (
                    piezo_end_v
                    - piezo_start_v
                )
                * progress
            )

            fast_set_voltage(
                mdt,
                voltage,
            )

            last_voltage = (
                voltage
            )

            next_piezo += (
                PIEZO_COMMAND_INTERVAL_S
            )

        # ------------------------------------------------
        # ADS
        # ------------------------------------------------

        if now >= next_sample:

            in0_v, in1_v = (
                ads.read_sample()
            )

            if last_p1 is None:

                last_p1, last_p2 = (
                    path_function(
                        progress
                    )
                )

            sample = {
                "time_local_s":
                    elapsed,

                "p1_target_deg":
                    float(last_p1),

                "p2_target_deg":
                    float(last_p2),

                "piezo_v":
                    float(last_voltage),

                "in0_v":
                    float(in0_v),

                "in1_v":
                    float(in1_v),
            }

            samples.append(
                sample
            )

            if raw_rows is not None:

                if global_start_time is None:

                    global_time = (
                        elapsed
                    )

                else:

                    global_time = (
                        now
                        - global_start_time
                    )

                raw_rows.append(
                    {
                        "time_s":
                            global_time,

                        "p1_target_deg":
                            float(
                                last_p1
                            ),

                        "p2_target_deg":
                            float(
                                last_p2
                            ),

                        "piezo_v":
                            float(
                                last_voltage
                            ),

                        "in0_v":
                            float(
                                in0_v
                            ),

                        "in1_v":
                            float(
                                in1_v
                            ),
                    }
                )

            next_sample += (
                SAMPLE_INTERVAL_S
            )

        if progress >= 1.0:
            break

        time.sleep(
            0.001
        )

    final_p1, final_p2 = (
        path_function(
            1.0
        )
    )

    send_mpc_target(
        mpc,
        final_p1,
        final_p2,
    )

    if tracker is not None:

        if global_start_time is None:

            tracker_time = (
                time.monotonic()
                - start_t
            )

        else:

            tracker_time = (
                time.monotonic()
                - global_start_time
            )

        tracker.register(
            final_p1,
            final_p2,
            tracker_time,
        )

    metrics = (
        calculate_metrics(
            samples
        )
    )

    mean_p1 = float(
        np.mean(
            [
                s[
                    "p1_target_deg"
                ]
                for s
                in samples
            ]
        )
    )

    mean_p2 = float(
        np.mean(
            [
                s[
                    "p2_target_deg"
                ]
                for s
                in samples
            ]
        )
    )

    p1_min = float(
        min(
            s[
                "p1_target_deg"
            ]
            for s
            in samples
        )
    )

    p1_max = float(
        max(
            s[
                "p1_target_deg"
            ]
            for s
            in samples
        )
    )

    p2_min = float(
        min(
            s[
                "p2_target_deg"
            ]
            for s
            in samples
        )
    )

    p2_max = float(
        max(
            s[
                "p2_target_deg"
            ]
            for s
            in samples
        )
    )

    return {
        **metrics,

        "mean_p1_deg":
            mean_p1,

        "mean_p2_deg":
            mean_p2,

        "p1_min_deg":
            p1_min,

        "p1_max_deg":
            p1_max,

        "p2_min_deg":
            p2_min,

        "p2_max_deg":
            p2_max,

        "end_p1_deg":
            float(
                final_p1
            ),

        "end_p2_deg":
            float(
                final_p2
            ),

        "piezo_direction":
            (
                "up"
                if piezo_end_v
                >
                piezo_start_v
                else "down"
            ),
    }


# ============================================================
# POTWIERDZENIE STACJONARNE
# ============================================================

def stationary_confirmation(
    mpc,
    mdt,
    ads,
    p1,
    p2,
):

    print(
        f"Potwierdzenie stacjonarne "
        f"({p1:.2f}°, {p2:.2f}°)..."
    )

    move_both_and_wait(
        mpc,
        p1,
        p2,
    )

    controlled_piezo_ramp(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    def fixed_path(_):

        return (
            p1,
            p2,
        )

    result = (
        run_halfcycle_window(
            mpc,
            mdt,
            ads,
            fixed_path,
            PIEZO_MIN_V,
            PIEZO_MAX_V,
        )
    )

    controlled_piezo_ramp(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    return result


# ============================================================
# RESET SYSTEMU
# ============================================================

def reset_system(
    mpc,
    mdt,
):

    print()
    print(
        f"Reset do "
        f"({START_P1:.1f}°, "
        f"{START_P2:.1f}°)"
    )

    move_both_and_wait(
        mpc,
        START_P1,
        START_P2,
    )

    # Nie zakładamy poprawnego read_voltage().
    # Po prostu łagodnie wymuszamy powrót.

    try:

        current_v = float(
            mdt.read_voltage()
        )

    except Exception:

        current_v = (
            PIEZO_MAX_V
        )

    controlled_piezo_ramp(
        mdt,
        current_v,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )


# ============================================================
# REFERENCJA
# ============================================================

def run_reference_scan(
    mpc,
    mdt,
    ads,
):

    print()
    print("=" * 80)
    print(
        "REFERENCJA: CIĄGŁY RASTER"
    )
    print("=" * 80)

    print(
        f"P1: "
        f"{MPC_MIN_DEG:.1f}° "
        f"<-> "
        f"{MPC_MAX_DEG:.1f}°"
    )

    print(
        f"Prędkość P1: "
        f"{REFERENCE_P1_SPEED_DEG_S:.2f}°/s"
    )

    print(
        f"Liczba linii P2: "
        f"{len(REFERENCE_ROWS_P2)}"
    )

    print(
        f"Jedno okno A_D: "
        f"{HALF_CYCLE_TIME_S:.2f} s"
    )

    print(
        f"Rozdzielczość wzdłuż P1: "
        f"około "
        f"{REFERENCE_P1_SPEED_DEG_S * HALF_CYCLE_TIME_S:.2f}°"
    )

    raw_rows = []
    window_rows = []

    scan_start = (
        time.monotonic()
    )

    # Piezo startuje od 80 V.

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    piezo_up = True

    window_id = 0

    for row_index, p2 in enumerate(
        REFERENCE_ROWS_P2
    ):

        if row_index % 2 == 0:

            row_start = (
                MPC_MIN_DEG
            )

            row_end = (
                MPC_MAX_DEG
            )

        else:

            row_start = (
                MPC_MAX_DEG
            )

            row_end = (
                MPC_MIN_DEG
            )

        print()
        print(
            f"Linia "
            f"{row_index + 1}/"
            f"{len(REFERENCE_ROWS_P2)}"
        )

        print(
            f"P2 = {p2:.1f}°"
        )

        print(
            f"P1: "
            f"{row_start:.1f}° "
            f"-> "
            f"{row_end:.1f}°"
        )

        move_both_and_wait(
            mpc,
            row_start,
            p2,
        )

        current_p1 = (
            row_start
        )

        direction = (
            1.0
            if row_end > row_start
            else -1.0
        )

        while True:

            remaining = abs(
                row_end
                - current_p1
            )

            if remaining < 0.001:
                break

            distance_this_window = (
                REFERENCE_P1_SPEED_DEG_S
                *
                HALF_CYCLE_TIME_S
            )

            distance_this_window = min(
                distance_this_window,
                remaining,
            )

            next_p1 = (
                current_p1
                +
                direction
                * distance_this_window
            )

            start_p1 = (
                current_p1
            )

            end_p1 = (
                next_p1
            )

            def path_function(
                u,
                start_p1=start_p1,
                end_p1=end_p1,
                p2=p2,
            ):

                p1 = (
                    start_p1
                    +
                    (
                        end_p1
                        - start_p1
                    )
                    * u
                )

                return (
                    p1,
                    p2,
                )

            if piezo_up:

                piezo_start = (
                    PIEZO_MIN_V
                )

                piezo_end = (
                    PIEZO_MAX_V
                )

            else:

                piezo_start = (
                    PIEZO_MAX_V
                )

                piezo_end = (
                    PIEZO_MIN_V
                )

            result = (
                run_halfcycle_window(
                    mpc,
                    mdt,
                    ads,
                    path_function,
                    piezo_start,
                    piezo_end,
                    tracker=None,
                    global_start_time=
                        scan_start,
                    raw_rows=
                        raw_rows,
                )
            )

            piezo_up = (
                not piezo_up
            )

            window_id += 1

            window_row = {
                "window_id":
                    window_id,

                "row_id":
                    row_index + 1,

                "p1_mean_deg":
                    result[
                        "mean_p1_deg"
                    ],

                "p2_mean_deg":
                    result[
                        "mean_p2_deg"
                    ],

                "p1_min_deg":
                    result[
                        "p1_min_deg"
                    ],

                "p1_max_deg":
                    result[
                        "p1_max_deg"
                    ],

                "p2_min_deg":
                    result[
                        "p2_min_deg"
                    ],

                "p2_max_deg":
                    result[
                        "p2_max_deg"
                    ],

                "diff_amplitude_v":
                    result[
                        "diff_amplitude_v"
                    ],

                "score":
                    result[
                        "score"
                    ],

                "mean_sum_v":
                    result[
                        "mean_sum_v"
                    ],

                "samples":
                    result[
                        "samples"
                    ],

                "piezo_direction":
                    result[
                        "piezo_direction"
                    ],
            }

            window_rows.append(
                window_row
            )

            print(
                f"  #{window_id:03d} | "
                f"P1={result['mean_p1_deg']:7.2f}° | "
                f"P2={result['mean_p2_deg']:7.2f}° | "
                f"A_D={result['diff_amplitude_v']:.4f} V"
            )

            current_p1 = (
                next_p1
            )

    total_time = (
        time.monotonic()
        - scan_start
    )

    save_csv(
        OUTPUT_DIR
        / "reference_windows.csv",
        window_rows,
    )

    save_csv(
        OUTPUT_DIR
        / "reference_raw.csv",
        raw_rows,
    )

    valid_rows = [
        r
        for r
        in window_rows
        if not math.isnan(
            r[
                "diff_amplitude_v"
            ]
        )
    ]

    best = max(
        valid_rows,
        key=lambda r:
            r[
                "diff_amplitude_v"
            ],
    )

    minimum = min(
        valid_rows,
        key=lambda r:
            r[
                "diff_amplitude_v"
            ],
    )

    print()
    print("=" * 80)
    print(
        "REFERENCJA GOTOWA"
    )
    print("=" * 80)

    print(
        f"Okna: "
        f"{len(window_rows)}"
    )

    print(
        f"Czas: "
        f"{total_time:.1f} s"
    )

    print(
        f"MAX A_D = "
        f"{best['diff_amplitude_v']:.6f} V"
    )

    print(
        f"około "
        f"P1={best['p1_mean_deg']:.2f}°, "
        f"P2={best['p2_mean_deg']:.2f}°"
    )

    print(
        f"MIN A_D = "
        f"{minimum['diff_amplitude_v']:.6f} V"
    )

    return (
        window_rows,
        best,
        total_time,
    )


# ============================================================
# KONTEKST ALGORYTMU
# ============================================================

class AlgorithmContext:

    def __init__(
        self,
        name,
        mpc,
        mdt,
        ads,
        reference_best,
    ):

        self.name = (
            name
        )

        self.mpc = (
            mpc
        )

        self.mdt = (
            mdt
        )

        self.ads = (
            ads
        )

        self.reference_best = (
            reference_best
        )

        self.start_time = (
            time.monotonic()
        )

        self.tracker = (
            PathTracker()
        )

        self.raw_rows = []
        self.window_rows = []

        self.window_count = 0

        self.best = None
        self.minimum = None

        self.target_reached = False

        self.confirmations = 0

        self.piezo_up = True


    def elapsed(self):

        return (
            time.monotonic()
            - self.start_time
        )


    def time_finished(self):

        return (
            self.elapsed()
            >= MAX_ALGORITHM_TIME_S
        )


    def evaluate_window(
        self,
        path_function,
        state,
    ):

        if self.piezo_up:

            piezo_start = (
                PIEZO_MIN_V
            )

            piezo_end = (
                PIEZO_MAX_V
            )

        else:

            piezo_start = (
                PIEZO_MAX_V
            )

            piezo_end = (
                PIEZO_MIN_V
            )

        result = (
            run_halfcycle_window(
                self.mpc,
                self.mdt,
                self.ads,
                path_function,
                piezo_start,
                piezo_end,
                tracker=
                    self.tracker,
                global_start_time=
                    self.start_time,
                raw_rows=
                    self.raw_rows,
            )
        )

        self.piezo_up = (
            not self.piezo_up
        )

        self.window_count += 1

        row = {
            "window_id":
                self.window_count,

            "time_s":
                self.elapsed(),

            "state":
                state,

            "p1_mean_deg":
                result[
                    "mean_p1_deg"
                ],

            "p2_mean_deg":
                result[
                    "mean_p2_deg"
                ],

            "p1_min_deg":
                result[
                    "p1_min_deg"
                ],

            "p1_max_deg":
                result[
                    "p1_max_deg"
                ],

            "p2_min_deg":
                result[
                    "p2_min_deg"
                ],

            "p2_max_deg":
                result[
                    "p2_max_deg"
                ],

            "diff_amplitude_v":
                result[
                    "diff_amplitude_v"
                ],

            "score":
                result[
                    "score"
                ],

            "mean_sum_v":
                result[
                    "mean_sum_v"
                ],

            "samples":
                result[
                    "samples"
                ],

            "piezo_direction":
                result[
                    "piezo_direction"
                ],
        }

        self.window_rows.append(
            row
        )

        amp = (
            result[
                "diff_amplitude_v"
            ]
        )

        if (
            self.best is None
            or
            amp
            >
            self.best[
                "diff_amplitude_v"
            ]
        ):

            self.best = {
                **result,
                "time_s":
                    self.elapsed(),
            }

        if (
            self.minimum is None
            or
            amp
            <
            self.minimum[
                "diff_amplitude_v"
            ]
        ):

            self.minimum = {
                **result
            }

        print(
            f"[{self.name}] "
            f"#{self.window_count:02d} | "
            f"P1={result['mean_p1_deg']:7.2f}° | "
            f"P2={result['mean_p2_deg']:7.2f}° | "
            f"A_D={amp:.4f} V | "
            f"best="
            f"{self.best['diff_amplitude_v']:.4f} V"
        )

        # --------------------------------------------
        # potwierdzenie progu
        # --------------------------------------------

        if (
            amp
            >= TARGET_AMPLITUDE_V
        ):

            if not CONFIRM_TARGET:

                self.target_reached = True
                return True

            candidate_p1 = (
                result[
                    "mean_p1_deg"
                ]
            )

            candidate_p2 = (
                result[
                    "mean_p2_deg"
                ]
            )

            self.confirmations += 1

            print(
                "  -> przekroczono próg, "
                "potwierdzam stacjonarnie..."
            )

            confirmation = (
                stationary_confirmation(
                    self.mpc,
                    self.mdt,
                    self.ads,
                    candidate_p1,
                    candidate_p2,
                )
            )

            confirmed_amp = (
                confirmation[
                    "diff_amplitude_v"
                ]
            )

            print(
                f"  -> stacjonarne "
                f"A_D="
                f"{confirmed_amp:.4f} V"
            )

            difference = abs(
                confirmed_amp
                - amp
            )

            if (
                confirmed_amp
                >= TARGET_AMPLITUDE_V
                and
                difference
                <= CONFIRM_TOLERANCE_V
            ):

                print(
                    "  -> PRÓG POTWIERDZONY"
                )

                self.target_reached = True

                # Stacjonarne potwierdzenie może
                # być lepsze od okna ruchomego.

                if (
                    confirmed_amp
                    >
                    self.best[
                        "diff_amplitude_v"
                    ]
                ):

                    self.best = {
                        **confirmation,

                        "mean_p1_deg":
                            candidate_p1,

                        "mean_p2_deg":
                            candidate_p2,

                        "time_s":
                            self.elapsed(),
                    }

                return True

            print(
                "  -> próg NIEPOTWIERDZONY"
            )

        return False


    def save(self):

        save_csv(
            OUTPUT_DIR
            /
            f"{self.name}_windows.csv",
            self.window_rows,
        )

        save_csv(
            OUTPUT_DIR
            /
            f"{self.name}_raw.csv",
            self.raw_rows,
        )

        save_csv(
            OUTPUT_DIR
            /
            f"{self.name}_path.csv",
            self.tracker.rows,
        )


    def summary(self):

        if self.best is None:

            return None

        ref_p1 = (
            self.reference_best[
                "p1_mean_deg"
            ]
        )

        ref_p2 = (
            self.reference_best[
                "p2_mean_deg"
            ]
        )

        ref_amp = (
            self.reference_best[
                "diff_amplitude_v"
            ]
        )

        best_p1 = (
            self.best[
                "mean_p1_deg"
            ]
        )

        best_p2 = (
            self.best[
                "mean_p2_deg"
            ]
        )

        distance = math.sqrt(
            (
                best_p1
                - ref_p1
            )**2
            +
            (
                best_p2
                - ref_p2
            )**2
        )

        return {
            "algorithm":
                self.name,

            "target_reached":
                self.target_reached,

            "time_s":
                self.elapsed(),

            "windows":
                self.window_count,

            "confirmations":
                self.confirmations,

            "max_diff_amplitude_v":
                self.best[
                    "diff_amplitude_v"
                ],

            "min_diff_amplitude_v":
                self.minimum[
                    "diff_amplitude_v"
                ],

            "best_p1_deg":
                best_p1,

            "best_p2_deg":
                best_p2,

            "reference_max_v":
                ref_amp,

            "reference_amp_error_v":
                (
                    ref_amp
                    -
                    self.best[
                        "diff_amplitude_v"
                    ]
                ),

            "distance_from_reference_deg":
                distance,

            "path_length_deg":
                self.tracker.path_length_deg,

            "search_degree_pct":
                self.tracker.search_degree_pct,
        }


# ============================================================
# ALGORYTM 1 - SPIRALA
# ============================================================

def create_spiral_lookup():

    phi = np.linspace(
        0.0,
        2.0
        * math.pi
        * SPIRAL_TURNS,
        20000,
    )

    progress = (
        phi
        /
        phi[-1]
    )

    radius = (
        SPIRAL_MAX_RADIUS_DEG
        * progress
    )

    p1 = (
        SPIRAL_CENTER_P1
        +
        radius
        * np.cos(phi)
    )

    p2 = (
        SPIRAL_CENTER_P2
        +
        radius
        * np.sin(phi)
    )

    p1 = np.clip(
        p1,
        MPC_MIN_DEG,
        MPC_MAX_DEG,
    )

    p2 = np.clip(
        p2,
        MPC_MIN_DEG,
        MPC_MAX_DEG,
    )

    dp1 = np.diff(
        p1
    )

    dp2 = np.diff(
        p2
    )

    ds = np.sqrt(
        dp1**2
        +
        dp2**2
    )

    cumulative = np.concatenate(
        (
            [0.0],
            np.cumsum(ds),
        )
    )

    return (
        cumulative,
        p1,
        p2,
    )


def run_spiral(
    mpc,
    mdt,
    ads,
    reference_best,
):

    print()
    print("=" * 80)
    print(
        "ALGORYTM 1: SPIRALA"
    )
    print("=" * 80)

    reset_system(
        mpc,
        mdt,
    )

    context = (
        AlgorithmContext(
            "spiral",
            mpc,
            mdt,
            ads,
            reference_best,
        )
    )

    cumulative, p1_lookup, p2_lookup = (
        create_spiral_lookup()
    )

    total_length = (
        cumulative[-1]
    )

    distance_per_window = (
        SPIRAL_PATH_SPEED_DEG_S
        *
        HALF_CYCLE_TIME_S
    )

    current_s = 0.0

    while (
        current_s
        <
        total_length
        and
        not context.time_finished()
    ):

        start_s = (
            current_s
        )

        end_s = min(
            current_s
            +
            distance_per_window,
            total_length,
        )

        def path_function(
            u,
            start_s=start_s,
            end_s=end_s,
        ):

            s = (
                start_s
                +
                (
                    end_s
                    - start_s
                )
                * u
            )

            p1 = float(
                np.interp(
                    s,
                    cumulative,
                    p1_lookup,
                )
            )

            p2 = float(
                np.interp(
                    s,
                    cumulative,
                    p2_lookup,
                )
            )

            return (
                p1,
                p2,
            )

        reached = (
            context.evaluate_window(
                path_function,
                "spiral",
            )
        )

        current_s = (
            end_s
        )

        if reached:
            break

    context.save()

    return (
        context.summary()
    )


# ============================================================
# ALGORYTM 2 - ADAPTACYJNA ORBITA
# ============================================================

def run_adaptive(
    mpc,
    mdt,
    ads,
    reference_best,
):

    print()
    print("=" * 80)
    print(
        "ALGORYTM 2: "
        "ADAPTACYJNA TRAJEKTORIA 2D"
    )
    print("=" * 80)

    reset_system(
        mpc,
        mdt,
    )

    context = (
        AlgorithmContext(
            "adaptive",
            mpc,
            mdt,
            ads,
            reference_best,
        )
    )

    center = np.array(
        [
            START_P1,
            START_P2,
        ],
        dtype=float,
    )

    heading = np.array(
        [
            0.0,
            0.0,
        ],
        dtype=float,
    )

    radius = (
        ADAPTIVE_RADIUS_DEG
    )

    center_step = (
        ADAPTIVE_CENTER_STEP_DEG
    )

    previous_orbit_best = None

    orbit_id = 0

    while not context.time_finished():

        orbit_id += 1

        print()
        print(
            f"ORBITA {orbit_id}"
        )

        center_start = (
            center.copy()
        )

        drift = (
            heading
            * center_step
        )

        orbit_results = []

        for part in range(
            ADAPTIVE_WINDOWS_PER_ORBIT
        ):

            if context.time_finished():
                break

            phase_start = (
                2.0
                * math.pi
                *
                part
                /
                ADAPTIVE_WINDOWS_PER_ORBIT
            )

            phase_end = (
                2.0
                * math.pi
                *
                (part + 1)
                /
                ADAPTIVE_WINDOWS_PER_ORBIT
            )

            def path_function(
                u,
                part=part,
                phase_start=
                    phase_start,
                phase_end=
                    phase_end,
                center_start=
                    center_start.copy(),
                drift=
                    drift.copy(),
                radius=
                    radius,
            ):

                orbit_fraction = (
                    part + u
                ) / ADAPTIVE_WINDOWS_PER_ORBIT

                local_center = (
                    center_start
                    +
                    drift
                    * orbit_fraction
                )

                phase = (
                    phase_start
                    +
                    (
                        phase_end
                        - phase_start
                    )
                    * u
                )

                p1 = (
                    local_center[0]
                    +
                    radius
                    * math.cos(
                        phase
                    )
                )

                p2 = (
                    local_center[1]
                    +
                    radius
                    * math.sin(
                        phase
                    )
                )

                return (
                    clamp(
                        p1,
                        MPC_MIN_DEG,
                        MPC_MAX_DEG,
                    ),

                    clamp(
                        p2,
                        MPC_MIN_DEG,
                        MPC_MAX_DEG,
                    ),
                )

            reached = (
                context.evaluate_window(
                    path_function,
                    f"orbit_{orbit_id}",
                )
            )

            result = (
                context.window_rows[-1]
            )

            midpoint = (
                phase_start
                +
                (
                    phase_end
                    - phase_start
                )
                / 2.0
            )

            direction_vector = (
                np.array(
                    [
                        math.cos(
                            midpoint
                        ),
                        math.sin(
                            midpoint
                        ),
                    ]
                )
            )

            orbit_results.append(
                {
                    "amplitude":
                        result[
                            "diff_amplitude_v"
                        ],

                    "direction":
                        direction_vector,
                }
            )

            if reached:

                context.save()

                return (
                    context.summary()
                )

        if len(
            orbit_results
        ) < 2:

            break

        # --------------------------------------------
        # nowy środek
        # --------------------------------------------

        center = (
            center_start
            +
            drift
        )

        center[0] = clamp(
            center[0],
            MPC_MIN_DEG
            + radius,
            MPC_MAX_DEG
            - radius,
        )

        center[1] = clamp(
            center[1],
            MPC_MIN_DEG
            + radius,
            MPC_MAX_DEG
            - radius,
        )

        amplitudes = np.array(
            [
                r[
                    "amplitude"
                ]
                for r
                in orbit_results
            ],
            dtype=float,
        )

        mean_amp = float(
            np.mean(
                amplitudes
            )
        )

        gradient = np.array(
            [
                0.0,
                0.0,
            ]
        )

        for r in orbit_results:

            gradient += (
                (
                    r[
                        "amplitude"
                    ]
                    -
                    mean_amp
                )
                *
                r[
                    "direction"
                ]
            )

        norm = float(
            np.linalg.norm(
                gradient
            )
        )

        if norm > 1e-9:

            heading = (
                gradient
                /
                norm
            )

        orbit_best = float(
            np.max(
                amplitudes
            )
        )

        print(
            f"Środek: "
            f"({center[0]:.2f}°, "
            f"{center[1]:.2f}°)"
        )

        print(
            f"Kierunek: "
            f"({heading[0]:+.3f}, "
            f"{heading[1]:+.3f})"
        )

        print(
            f"Promień: "
            f"{radius:.2f}°"
        )

        print(
            f"Krok środka: "
            f"{center_step:.2f}°"
        )

        if (
            previous_orbit_best
            is not None
        ):

            improvement = (
                orbit_best
                -
                previous_orbit_best
            )

            if (
                improvement
                <
                MIN_IMPROVEMENT_V
            ):

                radius = max(
                    ADAPTIVE_MIN_RADIUS_DEG,
                    radius * 0.75,
                )

                center_step = max(
                    ADAPTIVE_MIN_CENTER_STEP_DEG,
                    center_step
                    * 0.75,
                )

        previous_orbit_best = (
            orbit_best
        )

    context.save()

    return (
        context.summary()
    )


# ============================================================
# ALGORYTM 3 - CONTINUOUS COORDINATE SEARCH
# ============================================================

def run_coordinate(
    mpc,
    mdt,
    ads,
    reference_best,
):

    print()
    print("=" * 80)
    print(
        "ALGORYTM 3: "
        "CONTINUOUS COORDINATE SEARCH"
    )
    print("=" * 80)

    reset_system(
        mpc,
        mdt,
    )

    context = (
        AlgorithmContext(
            "coordinate",
            mpc,
            mdt,
            ads,
            reference_best,
        )
    )

    current_p1 = (
        START_P1
    )

    current_p2 = (
        START_P2
    )

    # --------------------------------------------
    # baseline
    # --------------------------------------------

    def baseline_path(_):

        return (
            current_p1,
            current_p2,
        )

    reached = (
        context.evaluate_window(
            baseline_path,
            "baseline",
        )
    )

    if reached:

        context.save()

        return (
            context.summary()
        )

    best_amp = (
        context.best[
            "diff_amplitude_v"
        ]
    )

    # --------------------------------------------
    # kolejne dokładności
    # --------------------------------------------

    for speed in (
        COORDINATE_SPEEDS_DEG_S
    ):

        if context.time_finished():
            break

        print()
        print(
            f"Prędkość "
            f"{speed:.2f}°/s"
        )

        stage_improved = False

        for axis in [
            1,
            2,
        ]:

            if context.time_finished():
                break

            base_p1 = (
                current_p1
            )

            base_p2 = (
                current_p2
            )

            base_amp = (
                best_amp
            )

            axis_best_amp = (
                base_amp
            )

            axis_best_p1 = (
                base_p1
            )

            axis_best_p2 = (
                base_p2
            )

            # + następnie -, jeżeli + nie daje poprawy

            for direction in [
                +1,
                -1,
            ]:

                move_both_and_wait(
                    mpc,
                    base_p1,
                    base_p2,
                )

                sweep_p1 = (
                    base_p1
                )

                sweep_p2 = (
                    base_p2
                )

                previous_amp = (
                    base_amp
                )

                falling_count = 0

                direction_improved = (
                    False
                )

                for _ in range(
                    COORDINATE_MAX_WINDOWS_DIRECTION
                ):

                    if context.time_finished():
                        break

                    distance = (
                        speed
                        * HALF_CYCLE_TIME_S
                    )

                    start1 = (
                        sweep_p1
                    )

                    start2 = (
                        sweep_p2
                    )

                    if axis == 1:

                        end1 = clamp(
                            start1
                            +
                            direction
                            * distance,
                            MPC_MIN_DEG,
                            MPC_MAX_DEG,
                        )

                        end2 = (
                            start2
                        )

                    else:

                        end1 = (
                            start1
                        )

                        end2 = clamp(
                            start2
                            +
                            direction
                            * distance,
                            MPC_MIN_DEG,
                            MPC_MAX_DEG,
                        )

                    if (
                        abs(
                            end1
                            - start1
                        )
                        < 0.001
                        and
                        abs(
                            end2
                            - start2
                        )
                        < 0.001
                    ):

                        break

                    def path_function(
                        u,
                        start1=start1,
                        start2=start2,
                        end1=end1,
                        end2=end2,
                    ):

                        p1 = (
                            start1
                            +
                            (
                                end1
                                - start1
                            )
                            * u
                        )

                        p2 = (
                            start2
                            +
                            (
                                end2
                                - start2
                            )
                            * u
                        )

                        return (
                            p1,
                            p2,
                        )

                    state = (
                        f"axis{axis}_"
                        f"{direction:+d}_"
                        f"{speed:.2f}"
                    )

                    reached = (
                        context.evaluate_window(
                            path_function,
                            state,
                        )
                    )

                    row = (
                        context.window_rows[-1]
                    )

                    amp = (
                        row[
                            "diff_amplitude_v"
                        ]
                    )

                    mean_p1 = (
                        row[
                            "p1_mean_deg"
                        ]
                    )

                    mean_p2 = (
                        row[
                            "p2_mean_deg"
                        ]
                    )

                    if (
                        amp
                        >
                        axis_best_amp
                        +
                        MIN_IMPROVEMENT_V
                    ):

                        axis_best_amp = (
                            amp
                        )

                        axis_best_p1 = (
                            mean_p1
                        )

                        axis_best_p2 = (
                            mean_p2
                        )

                        direction_improved = (
                            True
                        )

                    if (
                        amp
                        <
                        previous_amp
                        -
                        MIN_IMPROVEMENT_V
                    ):

                        falling_count += 1

                    else:

                        falling_count = 0

                    previous_amp = (
                        amp
                    )

                    sweep_p1 = (
                        end1
                    )

                    sweep_p2 = (
                        end2
                    )

                    if reached:

                        context.save()

                        return (
                            context.summary()
                        )

                    if (
                        falling_count
                        >=
                        FALLING_WINDOWS_TO_REVERSE
                    ):

                        print(
                            "  wykryto spadek "
                            "funkcji celu"
                        )

                        break

                if direction_improved:

                    # znaleźliśmy dobrą stronę
                    # tej osi, nie sprawdzamy przeciwnej

                    break

            current_p1 = (
                axis_best_p1
            )

            current_p2 = (
                axis_best_p2
            )

            move_both_and_wait(
                mpc,
                current_p1,
                current_p2,
            )

            if (
                axis_best_amp
                >
                best_amp
                +
                MIN_IMPROVEMENT_V
            ):

                best_amp = (
                    axis_best_amp
                )

                stage_improved = (
                    True
                )

        if not stage_improved:

            print(
                "Brak poprawy -> "
                "zmniejszam prędkość."
            )

    context.save()

    return (
        context.summary()
    )


# ============================================================
# WCZYTANIE STAREJ REFERENCJI
# ============================================================

def load_reference():

    filepath = (
        OUTPUT_DIR
        /
        "reference_windows.csv"
    )

    if not filepath.exists():

        raise RuntimeError(
            "Nie znaleziono "
            "reference_windows.csv. "
            "Ustaw RUN_REFERENCE=True."
        )

    rows = []

    with open(
        filepath,
        newline="",
        encoding="utf-8",
    ) as f:

        reader = csv.DictReader(
            f
        )

        for row in reader:

            parsed = {}

            for key, value in (
                row.items()
            ):

                if key in [
                    "piezo_direction",
                ]:

                    parsed[key] = (
                        value
                    )

                elif key in [
                    "window_id",
                    "row_id",
                    "samples",
                ]:

                    parsed[key] = (
                        int(value)
                    )

                else:

                    parsed[key] = (
                        float(value)
                    )

            rows.append(
                parsed
            )

    best = max(
        rows,
        key=lambda r:
            r[
                "diff_amplitude_v"
            ],
    )

    return (
        rows,
        best,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    mpc = None
    mdt = None
    ads = None

    summaries = []

    try:

        print()
        print("=" * 80)
        print(
            "TEST CIĄGŁYCH ALGORYTMÓW POLARYZACJI"
        )
        print("=" * 80)

        print(
            f"Start: "
            f"P1={START_P1:.1f}°, "
            f"P2={START_P2:.1f}°"
        )

        print(
            f"Piezo: "
            f"{PIEZO_MIN_V:.1f} "
            f"<-> "
            f"{PIEZO_MAX_V:.1f} V"
        )

        print(
            f"Half-cycle: "
            f"{HALF_CYCLE_TIME_S:.2f} s"
        )

        print(
            f"Próg algorytmu: "
            f"A_D >= "
            f"{TARGET_AMPLITUDE_V:.3f} V"
        )

        # ====================================================
        # MPC
        # ====================================================

        print()
        print(
            "Łączenie MPC220..."
        )

        mpc = (
            MPC220Driver(
                MPC_PORT
            )
        )

        mpc.connect()

        print(
            "MPC220 OK"
        )

        # ====================================================
        # MDT
        # ====================================================

        print()
        print(
            "Łączenie MDT694B..."
        )

        mdt = (
            MDT694BDriver(
                MDT_PORT
            )
        )

        mdt.connect()

        print(
            "MDT694B OK"
        )

        # ====================================================
        # ADS
        # ====================================================

        # POPRAWIONE:
        # wcześniej brakowało jawnego connect()

        ads = (
            connect_ads()
        )

        # ====================================================
        # REFERENCJA
        # ====================================================

        if RUN_REFERENCE:

            (
                reference_rows,
                reference_best,
                reference_time,
            ) = (
                run_reference_scan(
                    mpc,
                    mdt,
                    ads,
                )
            )

        else:

            (
                reference_rows,
                reference_best,
            ) = (
                load_reference()
            )

            reference_time = (
                float("nan")
            )

        print()
        print("=" * 80)
        print(
            "MAKSIMUM REFERENCYJNE"
        )
        print("=" * 80)

        print(
            f"A_D = "
            f"{reference_best['diff_amplitude_v']:.6f} V"
        )

        print(
            f"P1 ≈ "
            f"{reference_best['p1_mean_deg']:.2f}°"
        )

        print(
            f"P2 ≈ "
            f"{reference_best['p2_mean_deg']:.2f}°"
        )

        # ====================================================
        # SPIRALA
        # ====================================================

        if RUN_SPIRAL:

            result = (
                run_spiral(
                    mpc,
                    mdt,
                    ads,
                    reference_best,
                )
            )

            if result is not None:

                summaries.append(
                    result
                )

        # ====================================================
        # ADAPTACYJNY
        # ====================================================

        if RUN_ADAPTIVE:

            result = (
                run_adaptive(
                    mpc,
                    mdt,
                    ads,
                    reference_best,
                )
            )

            if result is not None:

                summaries.append(
                    result
                )

        # ====================================================
        # COORDINATE
        # ====================================================

        if RUN_COORDINATE:

            result = (
                run_coordinate(
                    mpc,
                    mdt,
                    ads,
                    reference_best,
                )
            )

            if result is not None:

                summaries.append(
                    result
                )

        # ====================================================
        # COMPARISON
        # ====================================================

        save_csv(
            OUTPUT_DIR
            /
            "comparison.csv",
            summaries,
        )

        print()
        print("=" * 100)
        print(
            "WYNIKI KOŃCOWE"
        )
        print("=" * 100)

        print(
            f"Referencja:"
        )

        print(
            f"  A_D max = "
            f"{reference_best['diff_amplitude_v']:.4f} V"
        )

        print(
            f"  P1 ≈ "
            f"{reference_best['p1_mean_deg']:.2f}°"
        )

        print(
            f"  P2 ≈ "
            f"{reference_best['p2_mean_deg']:.2f}°"
        )

        for result in summaries:

            print()
            print(
                result[
                    "algorithm"
                ].upper()
            )

            print(
                f"  czas: "
                f"{result['time_s']:.1f} s"
            )

            print(
                f"  próg osiągnięty: "
                f"{result['target_reached']}"
            )

            print(
                f"  A_D max: "
                f"{result['max_diff_amplitude_v']:.4f} V"
            )

            print(
                f"  A_D min: "
                f"{result['min_diff_amplitude_v']:.4f} V"
            )

            print(
                f"  najlepsza pozycja: "
                f"P1="
                f"{result['best_p1_deg']:.2f}°, "
                f"P2="
                f"{result['best_p2_deg']:.2f}°"
            )

            print(
                f"  okna: "
                f"{result['windows']}"
            )

            print(
                f"  potwierdzenia: "
                f"{result['confirmations']}"
            )

            print(
                f"  długość trajektorii: "
                f"{result['path_length_deg']:.1f}°"
            )

            print(
                f"  stopień przeszukania: "
                f"{result['search_degree_pct']:.1f}%"
            )

            print(
                f"  odległość od maksimum ref.: "
                f"{result['distance_from_reference_deg']:.2f}°"
            )

            print(
                f"  różnica A_D względem ref.: "
                f"{result['reference_amp_error_v']:.4f} V"
            )

        print()
        print(
            "Pliki zapisano w:"
        )

        print(
            OUTPUT_DIR
        )

    finally:

        print()
        print(
            "Zamykanie urządzeń..."
        )

        # ADS
        close_ads(
            ads
        )

        # MDT
        if mdt is not None:

            try:

                mdt.close()

            except Exception:

                try:

                    mdt.disconnect()

                except Exception:

                    pass

        # MPC
        if mpc is not None:

            try:

                mpc.close()

            except Exception:

                try:

                    mpc.disconnect()

                except Exception:

                    pass

        print(
            "Koniec."
        )


if __name__ == "__main__":

    main()