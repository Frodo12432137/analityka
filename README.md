# Analityka — klienci reprezentatywni

Model w Pythonie wybierający domyślnie **1100 klientów podstawowych** oraz
**1100 unikalnych zastępców**, z raportem wag i jakości dopasowania.
Kod nie wymaga GAMS. Solver HiGHS jest dostępny przez SciPy.

Obsługuje także nową listę zgód z kolumnami **Numer PPE** i **Właściwy PPE**:
poprawiony kod ma pierwszeństwo, a OSD jest przypisywane z pierwotnego pliku zgód.
Stary plik służy wyłącznie do mapowania. Po jego wskazaniu liczba PPE wynika
automatycznie z nowej listy i dostępnych profili, bez ręcznego limitu i bez
rezerwowania klientów na zastępców. Szczegółowe ustawienia opisano
w [instrukcji nowych zgód](START_KLIENCI_REPREZENTATYWNI.md#nowe-zgody-lista-ppe-bez-osd-np-270-punktów).

## Uruchomienie

1. Pobierz repozytorium i otwórz cały folder w Visual Studio Code.
2. Przygotuj Python 3.10+ (64-bitowy) z Tcl/Tk oraz rozszerzenie Python firmy Microsoft.
3. Zainstaluj zależności z `representative_clients/requirements.txt` i wybierz
   ten sam interpreter w VS Code.
4. Otwórz `uruchom_klientow_reprezentatywnych.py` i kliknij **Run Python File in Terminal**.
5. W formularzu wskaż źródła XLSX i eksport zgód. Najpierw wykonaj sprawdzenie danych.

Obsługiwane są oba układy wejścia: profile w `Klienci_part_1` i `Klienci_part_2`
oraz profile bezpośrednio w `Klienci` (np. Białystok). Program rozpoznaje je
automatycznie, bez przerabiania plików Excel.

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

Testy obejmują oba układy profili Excel, limity czasu, zapis częściowy,
scenariusze 500 i 1100 par oraz małą pulę 270 PPE bez zastępców, korekty PPE,
mapowanie OSD i brak kandydatów w oddziale.
