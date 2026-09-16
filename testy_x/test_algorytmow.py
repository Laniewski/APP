import argparse
import csv
import math
import sys
import time
from pathlib import Path


# ============================================================
# ============================================================
# PARAMETRY TESTU - TO ZMIENIAJ
# ============================================================
# ============================================================

# Zakres skanowania piezo
PIEZO_MIN_V = 0
PIEZO_MAX_V = 150

# Próg zakończenia algorytmu
TARGET_AMPLITUDE_V = 0.40

# Pozycja początkowa MPC220
START_ANGLE_1 = 80.0
START_ANGLE_2 = 80.0


# ============================================================
# ŚCIEŻKI
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = (
    SCRIPT_DIR
    / "porownanie_algorytmow_polaryzacji"
)


# ============================================================
# IMPORTY PROJEKTU
# ============================================================

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
# PARAMETRY OGÓLNE
# ============================================================

# Pełna mapa referencyjna 9x9
REFERENCE_GRID_POINTS = 81

# Tylko zabezpieczenie przed zbyt długim szukaniem.
# Algorytm kończy się wcześniej po osiągnięciu progu.
MAX_EVALUATIONS = 20

# Minimalna różnica traktowana jako rzeczywista poprawa
MIN_IMPROVEMENT_V = 0.002


# ============================================================
# PARAMETRY PIEZO
# ============================================================

PIEZO_SPEED_V_S = 20.0
PIEZO_RETURN_SPEED_V_S = 20.0

PIEZO_COMMAND_INTERVAL_S = 0.05
PIEZO_SETTLE_S = 0.8


# ============================================================
# PARAMETRY MPC
# ============================================================

MPC_SETTLE_S = 1.0


# ============================================================
# PARAMETRY ADC
# ============================================================

SAMPLE_INTERVAL_S = 0.20
DISCARD_SAMPLES = 4


# ============================================================
# POTWIERDZANIE PRZEKROCZENIA PROGU
# ============================================================

CONFIRM_TARGET = True
CONFIRM_TOLERANCE_V = 0.10


# ============================================================
# WYJĄTKI STERUJĄCE
# ============================================================

class BudgetFinished(Exception):
    pass


class TargetReached(Exception):
    """
    Rzucany dopiero PO zapisaniu poprawnego wyniku.
    Powoduje natychmiastowe zakończenie danego algorytmu.
    """
    pass


# ============================================================
# FUNKCJE MATEMATYCZNE
# ============================================================

