# Wybór reprezentatywnych klientów

Moduł jest odpowiednikiem matematycznym `Model_dobor_klientow_v8.gms`
odtworzonym ze zdjęć kodu. Nie wymaga GAMS ani plików GDX. Korzysta z
otwartego solvera HiGHS dostępnego przez SciPy.

## Nowa lista zgód bez OSD i mała pula (np. 270 PPE)

Aktualna lista może zawierać nagłówki `Numer PPE` oraz
`Właściwy PPE (w przypadku błędów w kolumnie A)` w pierwszych 30 wierszach
dowolnego arkusza. Niepusta korekta ma pierwszeństwo; w przeciwnym razie
używany jest `Numer PPE`. Kody zapisuj jako tekst, z zachowaniem zer
początkowych. Liczb ani formuł Excel w używanym kodzie program nie przyjmuje.

Wskaż dodatkowo **pierwotny plik zgód — mapowanie OSD** (CLI: `--osd-mapping`),
z kolumnami `Kod PP Aktualny` i `OSD Nazwa - PP Aktualny`.
Stary plik służy wyłącznie do przypisania OSD: tylko PPE z nowej listy są
dopuszczone do modelu. Program usuwa powtórzenia i podaje ich liczbę.
Brak dopasowania poprawionego PPE lub sprzeczne OSD zatrzymują import.
Nie następuje powrót do błędnego kodu z kolumny A. Dotychczasowy format zgód
z OSD nadal działa bez dodatkowego pliku.

Po wskazaniu pliku mapowania OSD okno automatycznie dopasowuje **całą aktualną
pulę PPE z dostępnymi profilami po wykluczeniach**. Liczba wynika z danych;
nie wpisuje się 270 ani innego celu. Nie obowiązuje limit liczby klientów,
a zastępcy są wyłączeni. Pole ręcznego celu i przełącznik zastępców są wtedy
nieaktywne. Duplikaty nie zwiększają liczby punktów. Raport pokazuje liczby
PPE z nowej listy, występujących w źródłach oraz pozostałych po wykluczeniach.

CLI działa tak samo po podaniu `--osd-mapping` bez `--total-clients`.
Tryb można też włączyć jawnie przez `--all-consented`, również dla starego
formatu zgód z OSD. W tym trybie nie podaje się ręcznej liczby klientów.
Dotychczasowy ręczny dobór 1–1100 i opcjonalnych zastępców pozostaje dostępny
przez `--total-clients`; okno używa go przy braku pliku mapowania.

Liczbę grup można podać w oknie lub przez `--groups`. Jedna grupa dopasowuje
dostępne PPE danego OSD wspólnie. Domyślne cztery grupy są czterema osobnymi
próbami odtworzenia całego bilansu OSD. Do porównania dwóch pul zachowaj
identyczną liczbę grup, okres, bilans, ograniczenia wag i ustawienia solvera.
Nie zakładamy z góry pogorszenia — raport zawiera MAE, RMSE i błędy względne.

Dla zmienionej listy i trybu zastępców utwórz **nowy plik planu**, np.
`Plan_aktualne_zgody.json`. Plan zapisuje tryb całej puli, rzeczywistą liczbę
klientów, tryb zastępców i ścieżkę mapowania, a ponowne
uruchomienie sprawdza zgodność dopuszczonych PPE. Bez zastępców OSD z zerową
pulą dostaje przydział 0; raport `Pokrycie_OSD` i opis wyniku wyraźnie oznaczają,
że jego bilans nie jest oceniony. Nie jest to wynik dla pełnego portfela.

Przykład po dodaniu wszystkich źródeł `--input`:

```powershell
& $python -m representative_clients.portfolio_cli `
  --input "Dane_in\Modele\Model_wszystkie_OSD.xlsx" `
  --consents "Dane_in\Zgody\Nowe_zgody.xlsx" `
  --osd-mapping "Dane_in\Zgody\Pierwotne_zgody.xlsx" `
  --allocation-plan "Dane_out\Plan_aktualne_zgody.json" --validate-full
```

