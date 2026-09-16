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
    / "test_algorytmow_zmienna_predkosc"
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
# MPC
# ============================================================

MPC_MIN_DEG = 1.0
MPC_MAX_DEG = 160.0

START_P1_DEG = 80.0
START_P2_DEG = 80.0

# ------------------------------------------------------------
# ZMIENNA PRĘDKOŚĆ
# ------------------------------------------------------------

FAST_SPEED_DEG_S = 5.0
SLOW_SPEED_DEG_S = 1.0

SLOWDOWN_THRESHOLD_V = 0.35

MPC_COMMAND_INTERVAL_S = 0.12
MPC_SETTLE_S = 0.8


# ============================================================
# WARUNEK ZNALEZIENIA MAKSIMUM
# ============================================================

# Nowy wynik musi poprawić najlepszy o co najmniej 2 mV,
# żeby wyzerować licznik braku poprawy.

MIN_IMPROVEMENT_V = 0.002

# Po przejściu do 1°/s:
# 4 kolejne okna bez istotnej poprawy -> STOP

MAX_NO_IMPROVEMENT_WINDOWS = 4

# Maksymalny czas jednego algorytmu - zabezpieczenie

MAX_ALGORITHM_TIME_S = 240.0


# ============================================================
# PIEZO
# ============================================================

PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0

PIEZO_SPEED_V_S = 20.0

PIEZO_COMMAND_INTERVAL_S = 0.05
PIEZO_SETTLE_S = 0.5

HALF_CYCLE_TIME_S = (
    PIEZO_MAX_V
    - PIEZO_MIN_V
) / PIEZO_SPEED_V_S


# ============================================================
# ADS
# ============================================================

SAMPLE_INTERVAL_S = 0.20
DISCARD_SAMPLES = 4


# ============================================================
# ALGORYTM SPIRALNY
# ============================================================

SPIRAL_MAX_RADIUS_DEG = 78.0
SPIRAL_TURNS = 3.0


# ============================================================
# ALGORYTM ADAPTACYJNY
# ============================================================

ADAPTIVE_INITIAL_DIRECTION_DEG = 0.0
ADAPTIVE_DIRECTION_STEP_DEG = 45.0


# ============================================================
# COORDINATE SEARCH
# ============================================================

COORDINATE_DIRECTIONS = [
    (+1.0, 0.0),
    (-1.0, 0.0),
    (0.0, +1.0),
    (0.0, -1.0),
]


# ============================================================
# FUNKCJE PODSTAWOWE MPC
# ============================================================

def clamp_angle(angle):

    return max(
        MPC_MIN_DEG,
        min(
            MPC_MAX_DEG,
            angle,
        ),
    )


def read_paddle_angle(
    mpc,
    paddle,
):

    raw = mpc.read_position_units(
        paddle
    )

    return raw_position_to_angle(
        raw
    )


def read_both_angles(
    mpc,
):

    return (
        read_paddle_angle(
            mpc,
            1,
        ),
        read_paddle_angle(
            mpc,
            2,
        ),
    )


