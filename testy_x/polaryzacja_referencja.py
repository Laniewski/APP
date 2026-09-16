import argparse
import csv
import math
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
# KONFIGURACJA TESTU V2
# ============================================================

# Piezo
PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0

# Prędkość właściwego skanu pomiarowego
PIEZO_SPEED_V_S = 20.0

# Prędkość powrotu do 80 V
PIEZO_RETURN_SPEED_V_S = 20.0

# Jak często wysyłamy nowe napięcie do MDT694B
PIEZO_COMMAND_INTERVAL_S = 0.05


# ADS1263
# Około 5 próbek/s
SAMPLE_INTERVAL_S = 0.20


# MPC220
MPC_SETTLE_S = 0.20

# Coarse grid:
# około 1, 21, 41, ..., 160 stopni
COARSE_STEP_DEG = 20.0


# Folder wyników
OUTPUT_DIR = ROOT_DIR / "dane/polarization_reference"


def next_attempt_number():
    attempts = []
    for path in OUTPUT_DIR.glob("polarization_reference_*_*.csv"):
        parts = path.stem.split("_")
        if len(parts) >= 6 and parts[-3].isdigit():
            attempts.append(int(parts[-3]))
    return max(attempts, default=0) + 1


# ============================================================
# FUNKCJE MATEMATYCZNE
# ============================================================

def percentile(values, p):
    """
    Oblicza percentyl bez używania numpy.
    """

    values = sorted(values)

    if not values:
        raise ValueError("Brak danych.")

    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * p

    low = math.floor(position)
    high = math.ceil(position)

    if low == high:
        return values[low]

    fraction = position - low

    return (
        values[low] * (1.0 - fraction)
        + values[high] * fraction
    )


def robust_amplitude(values):
    """
    Odporna amplituda:

        A = (P95 - P05) / 2

    Percentyle są używane zamiast zwykłych min/max,
    żeby pojedynczy błędny pik nie zawyżył wyniku.
    """

    if len(values) < 5:
        raise RuntimeError(
            f"Za mało próbek do policzenia amplitudy: {len(values)}"
        )

    p05 = percentile(values, 0.05)
    p95 = percentile(values, 0.95)

    return (p95 - p05) / 2.0


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


def read_angle(mpc, paddle):
    raw_position = mpc.read_position_units(
        paddle
    )

    angle = raw_position_to_angle(
        raw_position
    )

    return clamp_angle(angle)


def move_paddle(
    mpc,
    paddle,
    angle,
):
    angle = clamp_angle(angle)

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

    return actual1, actual2


# ============================================================
# MDT694B / PIEZO
# ============================================================

def fast_set_voltage(
    mdt,
    voltage,
):
    """
    Szybka zmiana napięcia bez każdorazowego
    odczytywania limitów MDT694B.
    """

    mdt._send_command(
        f"xvoltage={voltage:.3f}"
    )


def move_piezo(
    mdt,
    start_v,
    target_v,
    speed_v_s,
):
    """
    Liniowa zmiana napięcia piezo.
    """

    distance = abs(
        target_v - start_v
    )

    if distance < 0.001:
        fast_set_voltage(
            mdt,
            target_v,
        )
        return

    duration = (
        distance
        / speed_v_s
    )

    direction = (
        1.0
        if target_v > start_v
        else -1.0
    )

    start_time = time.monotonic()

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
# POMIAR JEDNEGO PUNKTU POLARYZACJI
# ============================================================

