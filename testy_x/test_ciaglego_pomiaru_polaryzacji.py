import sys
import time
from pathlib import Path


# ============================================================
# USTAWIENIA
# ============================================================

MPC_PORT = "/dev/ttyUSB0"

PADDLE = 1

START_ANGLE_DEG = 40.0
END_ANGLE_DEG = 50.0

# najmniejszy sensowny krok sterownika
STEP_UNITS = 1

# około 1°/s
STEP_INTERVAL_S = 0.12

# odczyt pozycji
READ_INTERVAL_S = 0.12

SETTLE_S = 0.5


# ============================================================
# ŚCIEŻKA PROJEKTU
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# IMPORTY
# ============================================================

from modules.mpc220.driver import MPC220Driver

from modules.mpc220.calibration import (
    MPC_UNITS_PER_DEGREE,
    angle_to_command,
    raw_position_to_angle,
)


# ============================================================
# FUNKCJE
# ============================================================

def read_angle(mpc, paddle):
    raw = mpc.read_position_units(paddle)
    return raw_position_to_angle(raw)


def move_and_wait(mpc, paddle, angle):
    mpc.move_absolute_units(
        paddle,
        angle_to_command(angle),
    )

    mpc.wait_until_stopped(
        paddle
    )


# ============================================================
# TEST
# ============================================================

def run_test(mpc):

    start_command = angle_to_command(
        START_ANGLE_DEG
    )

    end_command = angle_to_command(
        END_ANGLE_DEG
    )

    angle_per_unit = (
        1.0 / MPC_UNITS_PER_DEGREE
    )

    expected_speed = (
        angle_per_unit
        * STEP_UNITS
        / STEP_INTERVAL_S
    )

    print()
    print("=" * 72)
    print("TEST PŁYNNEGO SWEEPU MPC220")
    print("=" * 72)

    print(
        f"1 unit = {angle_per_unit:.5f}°"
    )

    print(
        f"Krok = {STEP_UNITS} unit "
        f"≈ {angle_per_unit * STEP_UNITS:.5f}°"
    )

    print(
        f"Interwał = {STEP_INTERVAL_S:.3f} s"
    )

    print(
        f"Prędkość oczekiwana ≈ "
        f"{expected_speed:.3f}°/s"
    )

    print(
        f"Zakres: "
        f"{START_ANGLE_DEG:.1f}° "
        f"-> "
        f"{END_ANGLE_DEG:.1f}°"
    )

    # ========================================================
    # START
    # ========================================================

    print()
    print(
        f"Ustawiam start "
        f"{START_ANGLE_DEG:.2f}°..."
    )

    move_and_wait(
        mpc,
        PADDLE,
        START_ANGLE_DEG,
    )

    time.sleep(
        SETTLE_S
    )

    actual_start = read_angle(
        mpc,
        PADDLE
    )

    print(
        f"Rzeczywisty start: "
        f"{actual_start:.3f}°"
    )

    print()
    print(
        " czas    cel[°]    rzeczywista[°]    błąd[°]"
    )

    print("-" * 55)

    # ========================================================
    # PĘTLA SWEEPU
    # ========================================================

    start_time = time.monotonic()

    current_command = start_command

    next_command_time = (
        start_time
    )

    next_read_time = (
        start_time
    )

    last_command = (
        start_command
    )

    samples = []

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_time
        )

        # ----------------------------------------------------
        # NOWA KOMENDA
        # ----------------------------------------------------

        if (
            now >= next_command_time
            and
            current_command <= end_command
        ):

            mpc.move_absolute_units(
                PADDLE,
                current_command,
            )

            last_command = (
                current_command
            )

            current_command += (
                STEP_UNITS
            )

            next_command_time += (
                STEP_INTERVAL_S
            )

        # ----------------------------------------------------
        # ODCZYT POZYCJI
        # ----------------------------------------------------

        if now >= next_read_time:

            actual = read_angle(
                mpc,
                PADDLE
            )

            target_angle = (
                START_ANGLE_DEG
                +
                (
                    last_command
                    - start_command
                )
                / MPC_UNITS_PER_DEGREE
            )

            error = (
                target_angle
                - actual
            )

            samples.append(
                (
                    elapsed,
                    target_angle,
                    actual,
                    error,
                )
            )

            print(
                f"{elapsed:6.2f}   "
                f"{target_angle:8.3f}   "
                f"{actual:13.3f}   "
                f"{error:+8.3f}"
            )

            next_read_time += (
                READ_INTERVAL_S
            )

        # ----------------------------------------------------
        # KONIEC
        # ----------------------------------------------------

        if current_command > end_command:
            break

        time.sleep(
            0.001
        )

    # ========================================================
    # OSTATNI RUCH
    # ========================================================

    mpc.wait_until_stopped(
        PADDLE
    )

    end_time = time.monotonic()

    final_angle = read_angle(
        mpc,
        PADDLE
    )

    total_time = (
        end_time - start_time
    )

    actual_speed = (
        END_ANGLE_DEG
        - START_ANGLE_DEG
    ) / total_time

    # ========================================================
    # PROSTA ANALIZA
    # ========================================================

    errors = [
        abs(sample[3])
        for sample in samples
    ]

    if errors:

        mean_error = (
            sum(errors) / len(errors)
        )

        max_error = max(errors)

    else:

        mean_error = 0.0
        max_error = 0.0

    print()
    print("=" * 72)
    print("WYNIK")
    print("=" * 72)

    print(
        f"Pozycja końcowa:       "
        f"{final_angle:.3f}°"
    )

    print(
        f"Czas całkowity:        "
        f"{total_time:.3f} s"
    )

    print(
        f"Średnia prędkość:      "
        f"{actual_speed:.3f}°/s"
    )

    print(
        f"Prędkość oczekiwana:   "
        f"{expected_speed:.3f}°/s"
    )

    print(
        f"Średni |błąd|:         "
        f"{mean_error:.4f}°"
    )

    print(
        f"Maksymalny |błąd|:     "
        f"{max_error:.4f}°"
    )

    print()

    if (
        mean_error < 0.15
        and
        max_error < 0.30
    ):

        print(
            "WYNIK: sweep wygląda dobrze."
        )

        print(
            "Można użyć tego mechanizmu "
            "do ciągłego skanowania z piezo."
        )

    else:

        print(
            "WYNIK: sweep ma większe opóźnienie."
        )

        print(
            "Trzeba dobrać inny interwał "
            "albo większy krok."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    mpc = None

    try:

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

        run_test(
            mpc
        )

    finally:

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