# Decyzja przed implementacją
Baseline: 42 testy przechodzą. Prompt 3911 znaków, definicje 1864.
Walidator nie wiąże parametrów z tekstem; schema nie ma unsupported; 400 tokenów
nie wystarcza na długie plany z opisami. Benchmark dopasowuje powtarzane akcje
do najbliższych wartości, maskując zamianę argumentów między krokami.

Decyzja: częściowy redesign. Segmentacja, ekstrakcja w małych partiach,
deterministyczna interpretacja ograniczonej gramatyki i jawne unsupported dla
fragmentów spoza niej. Pełne dopasowanie fragmentu, nie szukanie słów/liczb.
LLM pozostaje sugestią. Nieznane parafrazy zablokowane: koszt bezpieczeństwa.
Runner i most sprzętowy bez zmian.

Oczekiwanie L przed kodem: start; temperatura 20; unsupported grzałka; wait 30;
łopatka 1 null; piezo 50; łopatka 1 kąt 100; łopatka 2 kąt 100; temperatura 30;
unsupported grzałka; łopatka 1 null; łopatka 2 null; stop; unsupported zapis.
INVALID, trzy unsupported i trzy brakujące kąty. Liczba mnoga oznacza obie
łopatki w kolejności 1,2. Domyślne jednostki kontraktu: C, V, stopnie, sekundy.
Jawna inna jednostka bez obsługiwanej konwersji blokuje fragment.
