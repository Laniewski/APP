import sys
import time
from pathlib import Path


# ============================================================
# USTAWIENIA
# ============================================================

MPC_PORT = "/dev/ttyUSB0"

PADDLE = 1

START_ANGLE_DEG = 40.0
END_ANGLE_DEG = 60.0

# Sterujemy bezpośrednio najmniejszą jednostką MPC
COMMAND_STEP_UNITS = 1

# około 1°/s
STEP_INTERVAL_S = 0.12

# nie ma sensu czytać dużo szybciej niż wysyłamy komendy
READ_INTERVAL_S = 0.12

SETTLE_S = 1.0


# ============================================================
# ŚCIEŻKI
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

    return (
        raw_position_to_angle(raw),
        raw,
    )


def move_and_wait(
    mpc,
    paddle,
    angle,
):

    command = angle_to_command(angle)

    mpc.move_absolute_units(
        paddle,
        command,
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

    theoretical_speed = (
        angle_per_unit
        * COMMAND_STEP_UNITS
        / STEP_INTERVAL_S
    )

    print()
    print("=" * 78)
    print("TEST DROBNEGO RUCHU MPC220")
    print("=" * 78)

    print(
        f"Jedna jednostka MPC:   "
        f"{angle_per_unit:.5f}°"
    )

    print(
        f"Krok:                  "
        f"{COMMAND_STEP_UNITS} unit "
        f"≈ {angle_per_unit * COMMAND_STEP_UNITS:.5f}°"
    )

    print(
        f"Interwał:              "
        f"{STEP_INTERVAL_S:.3f} s"
    )

    print(
        f"Prędkość teoretyczna: "
        f"{theoretical_speed:.3f}°/s"
    )

    print(
        f"Zakres:                "
        f"{START_ANGLE_DEG:.1f}° "
        f"-> "
        f"{END_ANGLE_DEG:.1f}°"
    )

    # ========================================================
    # START
    # ========================================================

    print()
    print("Ustawiam pozycję startową...")

    move_and_wait(
        mpc,
        PADDLE,
        START_ANGLE_DEG,
    )

    time.sleep(
        SETTLE_S
    )

    actual_angle, raw = read_angle(
        mpc,
        PADDLE,
    )

    print(
        f"Start rzeczywisty: "
        f"{actual_angle:.3f}° "
        f"(raw={raw})"
    )

    print()
    print(
        " czas     cmd     cel[°]    rzeczywista[°]    różnica"
    )

    print("-" * 70)

    # ========================================================
    # PĘTLA
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
                COMMAND_STEP_UNITS
            )

            next_command_time += (
                STEP_INTERVAL_S
            )

        # ----------------------------------------------------
        # ODCZYT
        # ----------------------------------------------------

        if now >= next_read_time:

            actual_angle, raw = read_angle(
                mpc,
                PADDLE,
            )

            # Kąt zadany odpowiadający komendzie.
            # Tutaj interesuje nas przede wszystkim
            # względna zmiana pozycji.

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
                - actual_angle
            )

            print(
                f"{elapsed:6.2f}   "
                f"{last_command:5d}   "
                f"{target_angle:8.3f}   "
                f"{actual_angle:13.3f}   "
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
    # CZEKAJ NA KONIEC
    # ========================================================

    print()
    print("Wysłano ostatnią komendę.")

    mpc.wait_until_stopped(
        PADDLE
    )

    end_time = time.monotonic()

    actual_end, raw_end = read_angle(
        mpc,
        PADDLE,
    )

    total_time = (
        end_time
        - start_time
    )

    actual_speed = (
        END_ANGLE_DEG
        - START_ANGLE_DEG
    ) / total_time

    print()
    print("=" * 78)
    print("WYNIK")
    print("=" * 78)

    print(
        f"Pozycja końcowa:      "
        f"{actual_end:.3f}°"
    )

    print(
        f"Czas:                 "
        f"{total_time:.3f} s"
    )

    print(
        f"Średnia prędkość:     "
        f"{actual_speed:.3f}°/s"
    )

    print(
        f"Oczekiwana prędkość:  "
        f"{theoretical_speed:.3f}°/s"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    mpc = None

    try:

        print("Łączenie MPC220...")

        mpc = MPC220Driver(
            MPC_PORT
        )

        mpc.connect()

        print("MPC220 OK")

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