def move_both_and_wait(
    mpc,
    p1_deg,
    p2_deg,
):

    p1_deg = clamp_angle(
        p1_deg
    )

    p2_deg = clamp_angle(
        p2_deg
    )

    mpc.move_absolute_units(
        1,
        angle_to_command(
            p1_deg
        ),
    )

    mpc.move_absolute_units(
        2,
        angle_to_command(
            p2_deg
        ),
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    time.sleep(
        MPC_SETTLE_S
    )

    return read_both_angles(
        mpc
    )


# ============================================================
# PIEZO
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

        now = time.monotonic()

        elapsed = (
            now - start_t
        )

        progress = min(
            elapsed / duration,
            1.0,
        )

        voltage = (
            start_v
            +
            (
                end_v - start_v
            )
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


def condition_piezo(
    mdt,
):

    print(
        "  Kondycjonowanie piezo..."
    )

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

    if hasattr(
        ads,
        "connect",
    ):
        ads.connect()

    ads.start_measurement()

    return ads


def discard_ads_samples(
    ads,
):

    for _ in range(
        DISCARD_SAMPLES
    ):

        ads.read_sample()

        time.sleep(
            SAMPLE_INTERVAL_S
        )


def close_ads(
    ads,
):

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

def calculate_metrics(
    samples,
):

    if len(samples) < 5:

        return {
            "diff_amplitude_v":
                float("nan"),

            "score":
                float("nan"),

            "mean_sum_v":
                float("nan"),
        }

    in0 = np.array(
        [
            row["in0_v"]
            for row in samples
        ],
        dtype=float,
    )

    in1 = np.array(
        [
            row["in1_v"]
            for row in samples
        ],
        dtype=float,
    )

    diff = (
        in0 - in1
    )

    diff_amplitude = (
        np.percentile(
            diff,
            95,
        )
        -
        np.percentile(
            diff,
            5,
        )
    ) / 2.0

    total = (
        in0 + in1
    )

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
            float(
                diff_amplitude
            ),

        "score":
            float(score),

        "mean_sum_v":
            float(
                np.mean(total)
            ),
    }


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
# KONTROLER PRĘDKOŚCI
# ============================================================

class SpeedController:

    def __init__(self):

        self.refine_mode = False

        self.switch_time_s = float(
            "nan"
        )

        self.switch_amplitude_v = float(
            "nan"
        )

        self.switch_p1_deg = float(
            "nan"
        )

        self.switch_p2_deg = float(
            "nan"
        )


    def get_speed(self):

        if self.refine_mode:

            return (
                SLOW_SPEED_DEG_S
            )

        return (
            FAST_SPEED_DEG_S
        )


    def update(
        self,
        row,
    ):

        amplitude = row[
            "diff_amplitude_v"
        ]

        if (
            not self.refine_mode
            and
            amplitude
            >= SLOWDOWN_THRESHOLD_V
        ):

            self.refine_mode = True

            self.switch_time_s = row[
                "algorithm_time_s"
            ]

            self.switch_amplitude_v = (
                amplitude
            )

            self.switch_p1_deg = row[
                "p1_mean_deg"
            ]

            self.switch_p2_deg = row[
                "p2_mean_deg"
            ]

            print()
            print(
                "  >>> PRZEJŚCIE SEARCH -> REFINE"
            )

            print(
                f"  A_D = "
                f"{amplitude:.6f} V"
            )

            print(
                f"  P1 = "
                f"{self.switch_p1_deg:.2f}°"
            )

            print(
                f"  P2 = "
                f"{self.switch_p2_deg:.2f}°"
            )

            print(
                f"  czas = "
                f"{self.switch_time_s:.2f} s"
            )

            print(
                f"  prędkość: "
                f"{FAST_SPEED_DEG_S:.1f} "
                f"-> "
                f"{SLOW_SPEED_DEG_S:.1f} °/s"
            )

            print()


# ============================================================
# DETEKTOR MAKSIMUM
# ============================================================

class MaximumDetector:

    def __init__(self):

        self.best_amplitude = -np.inf

        self.best_p1 = float(
            "nan"
        )

        self.best_p2 = float(
            "nan"
        )

        self.best_time_s = float(
            "nan"
        )

        self.best_window_id = None

        self.no_improvement_count = 0

        self.maximum_found = False

        self.convergence_time_s = float(
            "nan"
        )


    def update(
        self,
        row,
        refine_mode,
    ):

        amplitude = row[
            "diff_amplitude_v"
        ]

        # ----------------------------------------------------
        # Pierwszy wynik
        # ----------------------------------------------------

        if not np.isfinite(
            self.best_amplitude
        ):

            self.best_amplitude = (
                amplitude
            )

            self.best_p1 = row[
                "p1_mean_deg"
            ]

            self.best_p2 = row[
                "p2_mean_deg"
            ]

            self.best_time_s = row[
                "algorithm_time_s"
            ]

            self.best_window_id = row[
                "window_id"
            ]

            return False

        # ----------------------------------------------------
        # Sprawdzamy poprawę
        # ----------------------------------------------------

        improvement = (
            amplitude
            -
            self.best_amplitude
        )

        if (
            improvement
            >= MIN_IMPROVEMENT_V
        ):

            self.best_amplitude = (
                amplitude
            )

            self.best_p1 = row[
                "p1_mean_deg"
            ]

            self.best_p2 = row[
                "p2_mean_deg"
            ]

            self.best_time_s = row[
                "algorithm_time_s"
            ]

            self.best_window_id = row[
                "window_id"
            ]

            self.no_improvement_count = 0

            print(
                f"  >>> nowe najlepsze "
                f"A_D = "
                f"{self.best_amplitude:.6f} V"
            )

        else:

            # Liczymy brak poprawy wyłącznie
            # w fazie dokładnej.

            if refine_mode:

                self.no_improvement_count += 1

                print(
                    f"  brak poprawy: "
                    f"{self.no_improvement_count}"
                    f"/"
                    f"{MAX_NO_IMPROVEMENT_WINDOWS}"
                )

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

        if (
            refine_mode
            and
            self.no_improvement_count
            >= MAX_NO_IMPROVEMENT_WINDOWS
        ):

            self.maximum_found = True

            self.convergence_time_s = row[
                "algorithm_time_s"
            ]

            print()
            print(
                "=" * 70
            )

            print(
                "  MAKSIMUM UZNANE ZA ZNALEZIONE"
            )

            print(
                f"  A_D = "
                f"{self.best_amplitude:.6f} V"
            )

            print(
                f"  P1 = "
                f"{self.best_p1:.2f}°"
            )

            print(
                f"  P2 = "
                f"{self.best_p2:.2f}°"
            )

            print(
                f"  najlepszy pomiar "
                f"po "
                f"{self.best_time_s:.2f} s"
            )

            print(
                f"  algorytm zakończony "
                f"po "
                f"{self.convergence_time_s:.2f} s"
            )

            print(
                "=" * 70
            )

            print()

            return True

        return False


# ============================================================
# POJEDYNCZE OKNO CIĄGŁE
# ============================================================

def run_motion_window(
    mpc,
    mdt,
    ads,
    direction_p1,
    direction_p2,
    speed_deg_s,
    piezo_up,
    algorithm,
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
        read_both_angles(
            mpc
        )
    )

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
            elapsed
            / HALF_CYCLE_TIME_S,
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

            target_p1 = (
                start_p1
                +
                direction_p1
                * distance
            )

            target_p2 = (
                start_p2
                +
                direction_p2
                * distance
            )

            target_p1 = clamp_angle(
                target_p1
            )

            target_p2 = clamp_angle(
                target_p2
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
                +
                MPC_COMMAND_INTERVAL_S
            )

        # ====================================================
        # PIEZO
        # ====================================================

        if now >= next_piezo:

            if piezo_up:

                piezo_voltage = (
                    PIEZO_MIN_V
                    +
                    (
                        PIEZO_MAX_V
                        -
                        PIEZO_MIN_V
                    )
                    * progress
                )

            else:

                piezo_voltage = (
                    PIEZO_MAX_V
                    -
                    (
                        PIEZO_MAX_V
                        -
                        PIEZO_MIN_V
                    )
                    * progress
                )

            fast_set_voltage(
                mdt,
                piezo_voltage,
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
                    "algorithm":
                        algorithm,

                    "window_id":
                        window_id,

                    "algorithm_time_s":
                        now
                        -
                        algorithm_start_t,

                    "time_in_window_s":
                        elapsed,

                    "speed_deg_s":
                        speed_deg_s,

                    "mode":
                        (
                            "SEARCH"
                            if speed_deg_s
                            == FAST_SPEED_DEG_S
                            else "REFINE"
                        ),

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
                        float(
                            in0 - in1
                        ),
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

    # ========================================================
    # DOKŁADNE USTAWIENIE KOŃCA PIEZO
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

    # ========================================================
    # METRYKA
    # ========================================================

    metrics = calculate_metrics(
        samples
    )

    p1_values = np.array(
        [
            row["p1_deg"]
            for row in samples
        ],
        dtype=float,
    )

    p2_values = np.array(
        [
            row["p2_deg"]
            for row in samples
        ],
        dtype=float,
    )

    end_p1, end_p2 = (
        read_both_angles(
            mpc
        )
    )

    travelled_distance = math.hypot(
        end_p1 - start_p1,
        end_p2 - start_p2,
    )

    summary = {
        "algorithm":
            algorithm,

        "window_id":
            window_id,

        "algorithm_time_s":
            time.monotonic()
            -
            algorithm_start_t,

        "speed_deg_s":
            speed_deg_s,

        "mode":
            (
                "SEARCH"
                if speed_deg_s
                == FAST_SPEED_DEG_S
                else "REFINE"
            ),

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
                np.mean(
                    p1_values
                )
            ),

        "p2_mean_deg":
            float(
                np.mean(
                    p2_values
                )
            ),

        "travelled_distance_deg":
            float(
                travelled_distance
            ),

        "diff_amplitude_v":
            metrics[
                "diff_amplitude_v"
            ],

        "score":
            metrics[
                "score"
            ],

        "mean_sum_v":
            metrics[
                "mean_sum_v"
            ],

        "samples":
            len(samples),
    }

    return (
        summary,
        samples,
    )


# ============================================================
# LOG OKNA
# ============================================================

def print_window(
    row,
):

    print(
        f"W{row['window_id']:03d} | "
        f"{row['mode']:6s} | "
        f"v={row['speed_deg_s']:.1f}°/s | "
        f"P1={row['p1_mean_deg']:7.2f}° | "
        f"P2={row['p2_mean_deg']:7.2f}° | "
        f"A_D={row['diff_amplitude_v']:.6f} V | "
        f"t={row['algorithm_time_s']:.1f}s"
    )


# ============================================================
# OBSŁUGA WSPÓLNA WYNIKU OKNA
# ============================================================

def process_window_result(
    row,
    speed_controller,
    maximum_detector,
):

    print_window(
        row
    )

    # --------------------------------------------------------
    # Najpierw zapamiętujemy stan przed zmianą
    # --------------------------------------------------------

    was_refine = (
        speed_controller
        .refine_mode
    )

    # --------------------------------------------------------
    # Przełączenie 5 -> 1
    # --------------------------------------------------------

    speed_controller.update(
        row
    )

    # --------------------------------------------------------
    # Jeżeli właśnie weszliśmy do REFINE,
    # traktujemy bieżący wynik jako punkt wejścia,
    # ale NIE naliczamy jeszcze braku poprawy.
    # --------------------------------------------------------

    just_switched = (
        not was_refine
        and
        speed_controller.refine_mode
    )

    if just_switched:

        # Aktualizujemy najlepszy wynik,
        # ale nie chcemy od razu naliczać
        # "braku poprawy".

        if (
            row["diff_amplitude_v"]
            >
            maximum_detector.best_amplitude
        ):

            maximum_detector.best_amplitude = (
                row[
                    "diff_amplitude_v"
                ]
            )

            maximum_detector.best_p1 = row[
                "p1_mean_deg"
            ]

            maximum_detector.best_p2 = row[
                "p2_mean_deg"
            ]

            maximum_detector.best_time_s = row[
                "algorithm_time_s"
            ]

            maximum_detector.best_window_id = row[
                "window_id"
            ]

            maximum_detector.no_improvement_count = 0

        return False

    # --------------------------------------------------------
    # Normalna aktualizacja maksimum
    # --------------------------------------------------------

    return maximum_detector.update(
        row=row,
        refine_mode=(
            speed_controller
            .refine_mode
        ),
    )


# ============================================================
# ALGORYTM 1 — SPIRALA
# ============================================================

def run_spiral(
    mpc,
    mdt,
    ads,
):

    name = "spiral"

    print()
    print("=" * 80)
    print(
        "ALGORYTM 1 — SPIRALA"
    )
    print("=" * 80)

    move_both_and_wait(
        mpc,
        START_P1_DEG,
        START_P2_DEG,
    )

    condition_piezo(
        mdt
    )

    discard_ads_samples(
        ads
    )

    speed_controller = (
        SpeedController()
    )

    maximum_detector = (
        MaximumDetector()
    )

    windows = []
    raw_rows = []

    algorithm_start_t = (
        time.monotonic()
    )

    piezo_up = True
    window_id = 0

    theta = 0.0

    dr_dtheta = (
        SPIRAL_MAX_RADIUS_DEG
        /
        (
            2.0
            * math.pi
            * SPIRAL_TURNS
        )
    )

    stop_reason = (
        "time_limit"
    )

    while True:

        algorithm_time = (
            time.monotonic()
            -
            algorithm_start_t
        )

        if (
            algorithm_time
            >= MAX_ALGORITHM_TIME_S
        ):

            stop_reason = (
                "time_limit"
            )

            break

        if (
            theta
            >=
            2.0
            * math.pi
            * SPIRAL_TURNS
        ):

            stop_reason = (
                "path_finished"
            )

            break

        radius = (
            dr_dtheta
            * theta
        )

        # ----------------------------------------------------
        # Styczna do spirali Archimedesa
        # ----------------------------------------------------

        dx = (
            dr_dtheta
            * math.cos(theta)
            -
            radius
            * math.sin(theta)
        )

        dy = (
            dr_dtheta
            * math.sin(theta)
            +
            radius
            * math.cos(theta)
        )

        speed = (
            speed_controller
            .get_speed()
        )

        window_id += 1

        row, samples = (
            run_motion_window(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                direction_p1=dx,
                direction_p2=dy,

                speed_deg_s=speed,

                piezo_up=piezo_up,

                algorithm=name,
                window_id=window_id,

                algorithm_start_t=
                    algorithm_start_t,
            )
        )

        piezo_up = (
            not piezo_up
        )

        windows.append(
            row
        )

        raw_rows.extend(
            samples
        )

        stop = (
            process_window_result(
                row,
                speed_controller,
                maximum_detector,
            )
        )

        if stop:

            stop_reason = (
                "maximum_found"
            )

            break

        # ----------------------------------------------------
        # Aktualizacja theta na podstawie faktycznej
        # drogi jednego okna
        # ----------------------------------------------------

        travelled = row[
            "travelled_distance_deg"
        ]

        ds_dtheta = max(
            math.hypot(
                dr_dtheta,
                radius,
            ),
            1e-6,
        )

        theta += (
            travelled
            /
            ds_dtheta
        )

    return {
        "name":
            name,

        "windows":
            windows,

        "raw":
            raw_rows,

        "speed_controller":
            speed_controller,

        "maximum_detector":
            maximum_detector,

        "stop_reason":
            stop_reason,

        "total_time_s":
            time.monotonic()
            -
            algorithm_start_t,
    }


# ============================================================
# ALGORYTM 2 — ADAPTACYJNY
# ============================================================

def run_adaptive(
    mpc,
    mdt,
    ads,
):

    name = "adaptive"

    print()
    print("=" * 80)
    print(
        "ALGORYTM 2 — ADAPTACYJNY"
    )
    print("=" * 80)

    move_both_and_wait(
        mpc,
        START_P1_DEG,
        START_P2_DEG,
    )

    condition_piezo(
        mdt
    )

    discard_ads_samples(
        ads
    )

    speed_controller = (
        SpeedController()
    )

    maximum_detector = (
        MaximumDetector()
    )

    windows = []
    raw_rows = []

    algorithm_start_t = (
        time.monotonic()
    )

    piezo_up = True
    window_id = 0

    direction_deg = (
        ADAPTIVE_INITIAL_DIRECTION_DEG
    )

    previous_amplitude = None

    rotation_sign = 1.0

    stop_reason = (
        "time_limit"
    )

    while True:

        if (
            time.monotonic()
            -
            algorithm_start_t
            >= MAX_ALGORITHM_TIME_S
        ):

            stop_reason = (
                "time_limit"
            )

            break

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

        speed = (
            speed_controller
            .get_speed()
        )

        window_id += 1

        row, samples = (
            run_motion_window(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                direction_p1=dx,
                direction_p2=dy,

                speed_deg_s=speed,

                piezo_up=piezo_up,

                algorithm=name,
                window_id=window_id,

                algorithm_start_t=
                    algorithm_start_t,
            )
        )

        piezo_up = (
            not piezo_up
        )

        windows.append(
            row
        )

        raw_rows.extend(
            samples
        )

        stop = (
            process_window_result(
                row,
                speed_controller,
                maximum_detector,
            )
        )

        if stop:

            stop_reason = (
                "maximum_found"
            )

            break

        amplitude = row[
            "diff_amplitude_v"
        ]

        # ----------------------------------------------------
        # Sterowanie kierunkiem
        #
        # Jeśli wynik nie pogorszył się -> jedziemy dalej.
        # Jeśli spadł -> zmiana kierunku o 45°.
        # ----------------------------------------------------

        if previous_amplitude is not None:

            if (
                amplitude
                <
                previous_amplitude
            ):

                direction_deg += (
                    rotation_sign
                    *
                    ADAPTIVE_DIRECTION_STEP_DEG
                )

                rotation_sign *= -1.0

        previous_amplitude = (
            amplitude
        )

        direction_deg %= 360.0

        # ----------------------------------------------------
        # Granice
        # ----------------------------------------------------

        p1, p2 = (
            read_both_angles(
                mpc
            )
        )

        margin = (
            speed
            *
            HALF_CYCLE_TIME_S
            +
            2.0
        )

        if (
            p1
            <= MPC_MIN_DEG + margin

            or p1
            >= MPC_MAX_DEG - margin

            or p2
            <= MPC_MIN_DEG + margin

            or p2
            >= MPC_MAX_DEG - margin
        ):

            direction_deg += 135.0
            direction_deg %= 360.0

    return {
        "name":
            name,

        "windows":
            windows,

        "raw":
            raw_rows,

        "speed_controller":
            speed_controller,

        "maximum_detector":
            maximum_detector,

        "stop_reason":
            stop_reason,

        "total_time_s":
            time.monotonic()
            -
            algorithm_start_t,
    }


# ============================================================
# ALGORYTM 3 — COORDINATE SEARCH
# ============================================================

def run_coordinate(
    mpc,
    mdt,
    ads,
):

    name = "coordinate"

    print()
    print("=" * 80)
    print(
        "ALGORYTM 3 — COORDINATE SEARCH"
    )
    print("=" * 80)

    move_both_and_wait(
        mpc,
        START_P1_DEG,
        START_P2_DEG,
    )

    condition_piezo(
        mdt
    )

    discard_ads_samples(
        ads
    )

    speed_controller = (
        SpeedController()
    )

    maximum_detector = (
        MaximumDetector()
    )

    windows = []
    raw_rows = []

    algorithm_start_t = (
        time.monotonic()
    )

    piezo_up = True
    window_id = 0

    direction_index = 0

    previous_amplitude = None

    stop_reason = (
        "time_limit"
    )

    while True:

        if (
            time.monotonic()
            -
            algorithm_start_t
            >= MAX_ALGORITHM_TIME_S
        ):

            stop_reason = (
                "time_limit"
            )

            break

        dx, dy = (
            COORDINATE_DIRECTIONS[
                direction_index
            ]
        )

        speed = (
            speed_controller
            .get_speed()
        )

        window_id += 1

        row, samples = (
            run_motion_window(
                mpc=mpc,
                mdt=mdt,
                ads=ads,

                direction_p1=dx,
                direction_p2=dy,

                speed_deg_s=speed,

                piezo_up=piezo_up,

                algorithm=name,
                window_id=window_id,

                algorithm_start_t=
                    algorithm_start_t,
            )
        )

        piezo_up = (
            not piezo_up
        )

        windows.append(
            row
        )

        raw_rows.extend(
            samples
        )

        stop = (
            process_window_result(
                row,
                speed_controller,
                maximum_detector,
            )
        )

        if stop:

            stop_reason = (
                "maximum_found"
            )

            break

        amplitude = row[
            "diff_amplitude_v"
        ]

        # ----------------------------------------------------
        # Coordinate search:
        #
        # jeśli wynik rośnie -> kontynuujemy,
        # jeśli spada -> następny kierunek
        # ----------------------------------------------------

        if previous_amplitude is not None:

            if (
                amplitude
                <
                previous_amplitude
            ):

                direction_index = (
                    direction_index + 1
                ) % len(
                    COORDINATE_DIRECTIONS
                )

        previous_amplitude = (
            amplitude
        )

        # ----------------------------------------------------
        # Granice
        # ----------------------------------------------------

        p1, p2 = (
            read_both_angles(
                mpc
            )
        )

        margin = (
            speed
            *
            HALF_CYCLE_TIME_S
            +
            1.0
        )

        if (
            p1
            <= MPC_MIN_DEG + margin

            or p1
            >= MPC_MAX_DEG - margin

            or p2
            <= MPC_MIN_DEG + margin

            or p2
            >= MPC_MAX_DEG - margin
        ):

            direction_index = (
                direction_index + 1
            ) % len(
                COORDINATE_DIRECTIONS
            )

    return {
        "name":
            name,

        "windows":
            windows,

        "raw":
            raw_rows,

        "speed_controller":
            speed_controller,

        "maximum_detector":
            maximum_detector,

        "stop_reason":
            stop_reason,

        "total_time_s":
            time.monotonic()
            -
            algorithm_start_t,
    }


# ============================================================
# PODSUMOWANIE JEDNEGO ALGORYTMU
# ============================================================

def summarize_result(
    result,
):

    name = result[
        "name"
    ]

    windows = result[
        "windows"
    ]

    speed_controller = result[
        "speed_controller"
    ]

    maximum_detector = result[
        "maximum_detector"
    ]

    if not windows:
        return None

    amplitudes = np.array(
        [
            row[
                "diff_amplitude_v"
            ]
            for row in windows
        ],
        dtype=float,
    )

    best_index = int(
        np.nanargmax(
            amplitudes
        )
    )

    best = windows[
        best_index
    ]

    fast_windows = sum(
        1
        for row in windows
        if row[
            "speed_deg_s"
        ] == FAST_SPEED_DEG_S
    )

    slow_windows = sum(
        1
        for row in windows
        if row[
            "speed_deg_s"
        ] == SLOW_SPEED_DEG_S
    )

    total_distance = sum(
        row[
            "travelled_distance_deg"
        ]
        for row in windows
    )

    # --------------------------------------------------------
    # Jeżeli detektor zdążył zapisać maksimum,
    # używamy jego czasu.
    #
    # W przeciwnym razie bierzemy najlepszy punkt
    # z całego przebiegu.
    # --------------------------------------------------------

    if np.isfinite(
        maximum_detector.best_time_s
    ):

        best_time = (
            maximum_detector
            .best_time_s
        )

    else:

        best_time = best[
            "algorithm_time_s"
        ]

    if np.isfinite(
        maximum_detector
        .convergence_time_s
    ):

        convergence_time = (
            maximum_detector
            .convergence_time_s
        )

    else:

        convergence_time = result[
            "total_time_s"
        ]

    return {
        "algorithm":
            name,

        "stop_reason":
            result[
                "stop_reason"
            ],

        "maximum_found":
            maximum_detector
            .maximum_found,

        "max_A_D_v":
            float(
                best[
                    "diff_amplitude_v"
                ]
            ),

        "best_p1_deg":
            float(
                best[
                    "p1_mean_deg"
                ]
            ),

        "best_p2_deg":
            float(
                best[
                    "p2_mean_deg"
                ]
            ),

        "best_measurement_time_s":
            float(
                best_time
            ),

        "convergence_time_s":
            float(
                convergence_time
            ),

        "total_time_s":
            float(
                result[
                    "total_time_s"
                ]
            ),

        "windows_total":
            len(windows),

        "fast_windows_5_deg_s":
            fast_windows,

        "slow_windows_1_deg_s":
            slow_windows,

        "slowdown_occurred":
            speed_controller
            .refine_mode,

        "slowdown_time_s":
            float(
                speed_controller
                .switch_time_s
            ),

        "slowdown_A_D_v":
            float(
                speed_controller
                .switch_amplitude_v
            ),

        "slowdown_p1_deg":
            float(
                speed_controller
                .switch_p1_deg
            ),

        "slowdown_p2_deg":
            float(
                speed_controller
                .switch_p2_deg
            ),

        "total_path_deg":
            float(
                total_distance
            ),
    }


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
            "TEST ALGORYTMÓW POLARYZACJI"
        )

        print(
            "ZMIENNA PRĘDKOŚĆ 5°/s -> 1°/s"
        )
        print("=" * 80)

        print()

        print(
            f"Start: "
            f"P1={START_P1_DEG:.1f}°, "
            f"P2={START_P2_DEG:.1f}°"
        )

        print(
            f"SEARCH: "
            f"{FAST_SPEED_DEG_S:.1f}°/s"
        )

        print(
            f"REFINE: "
            f"{SLOW_SPEED_DEG_S:.1f}°/s"
        )

        print(
            f"Przejście do REFINE: "
            f"A_D >= "
            f"{SLOWDOWN_THRESHOLD_V:.3f} V"
        )

        print(
            f"Warunek maksimum: "
            f"{MAX_NO_IMPROVEMENT_WINDOWS} "
            f"okna bez poprawy >= "
            f"{MIN_IMPROVEMENT_V:.3f} V"
        )

        print(
            f"Limit czasu: "
            f"{MAX_ALGORITHM_TIME_S:.0f} s"
        )

        print()

        print(
            f"Piezo: "
            f"{PIEZO_MIN_V:.0f}"
            f"–"
            f"{PIEZO_MAX_V:.0f} V "
            f"@ "
            f"{PIEZO_SPEED_V_S:.1f} V/s"
        )

        print(
            f"Półcykl: "
            f"{HALF_CYCLE_TIME_S:.2f} s"
        )

        print(
            f"Okno przy 5°/s: "
            f"{FAST_SPEED_DEG_S * HALF_CYCLE_TIME_S:.1f}°"
        )

        print(
            f"Okno przy 1°/s: "
            f"{SLOW_SPEED_DEG_S * HALF_CYCLE_TIME_S:.1f}°"
        )

        # ====================================================
        # CONNECT MPC
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
        # CONNECT MDT
        # ====================================================

        print()
        print(
            "Łączenie MDT694B..."
        )

        mdt = MDT694BDriver(
            MDT_PORT
        )

        mdt.connect()

        print(
            "MDT694B OK"
        )

        # ====================================================
        # CONNECT ADS
        # ====================================================

        print()
        print(
            "Łączenie ADS1263..."
        )

        ads = connect_ads()

        print(
            "ADS1263 OK"
        )

        # ====================================================
        # ALGORYTMY
        # ====================================================

        algorithms = [
            run_spiral,
            run_adaptive,
            run_coordinate,
        ]

        summary_rows = []

        all_windows = []
        all_raw = []

        for algorithm_function in algorithms:

            # ------------------------------------------------
            # Piezo zawsze zaczyna od minimum
            # ------------------------------------------------

            fast_set_voltage(
                mdt,
                PIEZO_MIN_V,
            )

            time.sleep(
                PIEZO_SETTLE_S
            )

            result = (
                algorithm_function(
                    mpc,
                    mdt,
                    ads,
                )
            )

            name = result[
                "name"
            ]

            windows = result[
                "windows"
            ]

            raw = result[
                "raw"
            ]

            # ------------------------------------------------
            # ZAPIS
            # ------------------------------------------------

            save_csv(
                OUTPUT_DIR
                /
                f"{name}_windows.csv",
                windows,
            )

            save_csv(
                OUTPUT_DIR
                /
                f"{name}_raw.csv",
                raw,
            )

            all_windows.extend(
                windows
            )

            all_raw.extend(
                raw
            )

            summary = (
                summarize_result(
                    result
                )
            )

            if summary is not None:

                summary_rows.append(
                    summary
                )

            # ------------------------------------------------
            # PRZERWA MIĘDZY ALGORYTMAMI
            # ------------------------------------------------

            print()
            print(
                f"{name.upper()} zakończony."
            )

            print(
                f"Powód: "
                f"{result['stop_reason']}"
            )

            print(
                f"Czas całkowity: "
                f"{result['total_time_s']:.2f} s"
            )

            print()

            fast_set_voltage(
                mdt,
                PIEZO_MIN_V,
            )

            time.sleep(1.0)

        # ====================================================
        # ZAPIS ŁĄCZNY
        # ====================================================

        save_csv(
            OUTPUT_DIR
            /
            "all_windows.csv",
            all_windows,
        )

        save_csv(
            OUTPUT_DIR
            /
            "all_raw.csv",
            all_raw,
        )

        save_csv(
            OUTPUT_DIR
            /
            "summary.csv",
            summary_rows,
        )

        # ====================================================
        # PODSUMOWANIE
        # ====================================================

        print()
        print("=" * 80)
        print(
            "PODSUMOWANIE TESTU"
        )
        print("=" * 80)

        for row in summary_rows:

            print()

            print(
                row[
                    "algorithm"
                ].upper()
            )

            print(
                f"  STOP: "
                f"{row['stop_reason']}"
            )

            print(
                f"  maksimum znalezione: "
                f"{row['maximum_found']}"
            )

            print(
                f"  max A_D: "
                f"{row['max_A_D_v']:.6f} V"
            )

            print(
                f"  P1: "
                f"{row['best_p1_deg']:.2f}°"
            )

            print(
                f"  P2: "
                f"{row['best_p2_deg']:.2f}°"
            )

            print(
                f"  najlepszy pomiar po: "
                f"{row['best_measurement_time_s']:.2f} s"
            )

            print(
                f"  czas konwergencji: "
                f"{row['convergence_time_s']:.2f} s"
            )

            print(
                f"  okna 5°/s: "
                f"{row['fast_windows_5_deg_s']}"
            )

            print(
                f"  okna 1°/s: "
                f"{row['slow_windows_1_deg_s']}"
            )

            print(
                f"  długość ścieżki: "
                f"{row['total_path_deg']:.2f}°"
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
        print(
            "Zamykanie urządzeń..."
        )

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

        close_ads(
            ads
        )

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

        print(
            "Koniec."
        )


if __name__ == "__main__":
    main()