def percentile(values, p):

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
    Amplituda:
        A = (P95 - P05) / 2
    """

    if len(values) < 5:
        raise RuntimeError(
            f"Za mało próbek: {len(values)}"
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

    raw = mpc.read_position_units(
        paddle
    )

    return clamp_angle(
        raw_position_to_angle(raw)
    )


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

    requested1 = clamp_angle(
        angle1
    )

    requested2 = clamp_angle(
        angle2
    )

    print()
    print(
        f">>> NASTAWA MPC: "
        f"P1={requested1:.3f}°, "
        f"P2={requested2:.3f}°"
    )

    actual1 = move_paddle(
        mpc,
        1,
        requested1,
    )

    actual2 = move_paddle(
        mpc,
        2,
        requested2,
    )

    print(
        f">>> ODCZYT MPC:  "
        f"P1={actual1:.3f}°, "
        f"P2={actual2:.3f}°"
    )

    time.sleep(
        MPC_SETTLE_S
    )

    return actual1, actual2


# ============================================================
# MDT694B
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

    duration = (
        distance / speed_v_s
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
# KONDYCJONOWANIE PIEZO
# ============================================================

def condition_piezo(mdt):

    print()
    print("Kondycjonowanie piezo...")

    print(
        f"{PIEZO_MIN_V:.1f} V"
        f" -> "
        f"{PIEZO_MAX_V:.1f} V"
        f" -> "
        f"{PIEZO_MIN_V:.1f} V"
    )

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    move_piezo(
        mdt,
        PIEZO_MIN_V,
        PIEZO_MAX_V,
        PIEZO_SPEED_V_S,
    )

    time.sleep(0.3)

    move_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_RETURN_SPEED_V_S,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    print(
        "Kondycjonowanie zakończone."
    )


# ============================================================
# ADC
# ============================================================

def discard_adc_samples(adc):

    for _ in range(
        DISCARD_SAMPLES
    ):

        adc.read_sample()

        time.sleep(
            SAMPLE_INTERVAL_S
        )


# ============================================================
# JEDEN FIZYCZNY POMIAR
# ============================================================

def measure_polarization(
    adc,
    mdt,
    verbose=False,
):

    in0_values = []
    in1_values = []

    diff_values = []
    normalized_values = []
    sum_values = []

    # --------------------------------------------------------
    # START PIEZO
    # --------------------------------------------------------

    fast_set_voltage(
        mdt,
        PIEZO_MIN_V,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    discard_adc_samples(
        adc
    )

    # --------------------------------------------------------
    # CZAS SKANU
    # --------------------------------------------------------

    ramp_duration = (
        PIEZO_MAX_V
        - PIEZO_MIN_V
    ) / PIEZO_SPEED_V_S

    ramp_start = time.monotonic()

    next_command_time = ramp_start
    next_sample_time = ramp_start

    # --------------------------------------------------------
    # SKAN MIN -> MAX
    # --------------------------------------------------------

    while True:

        now = time.monotonic()

        elapsed = (
            now - ramp_start
        )

        if elapsed >= ramp_duration:
            break

        # MDT
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

        # ADC
        if now >= next_sample_time:

            in0, in1 = (
                adc.read_sample()
            )

            difference = (
                in0 - in1
            )

            total = (
                in0 + in1
            )

            in0_values.append(in0)
            in1_values.append(in1)

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

    fast_set_voltage(
        mdt,
        PIEZO_MAX_V,
    )

    # --------------------------------------------------------
    # OBLICZENIA
    # --------------------------------------------------------

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

    mean_sum = (
        sum(sum_values)
        / len(sum_values)
    )

    if verbose:

        print()
        print(
            "----- DIAGNOSTYKA -----"
        )

        print(
            f"Liczba próbek: "
            f"{len(diff_values)}"
        )

        print(
            f"IN0: "
            f"{min(in0_values):.4f}"
            f" .. "
            f"{max(in0_values):.4f} V"
        )

        print(
            f"IN1: "
            f"{min(in1_values):.4f}"
            f" .. "
            f"{max(in1_values):.4f} V"
        )

        print(
            f"IN0-IN1: "
            f"{min(diff_values):.4f}"
            f" .. "
            f"{max(diff_values):.4f} V"
        )

        print(
            f"A_D = "
            f"{diff_amplitude:.6f} V"
        )

        print(
            "-----------------------"
        )

    # --------------------------------------------------------
    # POWRÓT MAX -> MIN
    # --------------------------------------------------------

    move_piezo(
        mdt,
        PIEZO_MAX_V,
        PIEZO_MIN_V,
        PIEZO_RETURN_SPEED_V_S,
    )

    time.sleep(
        PIEZO_SETTLE_S
    )

    return {
        "diff_amplitude_v":
            diff_amplitude,

        "score":
            score,

        "mean_sum_v":
            mean_sum,

        "samples":
            len(diff_values),
    }


# ============================================================
# EWALUATOR
# ============================================================

class Evaluator:

    def __init__(
        self,
        name,
        mpc,
        mdt,
        adc,
    ):

        self.name = name

        self.mpc = mpc
        self.mdt = mdt
        self.adc = adc

        self.records = []
        self.cache = {}

        self.best_record = None

        # Każdy pełny skan piezo = 1 pomiar fizyczny
        self.physical_measurements = 0

        self.threshold_time_s = None
        self.threshold_physical_measurements = None
        self.threshold_unique_points = None

        self.start_time = (
            time.monotonic()
        )

    # --------------------------------------------------------
    # KLUCZ
    # --------------------------------------------------------

    def key(
        self,
        angle1,
        angle2,
    ):

        return (
            round(
                clamp_angle(angle1),
                3,
            ),

            round(
                clamp_angle(angle2),
                3,
            ),
        )

    # --------------------------------------------------------
    # POMIAR FIZYCZNY
    # --------------------------------------------------------

    def physical_measurement(
        self,
        verbose=False,
    ):

        self.physical_measurements += 1

        print(
            f">>> FIZYCZNY POMIAR NR "
            f"{self.physical_measurements}"
        )

        start = time.monotonic()

        result = measure_polarization(
            self.adc,
            self.mdt,
            verbose=verbose,
        )

        duration = (
            time.monotonic()
            - start
        )

        print(
            f">>> Czas pomiaru: "
            f"{duration:.2f} s"
        )

        print(
            f">>> A_D = "
            f"{result['diff_amplitude_v']:.6f} V"
        )

        return result

    # --------------------------------------------------------
    # POTWIERDZENIE PRZEKROCZENIA PROGU
    # --------------------------------------------------------

    def confirm_if_needed(
        self,
        first,
    ):

        first_amp = (
            first[
                "diff_amplitude_v"
            ]
        )

        if (
            not CONFIRM_TARGET
            or
            first_amp
            < TARGET_AMPLITUDE_V
        ):

            return first

        print()
        print(
            f">>> WYNIK PRZEKROCZYŁ PRÓG "
            f"{TARGET_AMPLITUDE_V:.3f} V"
        )

        print(
            f">>> Pierwszy pomiar: "
            f"{first_amp:.6f} V"
        )

        print(
            ">>> Wykonuję pomiar "
            "potwierdzający..."
        )

        second = (
            self.physical_measurement(
                verbose=True
            )
        )

        second_amp = (
            second[
                "diff_amplitude_v"
            ]
        )

        difference = abs(
            first_amp - second_amp
        )

        print(
            f">>> Drugi pomiar: "
            f"{second_amp:.6f} V"
        )

        print(
            f">>> Różnica: "
            f"{difference:.6f} V"
        )

        # ----------------------------------------------------
        # WYNIKI ZGODNE
        # ----------------------------------------------------

        if (
            difference
            <= CONFIRM_TOLERANCE_V
        ):

            result = {

                "diff_amplitude_v":
                    (
                        first_amp
                        + second_amp
                    ) / 2.0,

                "score":
                    (
                        first["score"]
                        + second["score"]
                    ) / 2.0,

                "mean_sum_v":
                    (
                        first["mean_sum_v"]
                        + second["mean_sum_v"]
                    ) / 2.0,

                "samples":
                    (
                        first["samples"]
                        + second["samples"]
                    ),
            }

            print(
                f">>> WYNIK POTWIERDZONY: "
                f"{result['diff_amplitude_v']:.6f} V"
            )

            return result

        # ----------------------------------------------------
        # WYNIKI NIEZGODNE
        # ----------------------------------------------------

        print()
        print(
            ">>> UWAGA: wyniki różnią się "
            "bardziej niż dopuszczalna tolerancja."
        )

        print(
            ">>> Pierwszego wysokiego wyniku "
            "nie uznaję za wiarygodny."
        )

        print(
            ">>> Przyjmuję drugi pomiar."
        )

        return second

    # --------------------------------------------------------
    # EWALUACJA PUNKTU
    # --------------------------------------------------------

    def evaluate(
        self,
        angle1,
        angle2,
    ):

        key = self.key(
            angle1,
            angle2,
        )

        # ----------------------------------------------------
        # CACHE
        # ----------------------------------------------------

        if key in self.cache:

            cached = (
                self.cache[key]
            )

            print()
            print(
                f">>> Punkt "
                f"P1={key[0]:.3f}°, "
                f"P2={key[1]:.3f}° "
                f"był już sprawdzony."
            )

            if cached[
                "target_reached"
            ]:

                raise TargetReached()

            return cached

        # ----------------------------------------------------
        # LIMIT
        # ----------------------------------------------------

        if (
            len(self.records)
            >= MAX_EVALUATIONS
        ):

            raise BudgetFinished()

        requested1 = clamp_angle(
            angle1
        )

        requested2 = clamp_angle(
            angle2
        )

        print()
        print(
            "=" * 70
        )

        print(
            f"[{self.name}]"
        )

        print(
            f"Punkt MPC: "
            f"{len(self.records) + 1}"
            f"/{MAX_EVALUATIONS}"
        )

        print(
            f"ŻĄDANA NASTAWA: "
            f"P1={requested1:.3f}°, "
            f"P2={requested2:.3f}°"
        )

        # ----------------------------------------------------
        # MPC
        # ----------------------------------------------------

        actual1, actual2 = (
            move_mpc(
                self.mpc,
                requested1,
                requested2,
            )
        )

        # ----------------------------------------------------
        # POMIAR
        # ----------------------------------------------------

        measurement = (
            self.physical_measurement()
        )

        # ----------------------------------------------------
        # POTWIERDZENIE
        # ----------------------------------------------------

        measurement = (
            self.confirm_if_needed(
                measurement
            )
        )

        elapsed = (
            time.monotonic()
            - self.start_time
        )

        # ----------------------------------------------------
        # REKORD
        # ----------------------------------------------------

        result = {

            "evaluation":
                len(self.records) + 1,

            "time_s":
                elapsed,

            "angle1_deg":
                actual1,

            "angle2_deg":
                actual2,

            "diff_amplitude_v":
                measurement[
                    "diff_amplitude_v"
                ],

            "score":
                measurement[
                    "score"
                ],

            "mean_sum_v":
                measurement[
                    "mean_sum_v"
                ],

            "samples":
                measurement[
                    "samples"
                ],

            "physical_measurements":
                self.physical_measurements,
        }

        # ----------------------------------------------------
        # MAKSIMUM
        # ----------------------------------------------------

        if (
            self.best_record is None
            or
            result[
                "diff_amplitude_v"
            ]
            >
            self.best_record[
                "diff_amplitude_v"
            ]
        ):

            self.best_record = result

            print()
            print(
                ">>> NOWE MAKSIMUM"
            )

            print(
                f">>> A_D = "
                f"{result['diff_amplitude_v']:.6f} V"
            )

            print(
                f">>> P1 = "
                f"{actual1:.3f}°"
            )

            print(
                f">>> P2 = "
                f"{actual2:.3f}°"
            )

        # ----------------------------------------------------
        # PRÓG
        # ----------------------------------------------------

        target_reached = (
            result[
                "diff_amplitude_v"
            ]
            >= TARGET_AMPLITUDE_V
        )

        result[
            "target_reached"
        ] = target_reached

        result[
            "best_so_far_v"
        ] = (
            self.best_record[
                "diff_amplitude_v"
            ]
        )

        result[
            "search_degree_pct"
        ] = (
            (len(self.records) + 1)
            / REFERENCE_GRID_POINTS
            * 100.0
        )

        # ----------------------------------------------------
        # WAŻNE:
        # zapisujemy rekord PRZED zatrzymaniem algorytmu
        # ----------------------------------------------------

        self.records.append(
            result
        )

        self.cache[key] = (
            result
        )

        print()
        print(
            f"[{self.name}] "
            f"A={result['diff_amplitude_v']:.4f} V | "
            f"BEST={result['best_so_far_v']:.4f} V | "
            f"P1={actual1:.3f}° | "
            f"P2={actual2:.3f}° | "
            f"pomiary={self.physical_measurements} | "
            f"czas={elapsed:.1f}s"
        )

        # ----------------------------------------------------
        # NATYCHMIASTOWE ZATRZYMANIE
        # ----------------------------------------------------

        if target_reached:

            if (
                self.threshold_time_s
                is None
            ):

                self.threshold_time_s = (
                    elapsed
                )

                self.threshold_physical_measurements = (
                    self.physical_measurements
                )

                self.threshold_unique_points = (
                    len(self.records)
                )

            print()
            print(
                "#" * 70
            )

            print(
                ">>> PRÓG OSIĄGNIĘTY"
            )

            print(
                f">>> A_D = "
                f"{result['diff_amplitude_v']:.6f} V"
            )

            print(
                f">>> wymagany próg = "
                f"{TARGET_AMPLITUDE_V:.6f} V"
            )

            print(
                f">>> nastawa: "
                f"P1={actual1:.3f}°, "
                f"P2={actual2:.3f}°"
            )

            print(
                f">>> unikalne punkty MPC: "
                f"{len(self.records)}"
            )

            print(
                f">>> pomiary fizyczne: "
                f"{self.physical_measurements}"
            )

            print(
                f">>> czas: "
                f"{elapsed:.2f} s"
            )

            print(
                ">>> ALGORYTM ZAKOŃCZONY"
            )

            print(
                "#" * 70
            )

            raise TargetReached()

        return result


# ============================================================
# 1. COARSE-TO-FINE GRID
# ============================================================

def run_coarse_to_fine(
    mpc,
    mdt,
    adc,
):

    evaluator = Evaluator(
        "coarse_to_fine_grid",
        mpc,
        mdt,
        adc,
    )

    coarse_angles = [
        1.0,
        54.0,
        107.0,
        160.0,
    ]

    coarse_points = [

        (a1, a2)

        for a1 in coarse_angles
        for a2 in coarse_angles
    ]

    # Punkty najbliższe pozycji startowej są badane pierwsze
    coarse_points.sort(
        key=lambda p:
            (
                (p[0] - START_ANGLE_1) ** 2
                +
                (p[1] - START_ANGLE_2) ** 2
            )
    )

    try:

        # ----------------------------------------------------
        # COARSE
        # ----------------------------------------------------

        for angle1, angle2 in coarse_points:

            evaluator.evaluate(
                angle1,
                angle2,
            )

        # ----------------------------------------------------
        # FINE ±20°
        # ----------------------------------------------------

        best = (
            evaluator.best_record
        )

        center1 = (
            best["angle1_deg"]
        )

        center2 = (
            best["angle2_deg"]
        )

        points = []

        for d1 in (
            -20.0,
            0.0,
            20.0,
        ):

            for d2 in (
                -20.0,
                0.0,
                20.0,
            ):

                points.append(
                    (
                        clamp_angle(
                            center1 + d1
                        ),

                        clamp_angle(
                            center2 + d2
                        ),
                    )
                )

        points.sort(
            key=lambda p:
                (
                    (p[0] - center1) ** 2
                    +
                    (p[1] - center2) ** 2
                )
        )

        for angle1, angle2 in points:

            evaluator.evaluate(
                angle1,
                angle2,
            )

        # ----------------------------------------------------
        # FINE ±5°
        # ----------------------------------------------------

        best = (
            evaluator.best_record
        )

        center1 = (
            best["angle1_deg"]
        )

        center2 = (
            best["angle2_deg"]
        )

        points = []

        for d1 in (
            -5.0,
            0.0,
            5.0,
        ):

            for d2 in (
                -5.0,
                0.0,
                5.0,
            ):

                points.append(
                    (
                        clamp_angle(
                            center1 + d1
                        ),

                        clamp_angle(
                            center2 + d2
                        ),
                    )
                )

        points.sort(
            key=lambda p:
                (
                    (p[0] - center1) ** 2
                    +
                    (p[1] - center2) ** 2
                )
        )

        for angle1, angle2 in points:

            evaluator.evaluate(
                angle1,
                angle2,
            )

    except TargetReached:

        print(
            "\nCoarse-to-Fine zakończony "
            "po osiągnięciu progu."
        )

    except BudgetFinished:

        print(
            "\nCoarse-to-Fine zakończony "
            "po wykorzystaniu budżetu."
        )

    return evaluator


# ============================================================
# 2. COORDINATE / COMPASS SEARCH
# ============================================================

def run_coordinate_search(
    mpc,
    mdt,
    adc,
):

    evaluator = Evaluator(
        "coordinate_search",
        mpc,
        mdt,
        adc,
    )

    current1 = (
        START_ANGLE_1
    )

    current2 = (
        START_ANGLE_2
    )

    step = 40.0
    minimum_step = 2.0

    try:

        current = (
            evaluator.evaluate(
                current1,
                current2,
            )
        )

        while (
            step >= minimum_step
        ):

            print()
            print(
                f">>> Coordinate Search | "
                f"krok = {step:.3f}°"
            )

            candidates = [

                (
                    current1 + step,
                    current2,
                ),

                (
                    current1 - step,
                    current2,
                ),

                (
                    current1,
                    current2 + step,
                ),

                (
                    current1,
                    current2 - step,
                ),
            ]

            best_candidate = (
                current
            )

            for (
                angle1,
                angle2
            ) in candidates:

                result = (
                    evaluator.evaluate(
                        angle1,
                        angle2,
                    )
                )

                if (
                    result[
                        "diff_amplitude_v"
                    ]
                    >
                    best_candidate[
                        "diff_amplitude_v"
                    ]
                    + MIN_IMPROVEMENT_V
                ):

                    best_candidate = (
                        result
                    )

            if (
                best_candidate[
                    "diff_amplitude_v"
                ]
                >
                current[
                    "diff_amplitude_v"
                ]
                + MIN_IMPROVEMENT_V
            ):

                current = (
                    best_candidate
                )

                current1 = (
                    current[
                        "angle1_deg"
                    ]
                )

                current2 = (
                    current[
                        "angle2_deg"
                    ]
                )

                print()
                print(
                    f">>> Nowy punkt bazowy: "
                    f"P1={current1:.3f}°, "
                    f"P2={current2:.3f}°"
                )

            else:

                step /= 2.0

                print()
                print(
                    f">>> Brak poprawy."
                )

                print(
                    f">>> Nowy krok: "
                    f"{step:.3f}°"
                )

    except TargetReached:

        print(
            "\nCoordinate Search zakończony "
            "po osiągnięciu progu."
        )

    except BudgetFinished:

        print(
            "\nCoordinate Search zakończony "
            "po wykorzystaniu budżetu."
        )

    return evaluator


# ============================================================
# 3. HOOKE-JEEVES
# ============================================================

def run_hooke_jeeves(
    mpc,
    mdt,
    adc,
):

    evaluator = Evaluator(
        "hooke_jeeves",
        mpc,
        mdt,
        adc,
    )

    base1 = (
        START_ANGLE_1
    )

    base2 = (
        START_ANGLE_2
    )

    step = 40.0
    minimum_step = 2.0

    try:

        base = (
            evaluator.evaluate(
                base1,
                base2,
            )
        )

        while (
            step >= minimum_step
        ):

            print()
            print(
                f">>> Hooke-Jeeves | "
                f"krok = {step:.3f}°"
            )

            old_base1 = (
                base1
            )

            old_base2 = (
                base2
            )

            old_base_result = (
                base
            )

            exploratory1 = (
                base1
            )

            exploratory2 = (
                base2
            )

            exploratory_result = (
                base
            )

            # ------------------------------------------------
            # OŚ P1
            # ------------------------------------------------

            plus = (
                evaluator.evaluate(
                    exploratory1 + step,
                    exploratory2,
                )
            )

            minus = (
                evaluator.evaluate(
                    exploratory1 - step,
                    exploratory2,
                )
            )

            candidate = max(

                [
                    exploratory_result,
                    plus,
                    minus,
                ],

                key=lambda r:
                    r[
                        "diff_amplitude_v"
                    ],
            )

            if (
                candidate[
                    "diff_amplitude_v"
                ]
                >
                exploratory_result[
                    "diff_amplitude_v"
                ]
                + MIN_IMPROVEMENT_V
            ):

                exploratory_result = (
                    candidate
                )

                exploratory1 = (
                    candidate[
                        "angle1_deg"
                    ]
                )

                exploratory2 = (
                    candidate[
                        "angle2_deg"
                    ]
                )

            # ------------------------------------------------
            # OŚ P2
            # ------------------------------------------------

            plus = (
                evaluator.evaluate(
                    exploratory1,
                    exploratory2 + step,
                )
            )

            minus = (
                evaluator.evaluate(
                    exploratory1,
                    exploratory2 - step,
                )
            )

            candidate = max(

                [
                    exploratory_result,
                    plus,
                    minus,
                ],

                key=lambda r:
                    r[
                        "diff_amplitude_v"
                    ],
            )

            if (
                candidate[
                    "diff_amplitude_v"
                ]
                >
                exploratory_result[
                    "diff_amplitude_v"
                ]
                + MIN_IMPROVEMENT_V
            ):

                exploratory_result = (
                    candidate
                )

                exploratory1 = (
                    candidate[
                        "angle1_deg"
                    ]
                )

                exploratory2 = (
                    candidate[
                        "angle2_deg"
                    ]
                )

            # ------------------------------------------------
            # PATTERN MOVE
            # ------------------------------------------------

            if (
                exploratory_result[
                    "diff_amplitude_v"
                ]
                >
                old_base_result[
                    "diff_amplitude_v"
                ]
                + MIN_IMPROVEMENT_V
            ):

                pattern1 = (
                    clamp_angle(
                        exploratory1
                        + (
                            exploratory1
                            - old_base1
                        )
                    )
                )

                pattern2 = (
                    clamp_angle(
                        exploratory2
                        + (
                            exploratory2
                            - old_base2
                        )
                    )
                )

                print()
                print(
                    f">>> Pattern move: "
                    f"P1={pattern1:.3f}°, "
                    f"P2={pattern2:.3f}°"
                )

                pattern = (
                    evaluator.evaluate(
                        pattern1,
                        pattern2,
                    )
                )

                if (
                    pattern[
                        "diff_amplitude_v"
                    ]
                    >
                    exploratory_result[
                        "diff_amplitude_v"
                    ]
                    + MIN_IMPROVEMENT_V
                ):

                    base = pattern

                    base1 = (
                        pattern[
                            "angle1_deg"
                        ]
                    )

                    base2 = (
                        pattern[
                            "angle2_deg"
                        ]
                    )

                else:

                    base = (
                        exploratory_result
                    )

                    base1 = (
                        exploratory1
                    )

                    base2 = (
                        exploratory2
                    )

            else:

                step /= 2.0

                print()
                print(
                    f">>> Brak poprawy."
                )

                print(
                    f">>> Nowy krok: "
                    f"{step:.3f}°"
                )

    except TargetReached:

        print(
            "\nHooke-Jeeves zakończony "
            "po osiągnięciu progu."
        )

    except BudgetFinished:

        print(
            "\nHooke-Jeeves zakończony "
            "po wykorzystaniu budżetu."
        )

    return evaluator


# ============================================================
# PODSUMOWANIE
# ============================================================

def summarize(
    evaluator
):

    best = (
        evaluator.best_record
    )

    if best is None:
        return None

    total_time = (
        evaluator.records[-1][
            "time_s"
        ]
    )

    unique_points = (
        len(
            evaluator.records
        )
    )

    search_degree = (
        unique_points
        / REFERENCE_GRID_POINTS
        * 100.0
    )

    return {

        "algorithm":
            evaluator.name,

        "piezo_min_v":
            PIEZO_MIN_V,

        "piezo_max_v":
            PIEZO_MAX_V,

        "target_amplitude_v":
            TARGET_AMPLITUDE_V,

        "start_angle1_deg":
            START_ANGLE_1,

        "start_angle2_deg":
            START_ANGLE_2,

        "total_time_s":
            total_time,

        "physical_measurements":
            evaluator.physical_measurements,

        "unique_points":
            unique_points,

        "search_degree_pct":
            search_degree,

        "best_amplitude_v":
            best[
                "diff_amplitude_v"
            ],

        "best_score":
            best[
                "score"
            ],

        "best_angle1_deg":
            best[
                "angle1_deg"
            ],

        "best_angle2_deg":
            best[
                "angle2_deg"
            ],

        "target_reached":
            (
                evaluator.threshold_time_s
                is not None
            ),

        "threshold_time_s":
            evaluator.threshold_time_s,

        "threshold_physical_measurements":
            evaluator.threshold_physical_measurements,

        "threshold_unique_points":
            evaluator.threshold_unique_points,
    }


# ============================================================
# RAPORT ALGORYTMU
# parametr | wartosc
# ============================================================

def save_algorithm_report(
    evaluator,
    path,
):

    summary = summarize(
        evaluator
    )

    rows = [

        (
            "parametr",
            "wartosc",
        ),

        (
            "algorytm",
            summary[
                "algorithm"
            ],
        ),

        (
            "piezo_min_v",
            f"{PIEZO_MIN_V:.3f}",
        ),

        (
            "piezo_max_v",
            f"{PIEZO_MAX_V:.3f}",
        ),

        (
            "prog_amplitudy_v",
            f"{TARGET_AMPLITUDE_V:.6f}",
        ),

        (
            "pozycja_startowa_p1_deg",
            f"{START_ANGLE_1:.3f}",
        ),

        (
            "pozycja_startowa_p2_deg",
            f"{START_ANGLE_2:.3f}",
        ),

        (
            "prog_osiagniety",
            str(
                summary[
                    "target_reached"
                ]
            ),
        ),

        (
            "czas_calkowity_s",
            f"{summary['total_time_s']:.3f}",
        ),

        (
            "liczba_pomiarow_fizycznych",
            str(
                summary[
                    "physical_measurements"
                ]
            ),
        ),

        (
            "liczba_unikalnych_punktow_mpc",
            str(
                summary[
                    "unique_points"
                ]
            ),
        ),

        (
            "stopien_przeszukania_pct",
            f"{summary['search_degree_pct']:.3f}",
        ),

        (
            "maksymalna_amplituda_v",
            f"{summary['best_amplitude_v']:.6f}",
        ),

        (
            "score_dla_maksimum",
            f"{summary['best_score']:.6f}",
        ),

        (
            "p1_dla_maksimum_deg",
            f"{summary['best_angle1_deg']:.3f}",
        ),

        (
            "p2_dla_maksimum_deg",
            f"{summary['best_angle2_deg']:.3f}",
        ),
    ]

    with open(
        path,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.writer(
            file
        )

        writer.writerows(
            rows
        )


# ============================================================
# RAPORT PORÓWNAWCZY
# ============================================================

def save_comparison(
    summaries,
    path,
):

    valid = [
        s
        for s in summaries
        if s is not None
    ]

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            "POROWNANIE ALGORYTMOW DOBORU POLARYZACJI\n"
        )

        file.write(
            "=" * 78
            + "\n\n"
        )

        # ====================================================
        # PARAMETRY TESTU
        # ====================================================

        file.write(
            "PARAMETRY TESTU\n"
        )

        file.write(
            "-" * 78
            + "\n"
        )

        file.write(
            f"PIEZO_MIN_V:               "
            f"{PIEZO_MIN_V:.3f} V\n"
        )

        file.write(
            f"PIEZO_MAX_V:               "
            f"{PIEZO_MAX_V:.3f} V\n"
        )

        file.write(
            f"TARGET_AMPLITUDE_V:        "
            f"{TARGET_AMPLITUDE_V:.3f} V\n"
        )

        file.write(
            f"START_ANGLE_1:             "
            f"{START_ANGLE_1:.3f} deg\n"
        )

        file.write(
            f"START_ANGLE_2:             "
            f"{START_ANGLE_2:.3f} deg\n"
        )

        file.write(
            f"Pelne przeszukanie:        "
            f"{REFERENCE_GRID_POINTS} punktow = 100%\n"
        )

        file.write(
            f"Maksymalny budzet awaryjny:"
            f" {MAX_EVALUATIONS} punktow\n"
        )

        file.write(
            "\n"
        )

        file.write(
            "Algorytm konczy prace natychmiast po "
            "potwierdzonym osiagnieciu zadanego progu.\n"
        )

        file.write(
            "Pomiar potwierdzajacy liczy sie jako "
            "dodatkowy pomiar fizyczny.\n"
        )

        file.write(
            "Stopien przeszukania jest liczony z liczby "
            "unikalnych nastaw MPC wzgledem 81 punktow "
            "mapy referencyjnej.\n"
        )

        # ====================================================
        # WYNIKI
        # ====================================================

        file.write(
            "\n"
            + "=" * 78
            + "\n"
        )

        file.write(
            "WYNIKI\n"
        )

        file.write(
            "=" * 78
            + "\n\n"
        )

        for s in valid:

            file.write(
                f"{s['algorithm']}\n"
            )

            file.write(
                "-" * 78
                + "\n"
            )

            file.write(
                f"Prog osiagniety:                   "
                f"{s['target_reached']}\n"
            )

            file.write(
                f"Czas:                              "
                f"{s['total_time_s']:.2f} s\n"
            )

            file.write(
                f"Liczba pomiarow fizycznych:        "
                f"{s['physical_measurements']}\n"
            )

            file.write(
                f"Liczba unikalnych punktow MPC:     "
                f"{s['unique_points']}\n"
            )

            file.write(
                f"Stopien przeszukania:              "
                f"{s['search_degree_pct']:.2f}%\n"
            )

            file.write(
                f"Najlepsza amplituda A_D:           "
                f"{s['best_amplitude_v']:.6f} V\n"
            )

            file.write(
                f"Score dla najlepszego wyniku:      "
                f"{s['best_score']:.6f}\n"
            )

            file.write(
                f"P1 dla maksimum:                   "
                f"{s['best_angle1_deg']:.3f} deg\n"
            )

            file.write(
                f"P2 dla maksimum:                   "
                f"{s['best_angle2_deg']:.3f} deg\n"
            )

            file.write(
                "\n"
            )

        # ====================================================
        # AUTOMATYCZNE PORÓWNANIE
        # ====================================================

        file.write(
            "=" * 78
            + "\n"
        )

        file.write(
            "KROTKIE POROWNANIE\n"
        )

        file.write(
            "=" * 78
            + "\n\n"
        )

        reached = [
            s
            for s in valid
            if s[
                "target_reached"
            ]
        ]

        if reached:

            fastest = min(
                reached,
                key=lambda s:
                    s[
                        "total_time_s"
                    ],
            )

            least_measurements = min(
                reached,
                key=lambda s:
                    s[
                        "physical_measurements"
                    ],
            )

            least_points = min(
                reached,
                key=lambda s:
                    s[
                        "unique_points"
                    ],
            )

            file.write(
                "Najszybszy algorytm:\n"
            )

            file.write(
                f"  {fastest['algorithm']} "
                f"- {fastest['total_time_s']:.2f} s\n\n"
            )

            file.write(
                "Najmniej pomiarow fizycznych:\n"
            )

            file.write(
                f"  {least_measurements['algorithm']} "
                f"- {least_measurements['physical_measurements']}\n\n"
            )

            file.write(
                "Najmniejszy stopien przeszukania:\n"
            )

            file.write(
                f"  {least_points['algorithm']} "
                f"- {least_points['search_degree_pct']:.2f}% "
                f"({least_points['unique_points']} punktow)\n\n"
            )

        else:

            file.write(
                "Zaden algorytm nie osiagnal "
                "zadanego progu.\n\n"
            )

        highest = max(
            valid,
            key=lambda s:
                s[
                    "best_amplitude_v"
                ],
        )

        file.write(
            "Najwyzsza znaleziona amplituda:\n"
        )

        file.write(
            f"  algorytm: "
            f"{highest['algorithm']}\n"
        )

        file.write(
            f"  A_D: "
            f"{highest['best_amplitude_v']:.6f} V\n"
        )

        file.write(
            f"  P1: "
            f"{highest['best_angle1_deg']:.3f} deg\n"
        )

        file.write(
            f"  P2: "
            f"{highest['best_angle2_deg']:.3f} deg\n"
        )


# ============================================================
# WYŚWIETLANIE PARAMETRÓW
# ============================================================

def print_test_settings():

    print()
    print(
        "=" * 78
    )

    print(
        "PARAMETRY TESTU"
    )

    print(
        "=" * 78
    )

    print(
        f"Piezo MIN:          "
        f"{PIEZO_MIN_V:.3f} V"
    )

    print(
        f"Piezo MAX:          "
        f"{PIEZO_MAX_V:.3f} V"
    )

    print(
        f"Zakres skanu:       "
        f"{PIEZO_MIN_V:.3f}"
        f" -> "
        f"{PIEZO_MAX_V:.3f} V"
    )

    print(
        f"Prędkość skanu:     "
        f"{PIEZO_SPEED_V_S:.3f} V/s"
    )

    print(
        f"Próg zakończenia:   "
        f"{TARGET_AMPLITUDE_V:.3f} V"
    )

    print(
        f"Start MPC:          "
        f"P1={START_ANGLE_1:.3f}°, "
        f"P2={START_ANGLE_2:.3f}°"
    )

    print(
        f"Limit awaryjny:     "
        f"{MAX_EVALUATIONS} punktów"
    )

    print(
        f"Mapa odniesienia:   "
        f"{REFERENCE_GRID_POINTS} punktów"
    )

    print()
    print(
        "UWAGA: algorytm kończy się od razu "
        "po potwierdzonym przekroczeniu progu."
    )

    print(
        "=" * 78
    )


# ============================================================
# RESET PRZED KAŻDYM ALGORYTMEM
# ============================================================

def reset_system(
    mpc,
    mdt,
    adc,
):

    print()
    print(
        "=" * 78
    )

    print(
        "PRZYGOTOWANIE UKLADU"
    )

    print(
        "=" * 78
    )

    condition_piezo(
        mdt
    )

    print()
    print(
        "Ustawiam pozycję początkową MPC..."
    )

    move_mpc(
        mpc,
        START_ANGLE_1,
        START_ANGLE_2,
    )

    discard_adc_samples(
        adc
    )

    time.sleep(0.5)

    print(
        "Układ gotowy."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Porownanie algorytmow "
            "automatycznej nastawy polaryzacji"
        )
    )

    parser.add_argument(
        "--mpc-port",
        default="/dev/ttyUSB0",
    )

    parser.add_argument(
        "--mdt-port",
        default="/dev/ttyACM0",
    )

    args = parser.parse_args()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    mpc = None
    mdt = None
    adc = None

    evaluators = []

    try:

        # ====================================================
        # PARAMETRY
        # ====================================================

        print_test_settings()

        # ====================================================
        # MPC220
        # ====================================================

        print()
        print(
            "Łączenie MPC220..."
        )

        mpc = MPC220Driver(
            args.mpc_port
        )

        mpc.connect()

        print(
            "MPC220 OK"
        )

        # ====================================================
        # MDT694B
        # ====================================================

        print()
        print(
            "Łączenie MDT694B..."
        )

        mdt = MDT694BDriver(
            args.mdt_port
        )

        mdt.connect()

        (
            allowed_min_v,
            allowed_max_v
        ) = mdt.read_voltage_range()

        if (
            PIEZO_MIN_V
            < allowed_min_v
        ):

            raise RuntimeError(
                f"PIEZO_MIN_V={PIEZO_MIN_V} V "
                f"jest poza zakresem MDT694B."
            )

        if (
            PIEZO_MAX_V
            > allowed_max_v
        ):

            raise RuntimeError(
                f"PIEZO_MAX_V={PIEZO_MAX_V} V "
                f"jest poza zakresem MDT694B."
            )

        print(
            f"MDT694B OK | "
            f"zakres: "
            f"{allowed_min_v:.1f}"
            f" - "
            f"{allowed_max_v:.1f} V"
        )

        # ====================================================
        # ADS1263
        # ====================================================

        print()
        print(
            "Łączenie ADS1263..."
        )

        adc = ADS1263Driver()

        adc.connect()

        adc.start_measurement()

        print(
            "ADS1263 OK"
        )

        # ====================================================
        # 1. COARSE-TO-FINE
        # ====================================================

        print()
        print(
            "#" * 78
        )

        print(
            "1/3 - COARSE-TO-FINE GRID SEARCH"
        )

        print(
            "#" * 78
        )

        reset_system(
            mpc,
            mdt,
            adc,
        )

        result = run_coarse_to_fine(
            mpc,
            mdt,
            adc,
        )

        evaluators.append(
            result
        )

        save_algorithm_report(
            result,
            OUTPUT_DIR
            / "coarse_to_fine_grid.csv",
        )

        # ====================================================
        # 2. COORDINATE SEARCH
        # ====================================================

        print()
        print(
            "#" * 78
        )

        print(
            "2/3 - COORDINATE SEARCH"
        )

        print(
            "#" * 78
        )

        reset_system(
            mpc,
            mdt,
            adc,
        )

        result = run_coordinate_search(
            mpc,
            mdt,
            adc,
        )

        evaluators.append(
            result
        )

        save_algorithm_report(
            result,
            OUTPUT_DIR
            / "coordinate_search.csv",
        )

        # ====================================================
        # 3. HOOKE-JEEVES
        # ====================================================

        print()
        print(
            "#" * 78
        )

        print(
            "3/3 - HOOKE-JEEVES"
        )

        print(
            "#" * 78
        )

        reset_system(
            mpc,
            mdt,
            adc,
        )

        result = run_hooke_jeeves(
            mpc,
            mdt,
            adc,
        )

        evaluators.append(
            result
        )

        save_algorithm_report(
            result,
            OUTPUT_DIR
            / "hooke_jeeves.csv",
        )

        # ====================================================
        # PORÓWNANIE
        # ====================================================

        summaries = [

            summarize(e)

            for e in evaluators
        ]

        save_comparison(
            summaries,
            OUTPUT_DIR
            / "porownanie_algorytmow.txt",
        )

        # ====================================================
        # NAJLEPSZY WYNIK
        # ====================================================

        valid_summaries = [
            s
            for s in summaries
            if s is not None
        ]

        best_summary = max(
            valid_summaries,
            key=lambda s:
                s[
                    "best_amplitude_v"
                ],
        )

        print()
        print(
            "=" * 78
        )

        print(
            "KONIEC TESTU"
        )

        print(
            "=" * 78
        )

        print()
        print(
            "NAJLEPSZY ZNALEZIONY WYNIK:"
        )

        print(
            f"Algorytm: "
            f"{best_summary['algorithm']}"
        )

        print(
            f"A_D: "
            f"{best_summary['best_amplitude_v']:.6f} V"
        )

        print(
            f"P1: "
            f"{best_summary['best_angle1_deg']:.3f}°"
        )

        print(
            f"P2: "
            f"{best_summary['best_angle2_deg']:.3f}°"
        )

        print()
        print(
            "Ustawiam MPC na najlepszej "
            "znalezionej nastawie..."
        )

        move_mpc(
            mpc,
            best_summary[
                "best_angle1_deg"
            ],
            best_summary[
                "best_angle2_deg"
            ],
        )

        print()
        print(
            "Wyniki zapisano w:"
        )

        print(
            OUTPUT_DIR
        )

    finally:

        # ====================================================
        # BEZPIECZNE ZAKOŃCZENIE
        # ====================================================

        if mdt is not None:

            try:

                fast_set_voltage(
                    mdt,
                    PIEZO_MIN_V,
                )

            except Exception:
                pass

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
                mdt.close()

            except Exception:

                try:
                    mdt.disconnect()
                except Exception:
                    pass

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
