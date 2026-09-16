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
    / "referencja_krzyzowa_5deg_s"
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

MPC_SPEED_DEG_S = 5.0
MPC_COMMAND_INTERVAL_S = 0.12

MPC_SETTLE_S = 0.8


# ============================================================
# LINIE REFERENCYJNE
# ============================================================

FIXED_ANGLES = [
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
# INFORMACJE
# ============================================================

WINDOW_ANGLE_DEG = (
    MPC_SPEED_DEG_S
    * HALF_CYCLE_TIME_S
)


# ============================================================
# MPC - FUNKCJE
# ============================================================

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


def move_both_and_wait(
    mpc,
    p1_deg,
    p2_deg,
):

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

    actual_p1 = read_paddle_angle(
        mpc,
        1,
    )

    actual_p2 = read_paddle_angle(
        mpc,
        2,
    )

    return (
        actual_p1,
        actual_p2,
    )


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
                end_v
                - start_v
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
# METRYKA
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

            "in0_amplitude_v":
                float("nan"),

            "in1_amplitude_v":
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

    diff = in0 - in1

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

    in0_amplitude = (
        np.percentile(
            in0,
            95,
        )
        -
        np.percentile(
            in0,
            5,
        )
    ) / 2.0

    in1_amplitude = (
        np.percentile(
            in1,
            95,
        )
        -
        np.percentile(
            in1,
            5,
        )
    ) / 2.0

    total = in0 + in1

    mean_sum = float(
        np.mean(total)
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

        "in0_amplitude_v":
            float(
                in0_amplitude
            ),

        "in1_amplitude_v":
            float(
                in1_amplitude
            ),

        "mean_sum_v":
            mean_sum,
    }


# ============================================================
# ZAPIS CSV
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
# POJEDYNCZE OKNO CIĄGŁE
#
# 3.5 s piezo = około 17.5° ruchu MPC
# ============================================================

def run_window(
    mpc,
    mdt,
    ads,
    moving_paddle,
    fixed_angle,
    start_angle,
    move_sign,
    piezo_up,
    orientation,
    line_id,
    window_id,
):

    samples = []

    start_t = time.monotonic()

    next_mpc = start_t
    next_piezo = start_t
    next_sample = start_t

    # ========================================================
    # POMIAR
    # ========================================================

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

        # ----------------------------------------------------
        # MPC
        #
        # WAŻNE:
        # target jest liczony od czasu.
        # Nie dodajemy kąta do aktualnego readbacku.
        # ----------------------------------------------------

        if now >= next_mpc:

            target = (
                start_angle
                +
                move_sign
                *
                MPC_SPEED_DEG_S
                *
                elapsed
            )

            target = max(
                MPC_MIN_DEG,
                min(
                    MPC_MAX_DEG,
                    target,
                )
            )

            mpc.move_absolute_units(
                moving_paddle,
                angle_to_command(
                    target
                ),
            )

            next_mpc = (
                now
                +
                MPC_COMMAND_INTERVAL_S
            )

        # ----------------------------------------------------
        # PIEZO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ADS
        # ----------------------------------------------------

        if now >= next_sample:

            in0, in1 = (
                ads.read_sample()
            )

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
                    "orientation":
                        orientation,

                    "line_id":
                        line_id,

                    "window_id":
                        window_id,

                    "time_in_window_s":
                        elapsed,

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
    # DOKŁADNY KONIEC PIEZO
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
    # METRYKI
    # ========================================================

    metrics = calculate_metrics(
        samples
    )

    p1_values = np.array(
        [
            x["p1_deg"]
            for x in samples
        ],
        dtype=float,
    )

    p2_values = np.array(
        [
            x["p2_deg"]
            for x in samples
        ],
        dtype=float,
    )

    if moving_paddle == 1:

        moving_values = p1_values

    else:

        moving_values = p2_values

    actual_span = abs(
        moving_values[-1]
        - moving_values[0]
    )

    actual_speed = (
        actual_span
        / HALF_CYCLE_TIME_S
    )

    summary = {
        "orientation":
            orientation,

        "line_id":
            line_id,

        "window_id":
            window_id,

        "fixed_angle_deg":
            fixed_angle,

        "moving_paddle":
            moving_paddle,

        "move_direction":
            (
                "positive"
                if move_sign > 0
                else "negative"
            ),

        "piezo_direction":
            (
                "up"
                if piezo_up
                else "down"
            ),

        "p1_start_deg":
            float(
                p1_values[0]
            ),

        "p1_end_deg":
            float(
                p1_values[-1]
            ),

        "p1_mean_deg":
            float(
                np.mean(
                    p1_values
                )
            ),

        "p1_min_deg":
            float(
                np.min(
                    p1_values
                )
            ),

        "p1_max_deg":
            float(
                np.max(
                    p1_values
                )
            ),

        "p2_start_deg":
            float(
                p2_values[0]
            ),

        "p2_end_deg":
            float(
                p2_values[-1]
            ),

        "p2_mean_deg":
            float(
                np.mean(
                    p2_values
                )
            ),

        "p2_min_deg":
            float(
                np.min(
                    p2_values
                )
            ),

        "p2_max_deg":
            float(
                np.max(
                    p2_values
                )
            ),

        "commanded_speed_deg_s":
            MPC_SPEED_DEG_S,

        "actual_span_deg":
            float(
                actual_span
            ),

        "actual_speed_deg_s":
            float(
                actual_speed
            ),

        "samples":
            len(samples),

        "diff_amplitude_v":
            metrics[
                "diff_amplitude_v"
            ],

        "score":
            metrics["score"],

        "in0_amplitude_v":
            metrics[
                "in0_amplitude_v"
            ],

        "in1_amplitude_v":
            metrics[
                "in1_amplitude_v"
            ],

        "mean_sum_v":
            metrics[
                "mean_sum_v"
            ],
    }

    return (
        summary,
        samples,
    )


# ============================================================
# POJEDYNCZA LINIA SKANU
# ============================================================

def run_scan_line(
    mpc,
    mdt,
    ads,
    orientation,
    line_id,
    fixed_angle,
    move_sign,
):

    # ========================================================
    # WYBÓR OSI
    # ========================================================

    if orientation == "horizontal":

        moving_paddle = 1

        if move_sign > 0:

            start_p1 = MPC_MIN_DEG

        else:

            start_p1 = MPC_MAX_DEG

        start_p2 = fixed_angle

    elif orientation == "vertical":

        moving_paddle = 2

        start_p1 = fixed_angle

        if move_sign > 0:

            start_p2 = MPC_MIN_DEG

        else:

            start_p2 = MPC_MAX_DEG

    else:

        raise ValueError(
            "Nieznana orientacja."
        )

    # ========================================================
    # USTAWIENIE POCZĄTKOWE
    # ========================================================

    actual_p1, actual_p2 = (
        move_both_and_wait(
            mpc,
            start_p1,
            start_p2,
        )
    )

    print()
    print(
        f"{orientation.upper()} "
        f"| linia {line_id}/9 "
        f"| fixed={fixed_angle:.1f}° "
        f"| kierunek="
        f"{'+' if move_sign > 0 else '-'}"
    )

    print(
        f"  start: "
        f"P1={actual_p1:.3f}° "
        f"P2={actual_p2:.3f}°"
    )

    # Każdą linię zaczynamy z piezo od 80 V.
    # Dzięki temu linie są porównywalne.

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

    piezo_up = True

    windows = []
    raw_rows = []

    window_id = 0

    # ========================================================
    # SKAN
    # ========================================================

    while True:

        current = read_paddle_angle(
            mpc,
            moving_paddle,
        )

        if move_sign > 0:

            remaining = (
                MPC_MAX_DEG
                - current
            )

        else:

            remaining = (
                current
                - MPC_MIN_DEG
            )

        # Tylko pełne półcykle.
        #
        # Przy 5°/s potrzebujemy około 17.5°
        # przestrzeni na jedno okno.

        if remaining < (
            WINDOW_ANGLE_DEG
            * 0.95
        ):
            break

        window_id += 1

        summary, samples = run_window(
            mpc=mpc,
            mdt=mdt,
            ads=ads,

            moving_paddle=
                moving_paddle,

            fixed_angle=
                fixed_angle,

            start_angle=
                current,

            move_sign=
                move_sign,

            piezo_up=
                piezo_up,

            orientation=
                orientation,

            line_id=
                line_id,

            window_id=
                window_id,
        )

        piezo_up = not piezo_up

        windows.append(
            summary
        )

        raw_rows.extend(
            samples
        )

        print(
            f"  W{window_id:02d} | "
            f"P1={summary['p1_mean_deg']:7.2f}° | "
            f"P2={summary['p2_mean_deg']:7.2f}° | "
            f"A_D={summary['diff_amplitude_v']:.6f} V | "
            f"span={summary['actual_span_deg']:.2f}° | "
            f"v={summary['actual_speed_deg_s']:.2f}°/s"
        )

    # ========================================================
    # DOJAZD DO KOŃCA LINII - BEZ POMIARU
    # ========================================================

    if orientation == "horizontal":

        end_p1 = (
            MPC_MAX_DEG
            if move_sign > 0
            else MPC_MIN_DEG
        )

        end_p2 = fixed_angle

    else:

        end_p1 = fixed_angle

        end_p2 = (
            MPC_MAX_DEG
            if move_sign > 0
            else MPC_MIN_DEG
        )

    move_both_and_wait(
        mpc,
        end_p1,
        end_p2,
    )

    print(
        f"  Koniec linii. "
        f"Okien: {len(windows)}"
    )

    return (
        windows,
        raw_rows,
    )


# ============================================================
# CAŁA ORIENTACJA
# ============================================================

def run_orientation(
    mpc,
    mdt,
    ads,
    orientation,
):

    print()
    print("=" * 80)

    if orientation == "horizontal":

        print(
            "SKANY POZIOME — RUCH P1"
        )

    else:

        print(
            "SKANY PIONOWE — RUCH P2"
        )

    print("=" * 80)

    all_windows = []
    all_raw = []

    # Krótka kondycja przed całą orientacją.

    condition_piezo(
        mdt
    )

    for index, fixed_angle in enumerate(
        FIXED_ANGLES,
        start=1,
    ):

        # Serpentyna:
        #
        # linia 1: 1 -> 160
        # linia 2: 160 -> 1
        # linia 3: 1 -> 160
        # ...

        if index % 2 == 1:

            move_sign = +1

        else:

            move_sign = -1

        windows, raw = run_scan_line(
            mpc=mpc,
            mdt=mdt,
            ads=ads,

            orientation=
                orientation,

            line_id=
                index,

            fixed_angle=
                fixed_angle,

            move_sign=
                move_sign,
        )

        all_windows.extend(
            windows
        )

        all_raw.extend(
            raw
        )

    return (
        all_windows,
        all_raw,
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
            "REFERENCJA KRZYŻOWA POLARYZACJI"
        )
        print("=" * 80)

        print(
            f"MPC: "
            f"{MPC_SPEED_DEG_S:.1f}°/s"
        )

        print(
            f"Piezo: "
            f"{PIEZO_MIN_V:.0f}"
            f"–"
            f"{PIEZO_MAX_V:.0f} V "
            f"@ "
            f"{PIEZO_SPEED_V_S:.1f} V/s"
        )

        print(
            f"Półcykl piezo: "
            f"{HALF_CYCLE_TIME_S:.2f} s"
        )

        print(
            f"Jedno okno obejmuje około: "
            f"{WINDOW_ANGLE_DEG:.1f}°"
        )

        print(
            f"Liczba linii poziomych: "
            f"{len(FIXED_ANGLES)}"
        )

        print(
            f"Liczba linii pionowych: "
            f"{len(FIXED_ANGLES)}"
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
        # ADS
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
        # POZIOME
        # ====================================================

        horizontal_windows, horizontal_raw = (
            run_orientation(
                mpc,
                mdt,
                ads,
                "horizontal",
            )
        )

        save_csv(
            OUTPUT_DIR
            / "horizontal_windows.csv",
            horizontal_windows,
        )

        save_csv(
            OUTPUT_DIR
            / "horizontal_raw.csv",
            horizontal_raw,
        )

        print()
        print(
            "Skany poziome zapisane."
        )

        # ====================================================
        # PIONOWE
        # ====================================================

        vertical_windows, vertical_raw = (
            run_orientation(
                mpc,
                mdt,
                ads,
                "vertical",
            )
        )

        save_csv(
            OUTPUT_DIR
            / "vertical_windows.csv",
            vertical_windows,
        )

        save_csv(
            OUTPUT_DIR
            / "vertical_raw.csv",
            vertical_raw,
        )

        print()
        print(
            "Skany pionowe zapisane."
        )

        # ====================================================
        # WSPÓLNY PLIK
        # ====================================================

        combined_windows = (
            horizontal_windows
            +
            vertical_windows
        )

        combined_raw = (
            horizontal_raw
            +
            vertical_raw
        )

        save_csv(
            OUTPUT_DIR
            / "combined_windows.csv",
            combined_windows,
        )

        save_csv(
            OUTPUT_DIR
            / "combined_raw.csv",
            combined_raw,
        )

        # ====================================================
        # PODSUMOWANIE
        # ====================================================

        print()
        print("=" * 80)
        print(
            "POMIAR ZAKOŃCZONY"
        )
        print("=" * 80)

        print(
            f"Poziome okna: "
            f"{len(horizontal_windows)}"
        )

        print(
            f"Pionowe okna: "
            f"{len(vertical_windows)}"
        )

        print(
            f"Łącznie: "
            f"{len(combined_windows)}"
        )

        if combined_windows:

            amplitudes = np.array(
                [
                    x[
                        "diff_amplitude_v"
                    ]
                    for x
                    in combined_windows
                ],
                dtype=float,
            )

            best_index = int(
                np.nanargmax(
                    amplitudes
                )
            )

            best = (
                combined_windows[
                    best_index
                ]
            )

            print()

            print(
                "Najlepsze okno:"
            )

            print(
                f"  orientacja: "
                f"{best['orientation']}"
            )

            print(
                f"  P1 średnie: "
                f"{best['p1_mean_deg']:.2f}°"
            )

            print(
                f"  P2 średnie: "
                f"{best['p2_mean_deg']:.2f}°"
            )

            print(
                f"  A_D: "
                f"{best['diff_amplitude_v']:.6f} V"
            )

            print(
                f"  rzeczywista prędkość: "
                f"{best['actual_speed_deg_s']:.3f}°/s"
            )

        print()

        print(
            "Wyniki:"
        )

        print(
            OUTPUT_DIR
        )

    finally:

        print()
        print(
            "Zamykanie urządzeń..."
        )

        # Piezo -> 80 V

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