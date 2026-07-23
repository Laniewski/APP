"""Przeliczenia pomiędzy stopniami aplikacji i jednostkami MPC220.

GUI pokazuje stopnie, ponieważ jest to jednostka naturalna dla operatora.
Sam sterownik MPC220 nie otrzymuje jednak stopni: protokół APT oczekuje
całkowitej pozycji w swoich wewnętrznych jednostkach.

Współczynniki poniżej opisują bieżącą, uproszczoną kalibrację dwupunktową.
Są zebrane w jednym module, aby późniejsza kalibracja laboratoryjna wymagała
zmiany tylko tego miejsca, a nie kodu GUI, workera i komunikacji szeregowej.
"""

MPC_MIN_ANGLE_DEG = 1.0
MPC_MAX_ANGLE_DEG = 160.0

MPC_CALIBRATION_ANGLE_DEG = 90.0
MPC_COMMAND_AT_CALIBRATION_ANGLE = 753

MPC_RAW_AT_ZERO_DEG = 964
MPC_RAW_AT_CALIBRATION_ANGLE = 1717

# 1717 - 964 = 753 jednostki dla różnicy 90 stopni.
# To przybliżenie będzie można zastąpić dokładniejszym modelem kalibracji.
MPC_UNITS_PER_DEGREE = 753.0 / 90.0


def angle_to_command(angle_deg: float) -> int:
    """Przelicza kąt absolutny na całkowitą pozycję APT MPC220.

    Parametry:
        angle_deg: Kąt w stopniach. Zakres aplikacji wynosi 1-160 stopni,
            ale funkcja pozostaje ogólna i nie ogranicza samodzielnie wartości.

    Zwraca:
        Całkowitą liczbę jednostek urządzenia, zaokrągloną do najbliższej
        jednostki APT.

    Wyjątki:
        TypeError lub ValueError mogą wystąpić, gdy przekazana wartość nie
        zachowuje się jak liczba rzeczywista.

    Kalibracja opiera się na punktach 0 stopni -> 0 jednostek oraz
    90 stopni -> 753 jednostki. Offset odczytu 964 nie występuje w tym
    wzorze, ponieważ dotyczy wyłącznie surowego licznika pozycji.
    """
    return round(angle_deg * MPC_UNITS_PER_DEGREE)


def raw_position_to_angle(raw_position: int) -> float:
    """Przelicza surowy licznik pozycji APT na kąt w stopniach.

    Parametry:
        raw_position: Signed int32 odczytany z pola pozycji odpowiedzi
            ``MOT_GET_POSCOUNTER``.

    Zwraca:
        Kąt w stopniach. Jest to wartość wynikająca z pomiaru, dlatego może
        chwilowo wyjść poza zakres GUI przy niedokładnej kalibracji.

    Offset 964 oznacza zaobserwowaną pozycję odpowiadającą zeru stopni.
    Różnica 753 jednostek pomiędzy 964 i 1717 odpowiada 90 stopniom.
    Oba współczynniki są celowo zebrane jako stałe, aby można je było później
    zastąpić wynikami dokładniejszej kalibracji.
    """
    return (raw_position - MPC_RAW_AT_ZERO_DEG) / MPC_UNITS_PER_DEGREE


def clamp_angle(angle_deg: float) -> float:
    """Ogranicza kąt do bezpiecznego zakresu aplikacji 1-160 stopni.

    Parametry:
        angle_deg: Kąt w stopniach, który ma zostać ograniczony.

    Zwraca:
        Wartość nie mniejszą niż ``MPC_MIN_ANGLE_DEG`` i nie większą niż
        ``MPC_MAX_ANGLE_DEG``.

    Ograniczenie należy do logiki aplikacji, a nie do warstwy urządzenia,
    ponieważ warstwa APT operuje wyłącznie na jednostkach całkowitych.
    """
    return max(MPC_MIN_ANGLE_DEG, min(MPC_MAX_ANGLE_DEG, angle_deg))


def calculate_target_angle(
    current_angle_deg: float,
    delta_angle_deg: float,
) -> float:
    """Wyznacza nowy kąt po zmianie względnej i ogranicza go do zakresu.

    Parametry:
        current_angle_deg: Rzeczywisty, ostatnio odczytany kąt w stopniach.
        delta_angle_deg: Krok zmiany w stopniach; może być dodatni lub ujemny.

    Zwraca:
        Docelowy kąt w zakresie 1-160 stopni.

    Przyciski krokowe używają tej funkcji zamiast tekstu etykiety GUI.
    Dzięki temu źródłem pozycji pozostaje odpowiedź urządzenia, a nie wartość
    wyświetlona operatorowi. Sam ruch jest potem wysyłany jako absolutna
    pozycja APT, co pozwala jednoznacznie obsłużyć ograniczenia krańcowe.
    """
    return clamp_angle(current_angle_deg + delta_angle_deg)
