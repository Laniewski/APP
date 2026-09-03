import argparse
import csv
import math
import time
from datetime import datetime
from pathlib import Path

from modules.mdt694b.driver import MDT694BDriver
from modules.measurement.driver import ADS1263Driver

from modules.mpc220.calibration import (
    MPC_MIN_ANGLE_DEG,
    MPC_MAX_ANGLE_DEG,
    angle_to_command,
    raw_position_to_angle,
)

from modules.mpc220.driver import MPC220Driver


# ============================================================
# KONFIGURACJA
# ============================================================

OUTPUT_DIR = Path("fast_polarization_results")


# ------------------------------------------------------------
# PIEZO
# ------------------------------------------------------------

PIEZO_MIN_V = 20.0
PIEZO_MAX_V = 90.0

# właściwy pomiar
PIEZO_SCAN_SPEED_V_S = 20.0

# szybki powrót bez pomiaru
PIEZO_RETURN_SPEED_V_S = 40.0

PIEZO_COMMAND_INTERVAL_S = 0.05


# ------------------------------------------------------------
# ADS
# ------------------------------------------------------------

SAMPLE_INTERVAL_S = 0.20


# ------------------------------------------------------------
# MPC
# ------------------------------------------------------------

MPC_SETTLE_S = 0.20


# ------------------------------------------------------------
# SEARCH
# ------------------------------------------------------------

# Pełna przestrzeń:
# 1, 41, 81, 121, 160
COARSE_STEP_DEG = 40.0

# Kolejne kroki lokalnego szukania
LOCAL_STEPS_DEG = [
    20.0,
    10.0,
    5.0,
    2.0,
]

# Ile razy mierzymy końcowy wynik
FINAL_REPEATS = 3


# ------------------------------------------------------------
# REFERENCJA Z PEŁNEGO GRIDU
# ------------------------------------------------------------

REFERENCE_SCORE = 0.105021097
REFERENCE_DIFF_AMPLITUDE_V = 0.445485966


# ============================================================
# MATEMATYKA
# ============================================================

def percentile(values, p):

    values = sorted(values)

    if not values:
        raise ValueError("Brak danych.")

    if len(values) == 1:
        return values[0]

    position = (
        (len(values) - 1)
        * p
    )

    low = math.floor(
        position
    )

    high = math.ceil(
        position
    )

    if low == high:
        return values[low]

    fraction = (
        position - low
    )

    return (
        values[low]
        * (1.0 - fraction)
        + values[high]
        * fraction
    )


def robust_amplitude(values):

    if len(values) < 5:

        raise RuntimeError(
            "Za mało próbek: "
            f"{len(values)}"
        )

    p05 = percentile(
        values,
        0.05,
    )

    p95 = percentile(
        values,
        0.95,
    )

    return (
        p95 - p05
    ) / 2.0


# ============================================================
# MPC220
# ============================================================

def clamp_angle(angle):

    return max(
        MPC_MIN_ANGLE_DEG,
        min(
            MPC_MAX_ANGLE_DEG,
            angle,
        ),
    )


def read_angle(
    mpc,
    paddle,
):

    raw = (
        mpc.read_position_units(
            paddle
        )
    )

    angle = (
        raw_position_to_angle(
            raw
        )
    )

    return clamp_angle(
        angle
    )


def move_paddle(
    mpc,
    paddle,
    angle,
):

    target = clamp_angle(
        angle
    )

    command = (
        angle_to_command(
            target
        )
    )

    mpc.move_absolute_units(
        paddle,
        command,
    )

    mpc.wait_until_stopped(
        paddle
    )

    return read_angle(
        mpc,
        paddle,
    )


