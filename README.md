# Analityka — klienci reprezentatywni

Model w Pythonie wybierający domyślnie **1100 klientów podstawowych** oraz
**1100 unikalnych zastępców**, z raportem wag i jakości dopasowania.
Kod nie wymaga GAMS. Solver HiGHS jest dostępny przez SciPy.

## Uruchomienie

1. Pobierz repozytorium i otwórz cały folder w Visual Studio Code.
2. Przygotuj Python 3.10+ (64-bitowy) z Tcl/Tk oraz rozszerzenie Python firmy Microsoft.
3. Zainstaluj zależności z `representative_clients/requirements.txt` i wybierz
   ten sam interpreter w VS Code.
4. Otwórz `uruchom_klientow_reprezentatywnych.py` i kliknij **Run Python File in Terminal**.
5. W formularzu wskaż źródła XLSX i eksport zgód. Najpierw wykonaj sprawdzenie danych.

Pełna instrukcja instalacji, schematu wejść, wyników i limitów:
[START_KLIENCI_REPREZENTATYWNI.md](START_KLIENCI_REPREZENTATYWNI.md).

## Limity i wyniki

- Maksymalnie **24 godziny całego przebiegu**, łącznie z odczytem, obliczeniami
  i zapisem; można wybrać krótszy czas. Program może zakończyć wcześniej.
- Domyślnie do **30 minut na grupę**, skracane według pozostałego budżetu.
- Każdy ukończony OSD dostaje osobny raport częściowy. Pełny raport powstaje
  dopiero po ukończeniu wszystkich OSD.
- Arkusz `Zastepcy` zawiera każdą parę podstawowy–zastępca, obie wagi i błędy.
- Limit czasu nie gwarantuje znalezienia rozwiązania dla całego portfela.

Nadzór czasu działa w launcherze oraz poleceniu
`python -m representative_clients.portfolio_cli`. Nie uruchamiaj bezpośrednio
wewnętrznego modułu `portfolio_worker`.

## Dane i weryfikacja

Repozytorium **nie zawiera danych klientów, zgód, zdjęć ani wyników produkcyjnych**.
Źródła trzymaj lokalnie w `Dane_in`, wyniki w `Dane_out`; oba foldery są ignorowane
przez Git. Nie publikuj danych firmowych w tym publicznym repozytorium.
Testy generują wyłącznie sztuczne dane. Nie wykonano jeszcze walidacji modelu
na rzeczywistych skoroszytach źródłowych.

```powershell
python -m unittest discover -s tests -p "test_representative*.py" -v
```

Wersja pakietu: 1.3. Zweryfikowano 71 testów, w tym limity czasu,
zapis częściowy oraz scenariusze 500 i 1100 par.