Jeśli źródła są w osobnych plikach, powtórz `--input` dla każdego.
Po kontroli zastąp `--validate-full` parametrem
`--output "Dane_out\Wyniki_aktualnej_puli.xlsx"`. Do niezależnej oceny można dodać
`--holdout-days N`; muszą zostać co najmniej dwa dni do dopasowania.

## Finalny tryb 8 OSD — zalecane uruchomienie

**Instrukcja VS Code, źródeł, wyników i czasu obliczeń:**
[START_KLIENCI_REPREZENTATYWNI.md](../START_KLIENCI_REPREZENTATYWNI.md).
Otwórz plik startowy i kliknij Run Python File in Terminal. Wybór plików,
trybu kontroli/próby/obliczeń i limitu czasu odbywa się w jednym oknie.
Cały przebieg ma limit **24 h**, łącznie z odczytem i zapisem. Domyślnie grupa
ma do 30 min; program może skończyć wcześniej. Ukończone OSD są zapisywane
osobno w folderze *_czesci_*. Pełny wynik w tym czasie nie jest gwarantowany.

Poniższy opis dotyczy ręcznego doboru bez automatycznego trybu całej puli.
Finalny przebieg łączy model główny z logiką zastępców i aktualnym plikiem
zgód. Domyślnie wybiera dokładnie **1100 klientów podstawowych** (ustawialne
od 1 do 1100, w granicach dostępnej puli) łącznie dla:
Białegostoku, Lublina, Łodzi Miasto, Łodzi Teren, Rzeszowa,
Skarżyska-Kamiennej, Warszawy i Zamościa. Limit jest dzielony proporcjonalnie
do liczby dostępnych klientów w OSD, z zachowaniem miejsca na jednego
unikalnego zastępcę dla każdego wybranego PPE.

Źródła mogą mieć pięć arkuszy (lista w Klienci oraz profile w Klienci_part_1
i Klienci_part_2) albo trzy arkusze, jak Białystok (profile w Klienci: A=OSD,
B=PPE, C=data, D+=godziny; nagłówki w wierszu 2). W obu przypadkach potrzebne
są Oddzial/Oddział oraz Ograniczenia. Program rozpoznaje układ automatycznie,
bez zmieniania Excela; można połączyć oba formaty w jednym przebiegu.

Najprościej uruchomić na Windows:

```powershell
& $python uruchom_klientow_reprezentatywnych.py
```

Program poprosi kolejno o:

1. wszystkie skoroszyty modeli głównych dla 8 OSD (można zaznaczyć wiele
   plików, także kilka części jednego OSD);
2. aktualny skoroszyt zgód;
3. dokładną łączną liczbę klientów podstawowych (domyślnie 1100, zakres 1–1100);
4. folder wyników i tryb pracy; nazwa XLSX i dziennika jest nadawana automatycznie.

Wersja konsolowa:

```powershell
& $python -m representative_clients.portfolio_cli `
  --input "Dane_in\Model_Bialystok.xlsx" `
  --input "Dane_in\Model_Lublin.xlsx" `
  --input "Dane_in\Model_Lodz_Miasto_w1.xlsx" `
  --input "Dane_in\Model_Lodz_Miasto_w2.xlsx" `
  --input "Dane_in\Model_Lodz_Teren.xlsx" `
  --input "Dane_in\Model_Rzeszow.xlsx" `
  --input "Dane_in\Model_Skarzysko.xlsx" `
  --input "Dane_in\Model_Warszawa.xlsx" `
  --input "Dane_in\Model_Zamosc.xlsx" `
  --consents "Dane_in\Aktualne_zgody.xlsx" `
  --total-clients 1100 `
  --total-time-limit 86400 `
  --time-limit 1800 `
  --output "Dane_out\Wyniki_klienci_final.xlsx"
```

Najpierw można użyć `--validate-only`. Ten tryb sprawdza osiem OSD, nagłówki
zgód, dostępność PPE, pojemność na pary klient–zastępca i podział limitu, ale
nie czyta wielkich profili godzinowych i nie uruchamia solvera.