def move_mpc(
    mpc,
    angle1,
    angle2,
):

    actual1 = move_paddle(
        mpc,
        1,
        angle1,
    )

    actual2 = move_paddle(
        mpc,
        2,
        angle2,
    )

    time.sleep(
        MPC_SETTLE_S
    )

    return (
        actual1,
        actual2,
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


def move_piezo(
    mdt,
    start_v,
    target_v,
    speed_v_s,
):

    distance = abs(
        target_v - start_v
    )

    if distance < 0.001:

        fast_set_voltage(
            mdt,
            target_v,
        )

        return

    direction = (
        1.0
        if target_v > start_v
        else -1.0
    )

    duration = (
        distance
        / speed_v_s
    )

    start_time = (
        time.monotonic()
    )

    while True:

        elapsed = (
            time.monotonic()
            - start_time
        )

        if elapsed >= duration:
            break

        voltage = (
            start_v
            + direction
            * speed_v_s
            * elapsed
        )

        fast_set_voltage(
            mdt,
            voltage,
        )

        time.sleep(
            PIEZO_COMMAND_INTERVAL_S
        )

    fast_set_voltage(
        mdt,
        target_v,
    )


# ============================================================
# POMIAR JEDNEJ POZYCJI MPC
# ============================================================

def measure_score(
    adc,
    mdt,
    raw_writer,
    program_start,
    point_id,
    angle1,
    angle2,
):

    in0_values = []
    in1_values = []

    diff_values = []
    normalized_values = []
    sum_values = []

    # --------------------------------------------
    # Start piezo
    # --------------------------------------------

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        0.15
    )

    scan_duration = (
        PIEZO_MAX_V
        - PIEZO_MIN_V
    ) / PIEZO_SCAN_SPEED_V_S

    scan_start = (
        time.monotonic()
    )

    next_voltage_time = (
        scan_start
    )

    next_sample_time = (
        scan_start
    )

    # --------------------------------------------
    # Skan 20 -> 90 V
    # --------------------------------------------

    while True:

        now = (
            time.monotonic()
        )

        elapsed = (
            now - scan_start
        )

        if elapsed >= scan_duration:
            break

        # ----------------------------
        # Piezo
        # ----------------------------

        if now >= next_voltage_time:

            voltage = (
                PIEZO_MIN_V
                + PIEZO_SCAN_SPEED_V_S
                * elapsed
            )

            voltage = min(
                voltage,
                PIEZO_MAX_V,
            )

            fast_set_voltage(
                mdt,
                voltage,
            )

            next_voltage_time += (
                PIEZO_COMMAND_INTERVAL_S
            )

        # ----------------------------
        # ADS
        # ----------------------------

        if now >= next_sample_time:

            in0, in1 = (
                adc.read_sample()
            )

            relative_time = (
                time.monotonic()
                - program_start
            )

            raw_writer.writerow(
                [
                    f"{relative_time:.6f}",
                    f"{in0:.6f}",
                    f"{in1:.6f}",
                    point_id,
                    f"{angle1:.3f}",
                    f"{angle2:.3f}",
                ]
            )

            in0_values.append(
                in0
            )

            in1_values.append(
                in1
            )

            difference = (
                in0 - in1
            )

            total = (
                in0 + in1
            )

            diff_values.append(
                difference
            )

            sum_values.append(
                total
            )

            if abs(total) > 1e-9:

                normalized_values.append(
                    difference
                    / total
                )

            next_sample_time += (
                SAMPLE_INTERVAL_S
            )

        time.sleep(
            0.002
        )

    fast_set_voltage(
        mdt,
        PIEZO_MAX_V,
    )

    # --------------------------------------------
    # Metryki
    # --------------------------------------------

    diff_amplitude = (
        robust_amplitude(
            diff_values
        )
    )

    score = (
        robust_amplitude(
            normalized_values
        )
    )

    in0_amplitude = (
        robust_amplitude(
            in0_values
        )
    )

    in1_amplitude = (
        robust_amplitude(
            in1_values
        )
    )

    mean_sum = (
        sum(sum_values)
        / len(sum_values)
    )

    # --------------------------------------------
    # Szybki powrót piezo
    # --------------------------------------------

    move_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_RETURN_SPEED_V_S,
    )

    return {
        "score":
            score,

        "diff_amplitude_v":
            diff_amplitude,

        "in0_amplitude_v":
            in0_amplitude,

        "in1_amplitude_v":
            in1_amplitude,

        "mean_sum_v":
            mean_sum,

        "samples":
            len(in0_values),
    }


# ============================================================
# GENEROWANIE COARSE GRID
# ============================================================

def create_coarse_angles():

    angles = []

    value = (
        MPC_MIN_ANGLE_DEG
    )

    while (
        value
        < MPC_MAX_ANGLE_DEG
    ):

        angles.append(
            round(
                value,
                3,
            )
        )

        value += (
            COARSE_STEP_DEG
        )

    if (
        MPC_MAX_ANGLE_DEG
        not in angles
    ):

        angles.append(
            MPC_MAX_ANGLE_DEG
        )

    return angles


# ============================================================
# MAIN
# ============================================================