def measure_polarization_point(
    adc,
    mdt,
    measurement_writer,
    program_start,
):
    in0_values = []
    in1_values = []

    diff_values = []
    normalized_values = []
    sum_values = []

    # --------------------------------------------------------
    # Ustawienie piezo na 80 V
    # --------------------------------------------------------

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(0.20)

    # --------------------------------------------------------
    # Czas skanu
    #
    # 80 -> 150 V
    # 70 V / 20 V/s = 3.5 s
    # --------------------------------------------------------

    ramp_duration = (
        PIEZO_MAX_V
        - PIEZO_MIN_V
    ) / PIEZO_SPEED_V_S

    ramp_start = time.monotonic()

    next_command_time = ramp_start
    next_sample_time = ramp_start

    # --------------------------------------------------------
    # SKAN 80 -> 150 V + ADS1263
    # --------------------------------------------------------

    while True:
        now = time.monotonic()

        elapsed = (
            now
            - ramp_start
        )

        if elapsed >= ramp_duration:
            break

        # ====================================================
        # PIEZO
        # ====================================================

        if now >= next_command_time:
            voltage = (
                PIEZO_MIN_V
                + PIEZO_SPEED_V_S
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

            next_command_time += (
                PIEZO_COMMAND_INTERVAL_S
            )

        # ====================================================
        # ADS1263
        # ====================================================

        if now >= next_sample_time:
            in0, in1 = adc.read_sample()

            relative_time = (
                time.monotonic()
                - program_start
            )

            # Format kompatybilny z aplikacją
            measurement_writer.writerow(
                [
                    f"{relative_time:.6f}",
                    f"{in0:.6f}",
                    f"{in1:.6f}",
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
                    difference / total
                )

            next_sample_time += (
                SAMPLE_INTERVAL_S
            )

        time.sleep(0.002)

    # Kończymy dokładnie na 150 V
    fast_set_voltage(
        mdt,
        PIEZO_MAX_V,
    )

    # --------------------------------------------------------
    # OBLICZENIA
    # --------------------------------------------------------

    diff_amplitude = robust_amplitude(
        diff_values
    )

    normalized_score = robust_amplitude(
        normalized_values
    )

    in0_amplitude = robust_amplitude(
        in0_values
    )

    in1_amplitude = robust_amplitude(
        in1_values
    )

    mean_sum = (
        sum(sum_values)
        / len(sum_values)
    )

    # --------------------------------------------------------
    # Powrót piezo 150 -> 80 V
    # --------------------------------------------------------

    move_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_RETURN_SPEED_V_S,
    )

    return {
        "score": normalized_score,
        "diff_amplitude_v": diff_amplitude,
        "in0_amplitude_v": in0_amplitude,
        "in1_amplitude_v": in1_amplitude,
        "mean_sum_v": mean_sum,
        "samples": len(in0_values),
    }


# ============================================================
# GENEROWANIE SIATKI 9x9
# ============================================================

def create_angles():
    angles = []

    value = MPC_MIN_ANGLE_DEG

    while value <= MPC_MAX_ANGLE_DEG:
        angles.append(
            round(
                value,
                3,
            )
        )

        value += COARSE_STEP_DEG

    # Dodaj dokładnie górną granicę 160°
    if angles[-1] != MPC_MAX_ANGLE_DEG:
        angles.append(
            MPC_MAX_ANGLE_DEG
        )

    return angles


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Polarization reference search V2 "
            "- 81 point MPC220 grid, "
            "piezo scan 80-150 V."
        )
    )

    parser.add_argument(
        "--mpc-port",
        default="/dev/ttyUSB0",
        help="Port MPC220",
    )

    parser.add_argument(
        "--mdt-port",
        default="/dev/ttyACM0",
        help="Port MDT694B",
    )

    args = parser.parse_args()

    # ========================================================
    # PLIKI
    # ========================================================

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    attempt = next_attempt_number()

    measurement_path = (
        OUTPUT_DIR
        / f"polarization_reference_raw_{attempt:02d}_{timestamp}.csv"
    )

    report_path = (
        OUTPUT_DIR
        / f"polarization_reference_report_{attempt:02d}_{timestamp}.csv"
    )

    # ========================================================
    # URZĄDZENIA
    # ========================================================

    mpc = None
    mdt = None
    adc = None

    all_results = []

    program_start = time.monotonic()

    try:
        # ====================================================
        # MPC220
        # ====================================================

        print()
        print("Łączenie MPC220...")

        mpc = MPC220Driver(
            args.mpc_port
        )

        mpc.connect()

        print("MPC220 OK")

        # ====================================================
        # MDT694B
        # ====================================================

        print("Łączenie MDT694B...")

        mdt = MDT694BDriver(
            args.mdt_port
        )

        mdt.connect()

        allowed_min_v, allowed_max_v = (
            mdt.read_voltage_range()
        )

        print(
            f"MDT694B OK | "
            f"zakres: "
            f"{allowed_min_v:.1f} - "
            f"{allowed_max_v:.1f} V"
        )

        # ----------------------------------------------------
        # Sprawdzenie bezpieczeństwa zakresu
        # ----------------------------------------------------

        if PIEZO_MIN_V < allowed_min_v:
            raise RuntimeError(
                f"PIEZO_MIN_V={PIEZO_MIN_V} V "
                f"jest poniżej zakresu MDT694B."
            )

        if PIEZO_MAX_V > allowed_max_v:
            raise RuntimeError(
                f"PIEZO_MAX_V={PIEZO_MAX_V} V "
                f"jest powyżej zakresu MDT694B."
            )

        # ====================================================
        # ADS1263
        # ====================================================

        print("Łączenie ADS1263...")

        adc = ADS1263Driver()

        adc.connect()
        adc.start_measurement()

        print("ADS1263 OK")

        # ====================================================
        # CSV
        # ====================================================

        with open(
            measurement_path,
            "w",
            encoding="utf-8",
            newline="",
        ) as measurement_file, open(
            report_path,
            "w",
            encoding="utf-8",
            newline="",
        ) as report_file:

            measurement_writer = csv.writer(
                measurement_file
            )

            report_writer = csv.writer(
                report_file
            )

            # ------------------------------------------------
            # RAW ADS
            # ------------------------------------------------

            measurement_writer.writerow(
                [
                    "time_s",
                    "in0_v",
                    "in1_v",
                ]
            )

            # ------------------------------------------------
            # RAPORT
            # ------------------------------------------------

            report_writer.writerow(
                [
                    "point_id",
                    "angle1_deg",
                    "angle2_deg",
                    "score",
                    "diff_amplitude_v",
                    "in0_amplitude_v",
                    "in1_amplitude_v",
                    "mean_sum_v",
                    "samples",
                    "measurement_start_s",
                    "measurement_end_s",
                ]
            )

            # =================================================
            # SIATKA
            # =================================================

            angles = create_angles()

            total_points = (
                len(angles)
                * len(angles)
            )

            point_id = 0

            print()
            print("=" * 70)
            print("START TESTU POLARYZACJI V2")
            print("=" * 70)

            print(
                f"Liczba punktów: "
                f"{total_points}"
            )

            print(
                f"Kąty MPC: {angles}"
            )

            print(
                f"Piezo: "
                f"{PIEZO_MIN_V:.1f} -> "
                f"{PIEZO_MAX_V:.1f} V"
            )

            print(
                f"Prędkość skanu: "
                f"{PIEZO_SPEED_V_S:.1f} V/s"
            )

            print(
                f"Czas skanu/punkt: "
                f"{(PIEZO_MAX_V - PIEZO_MIN_V) / PIEZO_SPEED_V_S:.2f} s"
            )

            # =================================================
            # GRID SEARCH 9x9
            # =================================================

            for row_index, target_angle1 in enumerate(
                angles
            ):
                # Serpentyna:
                # ograniczamy niepotrzebne ruchy P2

                if row_index % 2 == 0:
                    angle2_list = angles
                else:
                    angle2_list = list(
                        reversed(
                            angles
                        )
                    )

                for target_angle2 in angle2_list:
                    point_id += 1

                    print()
                    print("=" * 70)

                    print(
                        f"PUNKT "
                        f"{point_id}/"
                        f"{total_points}"
                    )

                    print(
                        f"Cel: "
                        f"P1={target_angle1:.1f}°, "
                        f"P2={target_angle2:.1f}°"
                    )

                    # =========================================
                    # MPC
                    # =========================================

                    actual_angle1, actual_angle2 = (
                        move_mpc(
                            mpc,
                            target_angle1,
                            target_angle2,
                        )
                    )

                    print(
                        f"Rzeczywiste: "
                        f"P1={actual_angle1:.3f}°, "
                        f"P2={actual_angle2:.3f}°"
                    )

                    # =========================================
                    # POMIAR
                    # =========================================

                    measurement_start = (
                        time.monotonic()
                        - program_start
                    )

                    result = measure_polarization_point(
                        adc=adc,
                        mdt=mdt,
                        measurement_writer=(
                            measurement_writer
                        ),
                        program_start=program_start,
                    )

                    measurement_end = (
                        time.monotonic()
                        - program_start
                    )

                    # =========================================
                    # REKORD
                    # =========================================

                    result.update(
                        {
                            "point_id":
                                point_id,

                            "angle1_deg":
                                actual_angle1,

                            "angle2_deg":
                                actual_angle2,

                            "measurement_start_s":
                                measurement_start,

                            "measurement_end_s":
                                measurement_end,
                        }
                    )

                    all_results.append(
                        result
                    )

                    # =========================================
                    # CSV
                    # =========================================

                    report_writer.writerow(
                        [
                            point_id,

                            f"{actual_angle1:.3f}",
                            f"{actual_angle2:.3f}",

                            f"{result['score']:.9f}",

                            f"{result['diff_amplitude_v']:.9f}",

                            f"{result['in0_amplitude_v']:.9f}",

                            f"{result['in1_amplitude_v']:.9f}",

                            f"{result['mean_sum_v']:.9f}",

                            result["samples"],

                            f"{measurement_start:.6f}",
                            f"{measurement_end:.6f}",
                        ]
                    )

                    # Zapis na bieżąco
                    measurement_file.flush()
                    report_file.flush()

                    # =========================================
                    # TERMINAL
                    # =========================================

                    print(
                        f"SCORE: "
                        f"{result['score']:.6f}"
                    )

                    print(
                        f"A_diff: "
                        f"{result['diff_amplitude_v']:.6f} V"
                    )

                    print(
                        f"A_IN0: "
                        f"{result['in0_amplitude_v']:.6f} V"
                    )

                    print(
                        f"A_IN1: "
                        f"{result['in1_amplitude_v']:.6f} V"
                    )

                    print(
                        f"Mean IN0+IN1: "
                        f"{result['mean_sum_v']:.6f} V"
                    )

                    print(
                        f"Próbki: "
                        f"{result['samples']}"
                    )

            # =================================================
            # NAJLEPSZY WYNIK
            # =================================================

            best_result = max(
                all_results,
                key=lambda item: (
                    item["score"]
                ),
            )

            print()
            print("=" * 70)
            print("NAJLEPSZY WYNIK V2")
            print("=" * 70)

            print(
                f"Paddle 1: "
                f"{best_result['angle1_deg']:.3f}°"
            )

            print(
                f"Paddle 2: "
                f"{best_result['angle2_deg']:.3f}°"
            )

            print(
                f"Score: "
                f"{best_result['score']:.9f}"
            )

            print(
                f"A_diff: "
                f"{best_result['diff_amplitude_v']:.9f} V"
            )

            print(
                f"A_IN0: "
                f"{best_result['in0_amplitude_v']:.9f} V"
            )

            print(
                f"A_IN1: "
                f"{best_result['in1_amplitude_v']:.9f} V"
            )

            print(
                f"Mean IN0+IN1: "
                f"{best_result['mean_sum_v']:.9f} V"
            )

            # =================================================
            # USTAWIENIE MPC W NAJLEPSZEJ POZYCJI
            # =================================================

            print()
            print(
                "Ustawiam MPC w najlepszej "
                "znalezionej pozycji..."
            )

            final_angle1, final_angle2 = move_mpc(
                mpc,
                best_result["angle1_deg"],
                best_result["angle2_deg"],
            )

            print(
                f"MPC ustawiony: "
                f"P1={final_angle1:.3f}°, "
                f"P2={final_angle2:.3f}°"
            )

            print()
            print(
                f"Measurement CSV: "
                f"{measurement_path}"
            )

            print(
                f"Report CSV: "
                f"{report_path}"
            )

    except KeyboardInterrupt:
        print()
        print(
            "TEST PRZERWANY PRZEZ UŻYTKOWNIKA."
        )

    except Exception as exc:
        print()
        print("=" * 70)
        print("BŁĄD TESTU V2")
        print("=" * 70)
        print(str(exc))

        raise

    finally:
        # ====================================================
        # PIEZO -> 80 V
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
                    PIEZO_RETURN_SPEED_V_S,
                )

                print(
                    f"Piezo ustawione na "
                    f"{PIEZO_MIN_V:.1f} V."
                )

            except Exception as exc:
                print(
                    f"Nie udało się ustawić "
                    f"piezo na {PIEZO_MIN_V:.1f} V: "
                    f"{exc}"
                )

        # ====================================================
        # ADS1263
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

        # ====================================================
        # MDT694B
        # ====================================================

        if mdt is not None:
            try:
                mdt.disconnect()
            except Exception:
                pass

        # ====================================================
        # MPC220
        # ====================================================

        if mpc is not None:
            try:
                mpc.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
