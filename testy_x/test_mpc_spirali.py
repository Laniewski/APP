import sys
import csv
import time
import math
from pathlib import Path


# ============================================================
# ŚCIEŻKI
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = (
    SCRIPT_DIR
    / "dane"
    / "test_mpc_spirala"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "spirala_mpc.csv"
)


# ============================================================
# IMPORTY
# ============================================================

from modules.mpc220.driver import MPC220Driver

from modules.mpc220.calibration import (
    angle_to_command,
    raw_position_to_angle,
)


# ============================================================
# USTAWIENIA
# ============================================================

MPC_PORT = "/dev/ttyUSB0"

# Środek przestrzeni
CENTER_P1 = 80.0
CENTER_P2 = 80.0

# Maksymalny promień testowej spirali
MAX_RADIUS_DEG = 30.0

# Liczba pełnych obrotów
TURNS = 3.0

# Całkowity czas spirali.
# Celowo wolno na pierwszy test.
DURATION_S = 45.0

# Nowy punkt trajektorii co:
COMMAND_INTERVAL_S = 0.12

# Odczyt rzeczywistych pozycji
READ_INTERVAL_S = 0.12

START_SETTLE_S = 1.0


# ============================================================
# FUNKCJE
# ============================================================

def read_angle(mpc, paddle):

    raw = mpc.read_position_units(
        paddle
    )

    return raw_position_to_angle(
        raw
    )


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


def spiral_position(progress):

    # progress: 0 -> 1

    radius = (
        MAX_RADIUS_DEG
        * progress
    )

    phi = (
        2.0
        * math.pi
        * TURNS
        * progress
    )

    p1 = (
        CENTER_P1
        + radius
        * math.cos(phi)
    )

    p2 = (
        CENTER_P2
        + radius
        * math.sin(phi)
    )

    return (
        p1,
        p2,
        radius,
        phi,
    )


# ============================================================
# TEST
# ============================================================

def run_test(mpc):

    print()
    print("=" * 76)
    print("TEST RUCHU MPC220 PO SPIRALI")
    print("=" * 76)

    print(
        f"Środek:          "
        f"({CENTER_P1:.1f}°, {CENTER_P2:.1f}°)"
    )

    print(
        f"Promień końcowy: {MAX_RADIUS_DEG:.1f}°"
    )

    print(
        f"Liczba obrotów:  {TURNS:.1f}"
    )

    print(
        f"Czas:            {DURATION_S:.1f} s"
    )

    print(
        f"Komenda co:      {COMMAND_INTERVAL_S:.3f} s"
    )

    print()

    # ========================================================
    # START
    # ========================================================

    print(
        "Ustawiam obie łopatki na "
        "(80°, 80°)..."
    )

    move_both_and_wait(
        mpc,
        CENTER_P1,
        CENTER_P2,
    )

    time.sleep(
        START_SETTLE_S
    )

    actual1 = read_angle(
        mpc,
        1,
    )

    actual2 = read_angle(
        mpc,
        2,
    )

    print(
        f"Start rzeczywisty: "
        f"P1={actual1:.3f}°, "
        f"P2={actual2:.3f}°"
    )

    print()
    print(
        " czas   cel P1   cel P2   "
        "real P1   real P2   "
        "err P1   err P2"
    )

    print("-" * 76)

    rows = []

    # ========================================================
    # PĘTLA
    # ========================================================

    start_time = time.monotonic()

    next_command = start_time
    next_read = start_time

    target_p1 = CENTER_P1
    target_p2 = CENTER_P2

    radius = 0.0
    phi = 0.0

    while True:

        now = time.monotonic()

        elapsed = (
            now - start_time
        )

        progress = min(
            elapsed / DURATION_S,
            1.0,
        )

        # ====================================================
        # NOWY PUNKT SPIRALI
        # ====================================================

        if now >= next_command:

            (
                target_p1,
                target_p2,
                radius,
                phi,
            ) = spiral_position(
                progress
            )

            # KLUCZ:
            # wysyłamy P1 i P2 jeden po drugim,
            # ale NIE czekamy na zatrzymanie.

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

            next_command += (
                COMMAND_INTERVAL_S
            )

        # ====================================================
        # ODCZYT POZYCJI
        # ====================================================

        if now >= next_read:

            actual1 = read_angle(
                mpc,
                1,
            )

            actual2 = read_angle(
                mpc,
                2,
            )

            error1 = (
                target_p1
                - actual1
            )

            error2 = (
                target_p2
                - actual2
            )

            radial_error = math.sqrt(
                error1**2
                + error2**2
            )

            rows.append(
                {
                    "time_s":
                        elapsed,

                    "progress":
                        progress,

                    "radius_deg":
                        radius,

                    "phi_rad":
                        phi,

                    "target_p1_deg":
                        target_p1,

                    "target_p2_deg":
                        target_p2,

                    "actual_p1_deg":
                        actual1,

                    "actual_p2_deg":
                        actual2,

                    "error_p1_deg":
                        error1,

                    "error_p2_deg":
                        error2,

                    "error_2d_deg":
                        radial_error,
                }
            )

            print(
                f"{elapsed:5.1f}   "
                f"{target_p1:7.2f}   "
                f"{target_p2:7.2f}   "
                f"{actual1:7.2f}   "
                f"{actual2:7.2f}   "
                f"{error1:+6.2f}   "
                f"{error2:+6.2f}"
            )

            next_read += (
                READ_INTERVAL_S
            )

        # ====================================================
        # KONIEC
        # ====================================================

        if progress >= 1.0:
            break

        time.sleep(
            0.001
        )

    # ========================================================
    # KOŃCOWA POZYCJA
    # ========================================================

    print()
    print(
        "Koniec trajektorii. "
        "Czekam na zatrzymanie..."
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    final1 = read_angle(
        mpc,
        1,
    )

    final2 = read_angle(
        mpc,
        2,
    )

    # ========================================================
    # CSV
    # ========================================================

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time_s",
                "progress",
                "radius_deg",
                "phi_rad",
                "target_p1_deg",
                "target_p2_deg",
                "actual_p1_deg",
                "actual_p2_deg",
                "error_p1_deg",
                "error_p2_deg",
                "error_2d_deg",
            ],
        )

        writer.writeheader()

        writer.writerows(
            rows
        )

    # ========================================================
    # STATYSTYKI
    # ========================================================

    errors1 = [
        abs(r["error_p1_deg"])
        for r in rows
    ]

    errors2 = [
        abs(r["error_p2_deg"])
        for r in rows
    ]

    errors_2d = [
        r["error_2d_deg"]
        for r in rows
    ]

    mean_e1 = (
        sum(errors1)
        / len(errors1)
    )

    mean_e2 = (
        sum(errors2)
        / len(errors2)
    )

    mean_e2d = (
        sum(errors_2d)
        / len(errors_2d)
    )

    max_e2d = max(
        errors_2d
    )

    print()
    print("=" * 76)
    print("WYNIK")
    print("=" * 76)

    print(
        f"Pozycja końcowa:"
    )

    print(
        f"P1 = {final1:.3f}°"
    )

    print(
        f"P2 = {final2:.3f}°"
    )

    print()

    print(
        f"Średni |błąd P1|: "
        f"{mean_e1:.4f}°"
    )

    print(
        f"Średni |błąd P2|: "
        f"{mean_e2:.4f}°"
    )

    print(
        f"Średni błąd 2D:   "
        f"{mean_e2d:.4f}°"
    )

    print(
        f"Maks. błąd 2D:    "
        f"{max_e2d:.4f}°"
    )

    print()
    print(
        f"CSV: {OUTPUT_FILE}"
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