def main():

    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--mpc-port",
        default="/dev/ttyUSB0",
    )

    parser.add_argument(
        "--mdt-port",
        default="/dev/ttyACM0",
    )

    args = (
        parser.parse_args()
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    report_path = (
        OUTPUT_DIR
        / f"fast_search_report_{timestamp}.csv"
    )

    raw_path = (
        OUTPUT_DIR
        / f"fast_search_raw_{timestamp}.csv"
    )

    mpc = None
    mdt = None
    adc = None

    program_start = (
        time.monotonic()
    )

    # Cache wyników:
    #
    # (angle1, angle2) -> result
    #
    measured = {}

    all_results = []

    point_counter = 0

    # ========================================================
    # Funkcja pomocnicza do pomiaru pozycji
    # ========================================================

    def evaluate(
        angle1,
        angle2,
        stage,
        report_writer,
        raw_writer,
        force=False,
    ):

        nonlocal point_counter

        target1 = round(
            clamp_angle(
                angle1
            ),
            3,
        )

        target2 = round(
            clamp_angle(
                angle2
            ),
            3,
        )

        cache_key = (
            round(target1, 2),
            round(target2, 2),
        )

        # ----------------------------------------
        # Jeżeli już mierzyliśmy ten punkt
        # ----------------------------------------

        if (
            cache_key in measured
            and not force
        ):

            return measured[
                cache_key
            ]

        point_counter += 1

        print()
        print(
            "=" * 70
        )

        print(
            f"POMIAR {point_counter}"
        )

        print(
            f"Etap: {stage}"
        )

        print(
            f"Cel: "
            f"P1={target1:.2f}°, "
            f"P2={target2:.2f}°"
        )

        point_start = (
            time.monotonic()
            - program_start
        )

        # ----------------------------------------
        # MPC
        # ----------------------------------------

        actual1, actual2 = (
            move_mpc(
                mpc,
                target1,
                target2,
            )
        )

        print(
            f"Rzeczywiste: "
            f"P1={actual1:.2f}°, "
            f"P2={actual2:.2f}°"
        )

        # ----------------------------------------
        # Pomiar
        # ----------------------------------------

        result = measure_score(
            adc=adc,
            mdt=mdt,
            raw_writer=raw_writer,
            program_start=program_start,
            point_id=point_counter,
            angle1=actual1,
            angle2=actual2,
        )

        point_end = (
            time.monotonic()
            - program_start
        )

        result.update(
            {
                "point_id":
                    point_counter,

                "stage":
                    stage,

                "angle1_deg":
                    actual1,

                "angle2_deg":
                    actual2,

                "start_s":
                    point_start,

                "end_s":
                    point_end,
            }
        )

        measured[
            cache_key
        ] = result

        all_results.append(
            result
        )

        report_writer.writerow(
            [
                point_counter,
                stage,

                f"{actual1:.3f}",
                f"{actual2:.3f}",

                f"{result['score']:.9f}",

                f"{result['diff_amplitude_v']:.9f}",

                f"{result['in0_amplitude_v']:.9f}",

                f"{result['in1_amplitude_v']:.9f}",

                f"{result['mean_sum_v']:.9f}",

                result["samples"],

                f"{point_start:.6f}",
                f"{point_end:.6f}",
            ]
        )

        print(
            f"SCORE = "
            f"{result['score']:.6f}"
        )

        print(
            f"A_diff = "
            f"{result['diff_amplitude_v']:.6f} V"
        )

        print(
            f"Vs referencja = "
            f"{100.0 * result['diff_amplitude_v'] / REFERENCE_DIFF_AMPLITUDE_V:.1f}%"
        )

        return result


    try:

        # ====================================================
        # CONNECT
        # ====================================================

        print(
            "Łączenie MPC220..."
        )

        mpc = (
            MPC220Driver(
                args.mpc_port
            )
        )

        mpc.connect()

        print(
            "MPC220 OK"
        )

        print(
            "Łączenie MDT694B..."
        )

        mdt = (
            MDT694BDriver(
                args.mdt_port
            )
        )

        mdt.connect()

        allowed_min_v, allowed_max_v = (
            mdt.read_voltage_range()
        )

        if (
            PIEZO_MIN_V
            < allowed_min_v
            or PIEZO_MAX_V
            > allowed_max_v
        ):

            raise RuntimeError(
                "Zakres piezo poza "
                "dozwolonym zakresem MDT694B."
            )

        print(
            f"MDT694B OK | "
            f"{allowed_min_v:.1f}-"
            f"{allowed_max_v:.1f} V"
        )

        print(
            "Łączenie ADS1263..."
        )

        adc = (
            ADS1263Driver()
        )

        adc.connect()

        adc.start_measurement()

        print(
            "ADS1263 OK"
        )

        # ====================================================
        # CSV
        # ====================================================

        with open(
            report_path,
            "w",
            encoding="utf-8",
            newline="",
        ) as report_file, open(
            raw_path,
            "w",
            encoding="utf-8",
            newline="",
        ) as raw_file:

            report_writer = (
                csv.writer(
                    report_file
                )
            )

            raw_writer = (
                csv.writer(
                    raw_file
                )
            )

            report_writer.writerow(
                [
                    "point_id",
                    "stage",

                    "angle1_deg",
                    "angle2_deg",

                    "score",

                    "diff_amplitude_v",

                    "in0_amplitude_v",
                    "in1_amplitude_v",

                    "mean_sum_v",

                    "samples",

                    "start_s",
                    "end_s",
                ]
            )

            raw_writer.writerow(
                [
                    "time_s",
                    "in0_v",
                    "in1_v",

                    "point_id",

                    "angle1_deg",
                    "angle2_deg",
                ]
            )

            # =================================================
            # ETAP 1 — COARSE GRID
            # =================================================

            print()
            print(
                "#" * 70
            )

            print(
                "ETAP 1: COARSE SEARCH"
            )

            print(
                "#" * 70
            )

            coarse_angles = (
                create_coarse_angles()
            )

            print(
                f"Kąty coarse: "
                f"{coarse_angles}"
            )

            best = None

            for row_index, angle1 in enumerate(
                coarse_angles
            ):

                if (
                    row_index % 2
                    == 0
                ):

                    angle2_list = (
                        coarse_angles
                    )

                else:

                    angle2_list = list(
                        reversed(
                            coarse_angles
                        )
                    )

                for angle2 in angle2_list:

                    result = evaluate(
                        angle1,
                        angle2,
                        "coarse",
                        report_writer,
                        raw_writer,
                    )

                    if (
                        best is None
                        or result["score"]
                        > best["score"]
                    ):

                        best = result

                    report_file.flush()
                    raw_file.flush()

            print()
            print(
                "Najlepszy COARSE:"
            )

            print(
                f"P1={best['angle1_deg']:.2f}°, "
                f"P2={best['angle2_deg']:.2f}°, "
                f"score={best['score']:.6f}"
            )

            # =================================================
            # ETAP 2 — LOCAL COORDINATE SEARCH
            # =================================================

            print()
            print(
                "#" * 70
            )

            print(
                "ETAP 2: LOCAL SEARCH"
            )

            print(
                "#" * 70
            )

            current = best

            for step in LOCAL_STEPS_DEG:

                print()
                print(
                    f"--- krok lokalny "
                    f"{step:.1f}° ---"
                )

                improved = True

                while improved:

                    improved = False

                    center1 = (
                        current[
                            "angle1_deg"
                        ]
                    )

                    center2 = (
                        current[
                            "angle2_deg"
                        ]
                    )

                    candidates = [
                        (
                            center1 + step,
                            center2,
                        ),
                        (
                            center1 - step,
                            center2,
                        ),
                        (
                            center1,
                            center2 + step,
                        ),
                        (
                            center1,
                            center2 - step,
                        ),
                    ]

                    best_candidate = (
                        current
                    )

                    for (
                        candidate1,
                        candidate2,
                    ) in candidates:

                        candidate1 = (
                            clamp_angle(
                                candidate1
                            )
                        )

                        candidate2 = (
                            clamp_angle(
                                candidate2
                            )
                        )

                        result = evaluate(
                            candidate1,
                            candidate2,
                            f"local_{step:g}deg",
                            report_writer,
                            raw_writer,
                        )

                        if (
                            result["score"]
                            > best_candidate[
                                "score"
                            ]
                        ):

                            best_candidate = (
                                result
                            )

                    if (
                        best_candidate[
                            "score"
                        ]
                        > current["score"]
                    ):

                        improvement = (
                            best_candidate[
                                "score"
                            ]
                            - current[
                                "score"
                            ]
                        )

                        relative_improvement = (
                            improvement
                            / current["score"]
                        )

                        current = (
                            best_candidate
                        )

                        # Nawet małą poprawę przyjmujemy,
                        # ale wymagamy ~0.5%, aby od razu
                        # kontynuować w tym samym kroku.
                        if (
                            relative_improvement
                            > 0.005
                        ):

                            improved = True

                        print(
                            f"Nowy najlepszy: "
                            f"P1={current['angle1_deg']:.2f}°, "
                            f"P2={current['angle2_deg']:.2f}°, "
                            f"score={current['score']:.6f}"
                        )

                print(
                    f"Po kroku {step:.1f}°: "
                    f"P1={current['angle1_deg']:.2f}°, "
                    f"P2={current['angle2_deg']:.2f}°"
                )

            # =================================================
            # ETAP 3 — POWTÓRZENIA KOŃCOWE
            # =================================================

            print()
            print(
                "#" * 70
            )

            print(
                "ETAP 3: FINAL CONFIRMATION"
            )

            print(
                "#" * 70
            )

            final_results = []

            for repeat in range(
                FINAL_REPEATS
            ):

                print(
                    f"\nPowtórzenie "
                    f"{repeat + 1}/"
                    f"{FINAL_REPEATS}"
                )

                result = evaluate(
                    current[
                        "angle1_deg"
                    ],
                    current[
                        "angle2_deg"
                    ],
                    f"final_{repeat + 1}",
                    report_writer,
                    raw_writer,
                    force=True,
                )

                final_results.append(
                    result
                )

            final_score = (
                sum(
                    item["score"]
                    for item
                    in final_results
                )
                / len(final_results)
            )

            final_diff = (
                sum(
                    item[
                        "diff_amplitude_v"
                    ]
                    for item
                    in final_results
                )
                / len(final_results)
            )

            elapsed_total = (
                time.monotonic()
                - program_start
            )

            # =================================================
            # WYNIK
            # =================================================

            print()
            print(
                "=" * 70
            )

            print(
                "WYNIK SZYBKIEGO ALGORYTMU"
            )

            print(
                "=" * 70
            )

            print(
                f"Paddle 1: "
                f"{current['angle1_deg']:.3f}°"
            )

            print(
                f"Paddle 2: "
                f"{current['angle2_deg']:.3f}°"
            )

            print()
            print(
                f"Średni final score: "
                f"{final_score:.9f}"
            )

            print(
                f"Średnia final amplitude: "
                f"{final_diff:.9f} V"
            )

            print()
            print(
                f"Referencyjna amplituda: "
                f"{REFERENCE_DIFF_AMPLITUDE_V:.9f} V"
            )

            quality_percent = (
                100.0
                * final_diff
                / REFERENCE_DIFF_AMPLITUDE_V
            )

            print(
                f"Jakość względem "
                f"pełnego gridu: "
                f"{quality_percent:.2f}%"
            )

            print(
                f"Liczba wykonanych "
                f"pomiarów: "
                f"{point_counter}"
            )

            print(
                f"Całkowity czas: "
                f"{elapsed_total:.1f} s "
                f"({elapsed_total / 60.0:.2f} min)"
            )

            # ---------------------------------------------
            # Zostawiamy MPC w znalezionym optimum
            # ---------------------------------------------

            move_mpc(
                mpc,
                current[
                    "angle1_deg"
                ],
                current[
                    "angle2_deg"
                ],
            )

            print()
            print(
                "MPC pozostawiony "
                "w znalezionym optimum."
            )

            print()
            print(
                f"Raport: {report_path}"
            )

            print(
                f"Raw:    {raw_path}"
            )

    except KeyboardInterrupt:

        print()
        print(
            "Test przerwany."
        )

    finally:

        # ====================================================
        # Bezpieczny powrót piezo
        # ====================================================

        if mdt is not None:

            try:

                current_voltage = (
                    mdt.read_voltage()
                )

                move_piezo(
                    mdt,
                    current_voltage,
                    PIEZO_MIN_V,
                    10.0,
                )

            except Exception as exc:

                print(
                    "Nie udało się "
                    f"cofnąć piezo: {exc}"
                )

        # ====================================================
        # CLOSE
        # ====================================================

        if adc is not None:

            try:
                adc.stop_measurement()
            except Exception:
                pass

            try:
                adc.close()
            except Exception:
                pass

        if mdt is not None:

            try:
                mdt.disconnect()
            except Exception:
                pass

        if mpc is not None:

            try:
                mpc.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()