Pełne sprawdzenie danych bez solvera zapewnia `--validate-full`.
Tak działa domyślny tryb „Sprawdzenie wszystkich danych” w oknie startowym.
W dzienniku zapisywany jest czas odczytu, a podczas obliczeń także czasy grup i OSD.
Limit globalny można zmniejszyć, ale nie przekroczyć 86400 s. Kod 124 oznacza
wyczerpanie budżetu. Uruchamiaj `portfolio_cli` lub okno VS Code: oba korzystają
z niezależnego nadzorcy procesu. Bezpośrednie wywołanie funkcji `main()` nie
zapewnia twardego przerwania podczas operacji natywnych.

Plik zgód może mieć dowolną nazwę arkusza. Program odnajduje nagłówki
`Kod PP Aktualny` oraz `OSD Nazwa - PP Aktualny` w pierwszych 30 wierszach.
Kody PPE muszą być tekstem. PPE bez zgody nie może zostać ani klientem
podstawowym, ani zastępcą. Klient wymagany w starym arkuszu `Ograniczenia`,
którego nie ma w aktualnym pliku zgód, zatrzymuje przebieg z czytelnym błędem.

Finalny skoroszyt zawiera `Podsumowanie`, `Wybrani`, `Zastepcy`, `Bilans`,
`Diagnostyka`, `Solver`, `Lejek_danych`, `Konfiguracja` i `Tekst_do_maila`.
Arkusz `Zastepcy` wypisuje wszystkie pary podstawowy–zastępca, obie wagi
i diagnostykę każdej podmiany. Domyślne 1100 par wymaga co najmniej 2200
różnych dopuszczonych PPE, odpowiednio rozłożonych po OSD.
Ostatni arkusz nie zawiera identyfikatorów PPE i jest gotowym opisem metody
oraz wyniku do wykorzystania w korespondencji.

## Starszy tryb pojedynczego OSD — zgodność z GAMS v8

Poniższe ustawienia i siedmioarkuszowy raport dotyczą starszego polecenia
`python -m representative_clients`. Aktualny launcher używa `portfolio_cli`,
który obsługuje wszystkie OSD, osobny plik zgód, dokładne limity i zastępców.

### Co robi starszy model

Dla każdego oddziału:

1. usuwa klientów wpisanych jako wykluczeni w kolumnie A arkusza
   `Ograniczenia`;
2. dzieli pozostałych round-robin na grupy `w1..wn` w kolejności z arkusza
   `Klienci`;
3. dla każdej grupy niezależnie wybiera maksymalnie `K` klientów i ich
   nieujemne wagi;
4. minimalizuje sumę bezwzględnych godzinowych różnic między bilansem
   oddziału a ważoną sumą profili wybranych klientów;
5. zapisuje wybór, odtworzony bilans, udziały poboru/oddania i diagnostykę.

Domyślne wartości są zgodne z widocznym kodem GAMS v8:

- 4 grupy;
- maksymalnie 50 klientów **w każdej grupie**;
- maksymalna kontrybucja klienta: 20% średniego bezwzględnego bilansu;
- limit czasu: 14 400 sekund na grupę;
- względna luka MIP: 10% (domyślne `OptCR` środowiska GAMS; linia
  ustawiająca `optcr` w sfotografowanym v8 jest zakomentowana).

Grupy `w1..w4` nie są klastrami geograficznymi. Grupowanie według lokalizacji
i podobieństwa profili będzie osobnym etapem po pozyskaniu odpowiednich kolumn.

> **Starszy tryb — zgody marketingowe:** ten tryb nie łączy się z systemem zgód i nie
> sprawdza ich samodzielnie. Ufa zawartości kolumny A arkusza `Ograniczenia`.
> Przed każdym uruchomieniem trzeba więc zasilić tę kolumnę kompletną, aktualną
> listą PPE, których nie wolno wybrać.

## Instalacja

Wymagany jest 64-bitowy Python 3.10 lub nowszy. W PowerShellu, z głównego
katalogu projektu, najpierw sprawdź wersję:

```powershell
py -3 --version
py -3 -c "import struct; print(struct.calcsize('P') * 8, 'bit')"
```

Jeżeli pokazana wersja jest niższa niż 3.10 albo drugi wynik nie brzmi
`64 bit`, nie kontynuuj w tym interpreterze. Utwórz osobne środowisko i
zainstaluj tylko zależności tego modułu:

```powershell
py -3 -m venv .venv-representative-clients
.\.venv-representative-clients\Scripts\python.exe -m pip install -r representative_clients\requirements.txt
```

