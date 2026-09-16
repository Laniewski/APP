import sys
import time
from pathlib import Path


# ============================================================
# USTAWIENIA TESTU
# ============================================================

MPC_PORT = "/dev/ttyUSB0"

# Pozycja początkowa
START_P1 = 80.0
START_P2 = 80.0

# Pozycja końcowa
TARGET_P1 = 120.0
TARGET_P2 = 40.0

# Czas na uspokojenie po ruchu
SETTLE_TIME_S = 1.0


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
    MPC_MIN_ANGLE_DEG,
    MPC_MAX_ANGLE_DEG,
    angle_to_command,
    raw_position_to_angle,
)


# ============================================================
# FUNKCJE
# ============================================================

def clamp_angle(angle):
    return max(
        MPC_MIN_ANGLE_DEG,
        min(MPC_MAX_ANGLE_DEG, angle)
    )


def read_angle(mpc, paddle):
    raw = mpc.read_position_units(paddle)
    return raw_position_to_angle(raw)


def print_positions(mpc, prefix=""):
    p1 = read_angle(mpc, 1)
    p2 = read_angle(mpc, 2)

    print(
        f"{prefix}P1={p1:.3f}°, "
        f"P2={p2:.3f}°"
    )

    return p1, p2


# ============================================================
# RUCH SEKWENCYJNY
# ============================================================

def move_sequential(mpc, angle1, angle2):

    angle1 = clamp_angle(angle1)
    angle2 = clamp_angle(angle2)

    command1 = angle_to_command(angle1)
    command2 = angle_to_command(angle2)

    print()
    print("Ruch SEKWENCYJNY")
    print(
        f"Cel: P1={angle1:.3f}°, "
        f"P2={angle2:.3f}°"
    )

    start = time.monotonic()

    # P1
    print("Start P1")

    mpc.move_absolute_units(
        1,
        command1,
    )

    mpc.wait_until_stopped(1)

    t_p1 = time.monotonic()

    print(
        f"P1 zakończone po "
        f"{t_p1 - start:.3f} s"
    )

    # P2
    print("Start P2")

    mpc.move_absolute_units(
        2,
        command2,
    )

    mpc.wait_until_stopped(2)

    end = time.monotonic()

    print(
        f"P2 zakończone po "
        f"{end - t_p1:.3f} s"
    )

    total = end - start

    print(
        f"CAŁKOWITY CZAS SEKWENCYJNY: "
        f"{total:.3f} s"
    )

    time.sleep(SETTLE_TIME_S)

    p1, p2 = print_positions(
        mpc,
        "Po ruchu: "
    )

    return total, p1, p2


# ============================================================
# RUCH RÓWNOLEGŁY
# ============================================================

def move_parallel(mpc, angle1, angle2):

    angle1 = clamp_angle(angle1)
    angle2 = clamp_angle(angle2)

    command1 = angle_to_command(angle1)
    command2 = angle_to_command(angle2)

    print()
    print("Ruch RÓWNOLEGŁY")
    print(
        f"Cel: P1={angle1:.3f}°, "
        f"P2={angle2:.3f}°"
    )

    start = time.monotonic()

    # --------------------------------------------------------
    # KLUCZOWA RÓŻNICA:
    # nie czekamy na P1 przed wysłaniem komendy P2
    # --------------------------------------------------------

    print("Wysyłam komendę P1...")

    mpc.move_absolute_units(
        1,
        command1,
    )

    t_command1 = time.monotonic()

    print("Wysyłam komendę P2...")

    mpc.move_absolute_units(
        2,
        command2,
    )

    t_command2 = time.monotonic()

    print(
        f"Różnica czasu wysłania komend: "
        f"{t_command2 - t_command1:.4f} s"
    )

    print(
        "Obie komendy wysłane. "
        "Czekam na zatrzymanie..."
    )

    # Dopiero teraz czekamy
    mpc.wait_until_stopped(1)

    t_p1 = time.monotonic()

    print(
        f"P1 zgłasza zatrzymanie po "
        f"{t_p1 - start:.3f} s"
    )

    mpc.wait_until_stopped(2)

    end = time.monotonic()

    print(
        f"P2 zgłasza zatrzymanie po "
        f"{end - start:.3f} s"
    )

    total = end - start

    print(
        f"CAŁKOWITY CZAS RÓWNOLEGŁY: "
        f"{total:.3f} s"
    )

    time.sleep(SETTLE_TIME_S)

    p1, p2 = print_positions(
        mpc,
        "Po ruchu: "
    )

    return total, p1, p2


