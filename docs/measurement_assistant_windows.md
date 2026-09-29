# Lokalny tester AI na Windows 10/11

Tester uruchamia wyłącznie segmentację, lokalny model, grounding i walidację.
Nie importuje kontrolerów sprzętu, nie wykrywa USB/serial i nie uruchamia
`MeasurementActions`, `Runnera` ani wygenerowanych skryptów. Zmienna
`APP_AI_EXECUTION_ENABLED` musi pozostać równa `0`.

## 1. Repozytorium

Uruchom PowerShell i wykonaj:

```powershell
$workRoot = Join-Path $HOME "Documents\kodowansko"
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null
Set-Location $workRoot
git clone https://github.com/Laniewski/APP.git APPv2
Set-Location .\APPv2
git checkout architecture-v2-learning
git status
git rev-parse HEAD
```

Jeśli `APPv2` już istnieje, nie klonuj ponownie. Wejdź do niego, wykonaj
`git status`, `git remote -v` i `git branch --show-current`. Zachowaj lokalne
zmiany przed przełączeniem gałęzi.

## 2. Python i minimalne środowisko

Python 3.11–3.13 z python.org jest odpowiedni. Podczas instalacji zaznacz
`Add python.exe to PATH`. Następnie:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Warstwa PC-only korzysta tylko z biblioteki standardowej. `requirements.txt`
zawiera PySide6, pyqtgraph i pyserial potrzebne pełnej aplikacji oraz integracji
sprzętowej; tester ich nie potrzebuje.

Aktywacja środowiska jest opcjonalna:

```powershell
.\.venv\Scripts\Activate.ps1
```

Jeśli PowerShell blokuje skrypt, można bez zmiany execution policy wywoływać
`.\.venv\Scripts\python.exe` bezpośrednio. Ewentualna zmiana tylko dla bieżącego
procesu to `Set-ExecutionPolicy -Scope Process Bypass`.

## 3. llama.cpp

Skrypt pobiera najnowsze oficjalne archiwum Windows x64 CPU bezpośrednio z
wydania `ggml-org/llama.cpp` i rozpakowuje je poza repozytorium:

```powershell
.\scripts\setup_llama_windows.ps1
```

Docelowa binarka to zwykle:

```text
C:\Users\<CURRENT_USER>\AppData\Local\APPv2\llama.cpp\llama-server.exe
```

Można też ręcznie pobrać asset `Windows x64 (CPU)` z
https://github.com/ggml-org/llama.cpp/releases i rozpakować go w tym katalogu.

## 4. Model GGUF

Model Qwen3.5-2B Q4_K_M jest dużym plikiem i skrypt nie pobiera go domyślnie.
Świadome pobranie jednego modelu:

```powershell
.\scripts\setup_llama_windows.ps1 -DownloadModel
```

Plik trafia do:

```text
C:\Users\<CURRENT_USER>\AppData\Local\APPv2\models\Qwen3.5-2B-Q4_K_M.gguf
```

Źródłem jest repozytorium modelu
https://huggingface.co/openresearchtools/Qwen3.5-2B-GGUF. Model ani binarki nie
są dodawane do Git.

## 5. Konfiguracja i uruchomienie

Skrypt środowiska wykrywa liczbę logicznych procesorów i ustawia połowę, nie
więcej niż cztery wątki. Ustawia też ścieżki z `LOCALAPPDATA`, kontekst 2048,
port 8080, schemat `nested` oraz bezwarunkowo wyłącza wykonanie sprzętowe:

```powershell
.\scripts\ai_env_windows.ps1
.\.venv\Scripts\python.exe tools\ai_plan_tester.py
```

Tester działa w pętli do podania pustej linii. Każdy wynik zapisuje w osobnym
podkatalogu `local_ai_tests\` jako `request.txt`, `segments.json`,
`model_extraction.json`, `final_plan.json` i `metrics.json`. Użyj `--no-save`,
aby wyłączyć zapis, albo przekaż jedno polecenie bez trybu interaktywnego:

```powershell
.\.venv\Scripts\python.exe tools\ai_plan_tester.py "Ustaw piezo na 12 V."
```

`COMPLETE` oznacza poprawny i kompletny plan. `INCOMPLETE` oznacza brak jawnego
argumentu. `INVALID` obejmuje nieobsługiwane czynności oraz naruszenia kontraktu.
„Włącz grzałkę” i „Zapisz plik” pozostają `unsupported`.

## 6. Testy i benchmarki

Testy PC-only, bez Qt, pyserial i sprzętu:

```powershell
.\.venv\Scripts\python.exe -m unittest tests_x.test_ai_pc_only tests_x.test_assistant_grounding
```

Pełny zestaw testów aplikacji wymaga zależności z `requirements.txt`. Część
testów sterowników używa atrap portu, ale importuje stos sprzętowy i nie należy
do minimalnej ścieżki AI. Benchmark modelu także nie wykonuje sprzętu:

```powershell
.\.venv\Scripts\python.exe tests_x\benchmark_measurement_assistant_models.py --mode after
```

Benchmark korzysta z serwera na porcie 18767 zgodnie z jego własną konfiguracją;
tester interaktywny używa portu z `APP_AI_PORT` i sam uruchamia serwer.

## 7. Typowe problemy

- `python` nie jest rozpoznawany: zainstaluj Python z python.org z opcją PATH
  albo użyj launchera `py -3` do utworzenia `.venv`.
- `git` nie jest rozpoznawany: zainstaluj Git for Windows i otwórz nowy
  PowerShell.
- `Activate.ps1 cannot be loaded`: używaj bezpośrednio
  `.\.venv\Scripts\python.exe` albo ustaw `ExecutionPolicy` tylko dla procesu.
- Brak `llama-server.exe`: uruchom `setup_llama_windows.ps1`, a potem ponownie
  `ai_env_windows.ps1`.
- Port 8080 jest zajęty: ustaw np. `$env:APP_AI_PORT="18080"` po wczytaniu
  skryptu środowiska. Tester nie przejmie procesu, który nie jest llama-server.
- Ścieżka modelu zawiera spacje: przypisz ją w cudzysłowie, np.
  `$env:APP_AI_MODEL="C:\Moje modele\model.gguf"`.
- Defender lub firewall pyta o dostęp: serwer nasłuchuje wyłącznie na
  `127.0.0.1`; zezwolenie na sieci publiczne nie jest potrzebne.
- Polskie znaki są uszkodzone: użyj Windows Terminal; w starszej konsoli można
  przed startem wykonać `chcp 65001`. Pliki testera zawsze używają UTF-8.
- Serwer nie startuje: uruchom `& $env:APP_AI_BINARY --version` i sprawdź
  `runs\llama-server.log`.

Domyślne ścieżki Linux/Raspberry Pi pozostają bez zmian. Konfigurację na obu
platformach można nadpisać przez `APP_AI_BINARY`, `APP_AI_MODEL`, `APP_AI_PORT`,
`APP_AI_CONTEXT`, `APP_AI_THREADS`, `APP_AI_TIMEOUT`,
`APP_AI_EXECUTION_ENABLED` i `APP_AI_SCHEMA_FORMAT`.
