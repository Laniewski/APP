import csv
import time
from datetime import datetime

from modules.mdt694b.driver import MDT694BDriver


# ============================================================
# KONFIGURACJA
# ============================================================

PORT = "/dev/ttyACM0"

# Nie potrzebujemy całego 0-140 V.
# Ten zakres powinien objąć ponad jeden prążek.
VOLTAGE_MIN = 20.0
VOLTAGE_MAX = 100.0

# Kolejno coraz szybsze testy.
RAMP_SPEEDS_V_S = [
    10.0,
    15.0,
    20.0,
    25.0,
    30.0,
    40.0,
]

# Dwa cykle:
# 20 -> 100 -> 20 -> 100 -> 20
CYCLES_PER_SPEED = 2

# MDT dostaje nową nastawę maksymalnie co 50 ms.
COMMAND_INTERVAL_S = 0.05

# Pauza między prędkościami.
# Będzie bardzo łatwo rozpoznać kolejne testy w CSV z aplikacji.
PAUSE_BETWEEN_TESTS_S = 3.0

# Baseline przed pierwszym i po ostatnim teście.
BASELINE_BEFORE_S = 5.0
BASELINE_AFTER_S = 5.0

# Plik pomocniczy zapisujący dokładne momenty testów.
LOG_FILE = "piezo_speed_test_log.csv"


# ============================================================
# FUNKCJE POMOCNICZE
# ============================================================

def fast_set_voltage(driver, voltage):
    """
    Ustawia napięcie bez wykonywania przy każdym kroku:
    xmin?, xmax?, sysmin?, sysmax?, vlimit?, xvoltage?

    Zakres bezpieczeństwa sprawdzamy raz przed rozpoczęciem testu.
    """
    driver._send_command(f"xvoltage={voltage:.3f}")


def log_event(writer, file_handle, script_start, event, speed=None, voltage=None):
    """
    Zapisuje zdarzenia testu do osobnego CSV.
    """

    elapsed = time.monotonic() - script_start

    writer.writerow([
        f"{elapsed:.6f}",
        datetime.now().isoformat(timespec="milliseconds"),
        event,
        "" if speed is None else f"{speed:.3f}",
        "" if voltage is None else f"{voltage:.3f}",
    ])

    file_handle.flush()


def ramp(
    driver,
    start_voltage,
    end_voltage,
    speed_v_s,
):
    """
    Rampa napięcia oparta na rzeczywistym czasie.

    Napięcie nie jest zwiększane o stały krok.
    Zamiast tego:

        V(t) = V_start +/- speed * t

    Dzięki temu opóźnienia transmisji szeregowej nie kumulują się
    i średnia prędkość rampy pozostaje możliwie bliska zadanej.
    """

    distance = abs(end_voltage - start_voltage)

    if distance < 0.001:
        fast_set_voltage(driver, end_voltage)
        return

    duration = distance / speed_v_s

    direction = 1.0 if end_voltage > start_voltage else -1.0

    ramp_start = time.monotonic()
    next_command = ramp_start

    while True:

        now = time.monotonic()
        elapsed = now - ramp_start

        if elapsed >= duration:
            break

        voltage = (
            start_voltage
            + direction * speed_v_s * elapsed
        )

        if direction > 0:
            voltage = min(voltage, end_voltage)
        else:
            voltage = max(voltage, end_voltage)

        fast_set_voltage(driver, voltage)

        print(
            f"\r"
            f"{speed_v_s:5.1f} V/s | "
            f"V = {voltage:7.2f} V | "
            f"t rampy = {elapsed:6.2f}/{duration:6.2f} s",
            end="",
            flush=True,
        )

        next_command += COMMAND_INTERVAL_S

        sleep_time = next_command - time.monotonic()

        if sleep_time > 0:
            time.sleep(sleep_time)

    # gwarantujemy dokładny punkt końcowy
    fast_set_voltage(driver, end_voltage)

    print(
        f"\r"
        f"{speed_v_s:5.1f} V/s | "
        f"V = {end_voltage:7.2f} V | "
        f"t rampy = {duration:6.2f}/{duration:6.2f} s"
    )