W dalszych przykładach zmienna `$python` oznacza interpreter z tego środowiska:

```powershell
$python = ".\.venv-representative-clients\Scripts\python.exe"
```

### Test instalacji bez danych służbowych

Przed otwieraniem dużego Excela uruchom test syntetyczny:

```powershell
& $python -m unittest discover -s tests -p "test_representative*.py" -v
```

Test nie korzysta z danych klientów. Dopiero komunikat `OK` potwierdza, że
środowisko i solver działają poprawnie.

## Przed pracą z Excelem

- zamknij wejściowy skoroszyt oraz wcześniejszy plik wynikowy w Excelu;
- nie zapisuj wyniku pod ścieżką wejścia;
- traktuj wejścia i wyniki jak dane służbowe zawierające identyfikatory PPE;
- nie dodawaj tych plików do repozytorium. Dołączony `.gitignore` obejmuje
  wyłącznie katalogi `Dane_in`, `Dane_out` i artefakty tego modułu; nie jest on
  zabezpieczeniem dostępu do danych.

Zamknięcie Excela ogranicza ryzyko odczytu pliku w trakcie zapisu oraz błędów
blokady przy tworzeniu wyniku.

## Uruchamianie oddziałami

Starsze polecenie należy uruchamiać **osobno dla każdego z 8 OSD/oddziałów**: Białystok,
Łódź Miasto, Łódź Teren, Lublin, Rzeszów, Skarżysko-Kamienna, Warszawa i
Zamość. Parametr `--branch` musi dokładnie odpowiadać nazwie w arkuszu
`Oddzial`. Każde uruchomienie musi mieć własny plik `--output`, najlepiej z
nazwą OSD i datą danych, np. `Wyniki_python_Zamosc_20260318.xlsx`.

Nie uruchamiaj ośmiu dużych modeli równolegle na komputerze roboczym. Jeden
skoroszyt wejściowy może mieć kilkaset MB, a solver potrzebuje dodatkowej
pamięci.

## Bezpieczna walidacja wejścia

Najpierw należy sprawdzić strukturę danych bez uruchamiania solvera:

```powershell
& $python -m representative_clients `
  --input "Dane_in\Model_2025_20260318_Zamosc_w1_w4_parts.xlsx" `
  --branch PGED_Zamosc `
  --validate-only
```

Walidacja niczego nie zapisuje i nie uruchamia optymalizacji, ale **czyta cały
skoroszyt XLSX**. Na dużym pliku może więc potrwać i zużyć dużo pamięci. Nie
przerywaj jej tylko dlatego, że dany etap trwa długo. Program pokazuje nazwę
bieżącego etapu oraz postęp co 100 000 wierszy dużych arkuszy profili.

## Uruchomienie

```powershell
& $python -m representative_clients `
  --input "Dane_in\Model_2025_20260318_Zamosc_w1_w4_parts.xlsx" `
  --branch PGED_Zamosc `
  --output "Dane_out\Wyniki_python_Zamosc_20260318.xlsx"
```

Istniejący wynik nie zostanie zastąpiony. Świadome zastąpienie wymaga flagi
`--overwrite`. Program zawsze odrzuca próbę zapisania wyniku pod tą samą
ścieżką co wejście.

Przy pierwszym teście na rzeczywistym pliku warto użyć krótkiego limitu:

```powershell
& $python -m representative_clients `
  --input "Dane_in\Model_2025_20260318_Zamosc_w1_w4_parts.xlsx" `
  --branch PGED_Zamosc `
  --output "Dane_out\Wyniki_python_Zamosc_20260318_test.xlsx" `
  --time-limit 60 `
  --solver-log