# ============================================================
# USTAWIENIE POZYCJI STARTOWEJ
# ============================================================

def move_to_start(mpc):

    print()
    print("=" * 70)

    print(
        f"Ustawiam pozycję startową: "
        f"P1={START_P1:.3f}°, "
        f"P2={START_P2:.3f}°"
    )

    command1 = angle_to_command(
        clamp_angle(START_P1)
    )

    command2 = angle_to_command(
        clamp_angle(START_P2)
    )

    # Możemy tutaj również wysłać obie komendy od razu
    mpc.move_absolute_units(
        1,
        command1,
    )

    mpc.move_absolute_units(
        2,
        command2,
    )

    mpc.wait_until_stopped(1)
    mpc.wait_until_stopped(2)

    time.sleep(SETTLE_TIME_S)

    print_positions(
        mpc,
        "START: "
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("TEST JEDNOCZESNEGO RUCHU ŁOPATEK MPC220")
    print("=" * 70)

    print(
        f"Port:       {MPC_PORT}"
    )

    print(
        f"Start:      "
        f"P1={START_P1:.1f}°, "
        f"P2={START_P2:.1f}°"
    )

    print(
        f"Cel:        "
        f"P1={TARGET_P1:.1f}°, "
        f"P2={TARGET_P2:.1f}°"
    )

    mpc = MPC220Driver(
        MPC_PORT
    )

    try:

        # ====================================================
        # POŁĄCZENIE
        # ====================================================

        print()
        print("Łączenie z MPC220...")

        mpc.connect()

        print("MPC220 połączony.")

        print_positions(
            mpc,
            "Aktualnie: "
        )

        # ====================================================
        # TEST 1 - SEKWENCYJNY
        # ====================================================

        move_to_start(mpc)

        print()
        print("#" * 70)
        print("TEST 1: RUCH SEKWENCYJNY")
        print("#" * 70)

        (
            sequential_time,
            seq_p1,
            seq_p2,
        ) = move_sequential(
            mpc,
            TARGET_P1,
            TARGET_P2,
        )

        # ====================================================
        # POWRÓT
        # ====================================================

        move_to_start(mpc)

        time.sleep(1.0)

        # ====================================================
        # TEST 2 - RÓWNOLEGŁY
        # ====================================================

        print()
        print("#" * 70)
        print("TEST 2: RUCH RÓWNOLEGŁY")
        print("#" * 70)

        (
            parallel_time,
            par_p1,
            par_p2,
        ) = move_parallel(
            mpc,
            TARGET_P1,
            TARGET_P2,
        )

        # ====================================================
        # WYNIKI
        # ====================================================

        print()
        print("=" * 70)
        print("WYNIKI")
        print("=" * 70)

        print(
            f"Ruch sekwencyjny: "
            f"{sequential_time:.3f} s"
        )

        print(
            f"Ruch równoległy:   "
            f"{parallel_time:.3f} s"
        )

        difference = (
            sequential_time
            - parallel_time
        )

        print(
            f"Różnica:           "
            f"{difference:.3f} s"
        )

        if sequential_time > 0:

            improvement = (
                difference
                / sequential_time
                * 100.0
            )

            print(
                f"Skrócenie czasu:   "
                f"{improvement:.1f}%"
            )

        print()
        print("Pozycje końcowe:")

        print(
            f"sekwencyjnie: "
            f"P1={seq_p1:.3f}°, "
            f"P2={seq_p2:.3f}°"
        )

        print(
            f"równolegle:   "
            f"P1={par_p1:.3f}°, "
            f"P2={par_p2:.3f}°"
        )

        print()
        print(
            "Jeżeli ruch równoległy jest wyraźnie "
            "szybszy i obie pozycje końcowe są "
            "poprawne, możemy zastosować go "
            "w algorytmie polaryzacji."
        )

    finally:

        try:
            mpc.close()

        except Exception:

            try:
                mpc.disconnect()

            except Exception:
                pass


if __name__ == "__main__":
    main()