def move_safely(driver, start_voltage, target_voltage):
    """
    Spokojny ruch do napięcia początkowego testu.
    """

    if abs(start_voltage - target_voltage) < 0.1:
        fast_set_voltage(driver, target_voltage)
        return

    print(
        f"Przejście z {start_voltage:.2f} V "
        f"do {target_voltage:.2f} V..."
    )

    # 10 V/s jest spokojną znaną nam prędkością
    ramp(
        driver,
        start_voltage,
        target_voltage,
        10.0,
    )


# ============================================================
# PROGRAM GŁÓWNY
# ============================================================

def main():

    print()
    print("==============================================")
    print("      AUTOMATYCZNY TEST PRĘDKOŚCI PIEZO")
    print("==============================================")
    print()

    driver = MDT694BDriver(
        port=PORT,
        timeout=1.0,
        settle_time=0.3,
    )

    print("Łączenie z MDT694B...")

    driver.connect()

    script_start = time.monotonic()

    log_file = open(
        LOG_FILE,
        "w",
        newline="",
        encoding="utf-8",
    )

    log_writer = csv.writer(log_file)

    log_writer.writerow([
        "script_time_s",
        "wall_time",
        "event",
        "speed_v_s",
        "voltage_v",
    ])

    try:

        # ====================================================
        # SPRAWDZENIE ZAKRESU
        # ====================================================

        allowed_min, allowed_max = driver.read_voltage_range()

        print()
        print(
            f"Efektywny zakres MDT694B: "
            f"{allowed_min:.2f} - {allowed_max:.2f} V"
        )

        v_min = max(VOLTAGE_MIN, allowed_min)
        v_max = min(VOLTAGE_MAX, allowed_max)

        if v_min >= v_max:
            raise RuntimeError(
                "Zakres testu nie mieści się "
                "w dozwolonym zakresie MDT694B."
            )

        print(
            f"Zakres używany w teście: "
            f"{v_min:.2f} - {v_max:.2f} V"
        )

        span = v_max - v_min

        print()
        print("Plan testu:")
        print()

        total_modulation_time = 0.0

        for speed in RAMP_SPEEDS_V_S:

            half_cycle = span / speed
            full_cycle = 2.0 * half_cycle

            test_time = (
                full_cycle
                * CYCLES_PER_SPEED
            )

            total_modulation_time += test_time

            print(
                f"{speed:5.1f} V/s  ->  "
                f"pół cyklu {half_cycle:5.2f} s | "
                f"pełny cykl {full_cycle:5.2f} s | "
                f"test {test_time:5.2f} s"
            )

        pauses = (
            PAUSE_BETWEEN_TESTS_S
            * (len(RAMP_SPEEDS_V_S) - 1)
        )

        estimated_total = (
            BASELINE_BEFORE_S
            + total_modulation_time
            + pauses
            + BASELINE_AFTER_S
        )

        print()
        print(
            f"Szacowany czas całego testu: "
            f"{estimated_total:.1f} s"
        )

        # ====================================================
        # POWRÓT DO POZYCJI STARTOWEJ
        # ====================================================

        current_voltage = driver.read_voltage()

        print()
        print(
            f"Aktualne napięcie: "
            f"{current_voltage:.2f} V"
        )

        move_safely(
            driver,
            current_voltage,
            v_min,
        )

        # ====================================================
        # BASELINE POCZĄTKOWY
        # ====================================================

        print()
        print("==============================================")
        print("              BASELINE")
        print("==============================================")

        print(
            f"Piezo stoi na {v_min:.2f} V "
            f"przez {BASELINE_BEFORE_S:.1f} s."
        )

        print()
        print(
            "W aplikacji ADS1263 pomiar powinien "
            "już być uruchomiony."
        )

        log_event(
            log_writer,
            log_file,
            script_start,
            "BASELINE_START",
            voltage=v_min,
        )

        time.sleep(BASELINE_BEFORE_S)

        log_event(
            log_writer,
            log_file,
            script_start,
            "BASELINE_END",
            voltage=v_min,
        )

        # ====================================================
        # TESTY KOLEJNYCH PRĘDKOŚCI
        # ====================================================

        for speed_index, speed in enumerate(
            RAMP_SPEEDS_V_S,
            start=1,
        ):

            print()
            print()
            print("==============================================")
            print(
                f" TEST {speed_index}/{len(RAMP_SPEEDS_V_S)}"
                f"     {speed:.1f} V/s"
            )
            print("==============================================")
            print()

            log_event(
                log_writer,
                log_file,
                script_start,
                "TEST_START",
                speed=speed,
                voltage=v_min,
            )

            for cycle in range(
                1,
                CYCLES_PER_SPEED + 1,
            ):

                # --------------------------------------------
                # RUCH W GÓRĘ
                # --------------------------------------------

                print()
                print(
                    f"Cykl {cycle}/{CYCLES_PER_SPEED}: "
                    f"{v_min:.0f} -> {v_max:.0f} V"
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "RAMP_UP_START",
                    speed=speed,
                    voltage=v_min,
                )

                ramp(
                    driver,
                    v_min,
                    v_max,
                    speed,
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "RAMP_UP_END",
                    speed=speed,
                    voltage=v_max,
                )

                # --------------------------------------------
                # RUCH W DÓŁ
                # --------------------------------------------

                print()
                print(
                    f"Cykl {cycle}/{CYCLES_PER_SPEED}: "
                    f"{v_max:.0f} -> {v_min:.0f} V"
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "RAMP_DOWN_START",
                    speed=speed,
                    voltage=v_max,
                )

                ramp(
                    driver,
                    v_max,
                    v_min,
                    speed,
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "RAMP_DOWN_END",
                    speed=speed,
                    voltage=v_min,
                )

            log_event(
                log_writer,
                log_file,
                script_start,
                "TEST_END",
                speed=speed,
                voltage=v_min,
            )

            # =================================================
            # PAUZA MIĘDZY TESTAMI
            # =================================================

            if speed_index < len(RAMP_SPEEDS_V_S):

                print()
                print(
                    f"PAUZA {PAUSE_BETWEEN_TESTS_S:.1f} s "
                    f"na {v_min:.1f} V"
                )

                fast_set_voltage(
                    driver,
                    v_min,
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "PAUSE_START",
                    voltage=v_min,
                )

                time.sleep(
                    PAUSE_BETWEEN_TESTS_S
                )

                log_event(
                    log_writer,
                    log_file,
                    script_start,
                    "PAUSE_END",
                    voltage=v_min,
                )

        # ====================================================
        # BASELINE KOŃCOWY
        # ====================================================

        print()
        print()
        print("==============================================")
        print("          KONIEC WSZYSTKICH TESTÓW")
        print("==============================================")
        print()

        fast_set_voltage(
            driver,
            v_min,
        )

        log_event(
            log_writer,
            log_file,
            script_start,
            "FINAL_BASELINE_START",
            voltage=v_min,
        )

        print(
            f"Piezo stoi przez "
            f"{BASELINE_AFTER_S:.1f} s."
        )

        time.sleep(
            BASELINE_AFTER_S
        )

        log_event(
            log_writer,
            log_file,
            script_start,
            "FINAL_BASELINE_END",
            voltage=v_min,
        )

        final_voltage = driver.read_voltage()

        print()
        print(
            f"Końcowe napięcie: "
            f"{final_voltage:.2f} V"
        )

        print()
        print(
            f"Log testu zapisano jako: "
            f"{LOG_FILE}"
        )

    except KeyboardInterrupt:

        print()
        print()
        print("==============================================")
        print("         TEST PRZERWANY CTRL+C")
        print("==============================================")

        log_event(
            log_writer,
            log_file,
            script_start,
            "INTERRUPTED",
        )

    finally:

        # ====================================================
        # BEZPIECZNY POWRÓT
        # ====================================================

        print()
        print(
            "Powrót do bezpiecznego "
            "napięcia początkowego..."
        )

        try:

            current_voltage = driver.read_voltage()

            allowed_min, allowed_max = (
                driver.read_voltage_range()
            )

            target = max(
                VOLTAGE_MIN,
                allowed_min,
            )

            target = min(
                target,
                allowed_max,
            )

            move_safely(
                driver,
                current_voltage,
                target,
            )

            final_voltage = driver.read_voltage()

            print(
                f"Napięcie końcowe MDT: "
                f"{final_voltage:.2f} V"
            )

        except Exception as exc:

            print()
            print(
                "UWAGA: nie udało się wykonać "
                f"końcowego powrotu: {exc}"
            )

        try:
            log_file.close()
        except Exception:
            pass

        driver.disconnect()

        print("MDT694B rozłączony.")
        print()


if __name__ == "__main__":
    main()