```

Domyślny limit 14 400 sekund dotyczy każdej grupy osobno. Przy czterech
grupach teoretyczny maksymalny czas solvera wynosi 16 godzin. Program pokazuje
postęp między grupami. Kod wyjścia `2` oznacza, że zapisano rozwiązanie, ale
co najmniej jedna grupa zatrzymała się np. przez limit czasu bez potwierdzenia
optymalności; należy wtedy sprawdzić arkusz `Diagnostyka`. W PowerShellu kod
ostatniego uruchomienia można sprawdzić poleceniem `$LASTEXITCODE`.

Kod `2` nie oznacza automatycznie, że zapisane rozwiązanie jest bezużyteczne:
oznacza, że przynajmniej dla jednej grupy solver zapisał rozwiązanie dopuszczalne,
ale nie potwierdził optymalności przed zatrzymaniem. Nie traktuj jednak takiego
wyniku jako finalnego bez oceny celu, luki MIP i naruszeń w `Diagnostyka`. Jeżeli
solver nie znajdzie rozwiązania dopuszczalnego, program zakończy się błędem i nie
powinien utworzyć kompletnego skoroszytu wynikowego.

Aktualna wersja zapisuje wynik dopiero po zakończeniu wszystkich grup. Nie ma
jeszcze mechanizmu wznowienia po przerwaniu procesu, dlatego przed pełnym
uruchomieniem koniecznie wykonaj walidację i krótki test 60-sekundowy.

## Oczekiwany układ starego Excela

Czytnik odwzorowuje zakresy widoczne w GAMS v8:

- `Oddzial` albo `Oddział`: nagłówki godzin od `C2`, dane od wiersza 3;
  kolumny A–B to oddział i data;
- `Klienci`: identyfikatory od `A2`;
- `Klienci_part_1` i `Klienci_part_2`: nagłówki godzin od `D2`, dane od
  wiersza 3; kolumny A–C to oddział, klient i data;
- `Ograniczenia`: wykluczeni od `A2`, wymagani od `E2`, ich wagi w kolumnie F.

Brakujące wartości profilu są traktowane jak zero, a części 1 i 2 są
sumowane tak jak w GAMS-ie. Jeżeli komórki zawierają formuły, plik musi być
najpierw przeliczony i zapisany w Excelu. Formuła bez zapisanego wyniku jest
odrzucana zamiast cichego zastąpienia zerem.

Tak jak GAMS, czytnik buduje globalny iloczyn wszystkich dat z arkusza
`Oddzial` i wszystkich godzin z jego nagłówka. W pliku wielooddziałowym daty
występujące wyłącznie przy innym OSD pozostają więc w modelu wybranego OSD z
bilansem docelowym równym zero.

Kolumna A arkusza `Ograniczenia` jest techniczną listą wykluczeń. Sam fakt
poprawnego wczytania skoroszytu nie dowodzi, że lista odzwierciedla aktualne
zgody marketingowe — to należy sprawdzić w procesie przygotowania danych.

## Wynik

Plik wynikowy zawiera arkusze:

- `Wyniki` — odtworzony ze zdjęć układ starego eksportu GDXXRW: wagi od `B3`,
  bilans od `G2`, istotność dzienna od `N2`, istotność całego okresu od `U2`;
- `Wybrani`;
- `Bilans`;
- `Istotnosc_dzienna`;
- `Istotnosc_all`;
- `Diagnostyka`;
- `Konfiguracja`.

Skoroszyt jest najpierw tworzony jako plik tymczasowy w katalogu docelowym i
dopiero po poprawnym zamknięciu publikowany pod nazwą wyniku. Na lokalnym
systemie plików chroni to wcześniejszy poprawny plik przed błędem eksportu;
udział sieciowy może mieć słabsze gwarancje, dlatego pierwszy test wykonaj
lokalnie.

## Status weryfikacji

Rdzeń optymalizacji, parser próbnego skoroszytu i eksport przechodzą testy
syntetyczne. Przed użyciem produkcyjnym trzeba jeszcze:

1. potwierdzić układ pięciu arkuszy na zanonimizowanych ekranach;
2. porównać wartość celu i wykonalność z jednym zapisanym wynikiem GAMS;
3. potwierdzić jednostki i konwencję znaku pobór/oddanie;
4. zmierzyć czas i szczytowe użycie RAM na jednym rzeczywistym pliku (macierz
   solvera została odchudzona, ale HiGHS nadal tworzy własne kopie danych);
5. dodać etap lokalizacyjnego grupowania do kontaktu.

Dokładna lista bezpiecznych ekranów potrzebnych do tej walidacji znajduje się
w pliku `VALIDATION_CHECKLIST.md`.
