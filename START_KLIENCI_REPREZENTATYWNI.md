# Start w Visual Studio Code — klienci reprezentatywni

Otwórz cały rozpakowany folder pakietu w VS Code przez **File → Open Folder**.
Plik startowy to **uruchom_klientow_reprezentatywnych.py**. Ścieżki do danych
wskazujesz w oknie programu; nie trzeba wpisywać ich w kodzie.

## 1. Jednorazowe przygotowanie Pythona

Potrzebny jest Python 3.10 lub nowszy, **64-bitowy**, z Tcl/Tk, oraz rozszerzenie
**Python firmy Microsoft** w VS Code. Wersja Pythona musi mieć zainstalowane
biblioteki z dołączonego pliku requirements.

Otwórz terminal PowerShell w głównym folderze pakietu i wykonaj:

~~~powershell
py -3 -m venv .venv-representative-clients
.\.venv-representative-clients\Scripts\python.exe -m pip install -r representative_clients\requirements.txt
~~~

Zainstalujesz tylko numpy, pandas, scipy i openpyxl wraz z ich zależnościami.
Do tego modelu używaj właśnie powyższego pliku requirements.

W VS Code naciśnij **Ctrl+Shift+P → Python: Select Interpreter → Enter interpreter path**
i wskaż:

~~~text
.venv-representative-clients\Scripts\python.exe
~~~

To interpreter, którego ma używać strzałka. Jeśli w VS Code był wcześniej
wybrany inny Python, zmień go raz na powyższy. Program poda w terminalu
konkretną komendę instalacji, jeżeli w wybranym interpreterze brakuje bibliotek.

## 2. Uruchomienie strzałką

1. Otwórz w edytorze plik **uruchom_klientow_reprezentatywnych.py**.
2. Kliknij **▶ Run Python File in Terminal** w prawym górnym rogu.
3. W oknie kliknij **Dodaj pliki…** i zaznacz wejścia modelu głównego.
   Można dodawać kolejne pliki z innych folderów.
4. Przy **Aktualny plik zgód** kliknij **Wybierz…** i wskaż jeden XLSX.
5. Wskaż folder wyników. Domyślnie wybrano **1100 klientów podstawowych łącznie**
   dla wszystkich OSD (możesz zmienić tę liczbę w zakresie 500–1100).
   Dodatkowo program dobierze po jednym unikalnym zastępcy: przy domyślnym
   ustawieniu to **1100 podstawowych + 1100 zastępców = 2200 różnych PPE**.
6. Wybierz tryb pracy i kliknij **Uruchom**. Postęp zobaczysz w terminalu VS Code.

Domyślny limit **całego pojedynczego przebiegu to 24 godziny**. Możesz wpisać
mniej w polu „Limit godzin CAŁEGO przebiegu”. Limit obejmuje także sprawdzanie
danych. Czas wybierania plików w formularzu nie jest wliczany.

Domyślny tryb to **Sprawdzenie wszystkich danych**: odczytuje także profile
i kontroluje formuły, ale nie uruchamia optymalizacji. Po poprawnej kontroli
uruchom ponownie strzałką i wybierz **Próba: 60 sekund na grupę** albo **Pełne obliczenia**.
Próba korzysta z pełnego wejścia, lecz ma krótki limit poszukiwania rozwiązania;
może zakończyć się bez wyniku, jeśli solver nie zdąży znaleźć rozwiązania dopuszczalnego.

Jest też konfiguracja **Run and Debug / F5 → Klienci reprezentatywni — wybór danych**.
W obu przypadkach wybierz interpreter przygotowany w punkcie 1.
Sposób działania przycisku opisuje [dokumentacja Microsoft](https://code.visualstudio.com/docs/python/run).

## 3. Gdzie umieścić pliki

Przy pierwszym otwarciu formularza program tworzy obok kodu poniższe foldery.
To wygodny układ; można również wskazać pliki z innych lokalizacji.

~~~text
klienci_reprezentatywni/
├── uruchom_klientow_reprezentatywnych.py
├── representative_clients/             kod i requirements.txt
├── Dane_in/
│   ├── Modele/                         skoroszyty modeli głównych
│   └── Zgody/                          aktualny eksport zgód
└── Dane_out/                           wyniki XLSX i dzienniki .log
~~~

Program odczytuje **pliki jawnie dodane do listy** w oknie. Samo włożenie pliku
do folderu nie wybiera go do obliczeń. Nie ma połączenia z SQL ani z serwerem
Marka: źródłem są wskazane eksporty XLSX.

## 4. Co przygotować jako dane wejściowe

### A. Dane historyczne i ograniczenia dla wszystkich 8 OSD

Przygotuj właściwe, aktualne skoroszyty **modelu głównego**, takie jak pliki
zaczynające się od Model_2025_20260318_ widoczne w folderze Dane_in.
Nazwa pliku może być dowolna — OSD jest odczytywane z arkusza Oddzial/Oddział.

| OSD | Typowa nazwa w danych |
|---|---|
| Białystok | PGED_Bialystok |
| Lublin | PGED_Lublin |
| Łódź Miasto | PGED_Lodz_Miasto |
| Łódź Teren | PGED_Lodz_Teren |
| Rzeszów | PGED_Rzeszow |
| Skarżysko-Kamienna | PGED_Skarzysko_Kamienna |
| Warszawa | PGED_Warszawa |
| Zamość | PGED_Zamosc |

Zwykle będzie osiem plików. Jeśli jedno OSD rzeczywiście ma kilka części,
dodaj wszystkie potrzebne części. Nie dokładaj równolegle starych wersji i kopii
tego samego zbioru. Nazwa w1/w2/w3/w4 sama w sobie nie oznacza, że trzeba
połączyć wszystkie te pliki: zdecyduj na podstawie zawartości i wersji wejścia.

Czytnik automatycznie rozpoznaje dwa układy; można je łączyć w jednym przebiegu.
Nazwy plików nie decydują o sposobie importu.

**Układ dzielony (pozostałe OSD) — pięć arkuszy:**

| Arkusz | Zawartość odczytywana przez program |
|---|---|
| Klienci | Lista wszystkich identyfikatorów PPE w kolumnie A, od A2; jeden PPE na wiersz. |
| Klienci_part_1 | Wiersz 2: A = OSD, B = PPE, C = data, od D2 godziny. Od wiersza 3: bilans pobór–oddanie danego PPE. |
| Klienci_part_2 | Taki sam układ jak część 1. Czytnik **sumuje** wartości obu arkuszy dla tego samego PPE i okresu. |
| Oddzial lub Oddział | Wiersz 2: A = OSD, B = data, od C2 godziny. Od wiersza 3: historyczny bilans całego OSD. |
| Ograniczenia | Od A2: wykluczeni PPE; od E2: wymagani PPE; w F: ich ustalone wagi. Nieużywane listy mogą być puste. |

Oba arkusze części muszą istnieć. Jeśli część 2 nie zawiera danych, pozostaw
jej prawidłowe nagłówki; nie kopiuj do niej danych z części 1, bo podwoiłoby
to profile. PPE i daty w częściach muszą odpowiadać listom w Klienci i Oddzial.

**Układ z profilami w Klienci (np. Model_2025_20260318_Bialystok.xlsx) — trzy arkusze:**

| Arkusz | Zawartość odczytywana przez program |
|---|---|
| Klienci | Wiersz 2: A = Oddzial/Oddział, B = Klient, C = dataCET/Data, od D2 godziny. Od wiersza 3: OSD, PPE, data i bilans godzinowy. |
| Oddzial lub Oddział | Jak w układzie dzielonym: dane od wiersza 3, data w B, godziny od C. |
| Ograniczenia | Tak jak wyżej: wykluczeni w A, wymagani w E, ich ustalone wagi w F. Listy mogą być puste. |

Lista PPE powstaje z kolumny B arkusza Klienci, w kolejności pierwszego wystąpienia.
Powtórzenie PPE dla innej daty jest prawidłowe; powtórzenie całego klucza
OSD–PPE–data jest błędem. Wiersz 1 z sumami kontrolnymi nie jest profilem.
Nie trzeba dodawać ani przemianowywać arkuszy w Białymstoku.

Arkuszy Klienci_part_1 i Klienci_part_2 nie powinno być w układzie trzyarkuszowym.
Jeśli występują razem z profilami w Klienci, program zgłasza niejednoznaczność,
zamiast ryzykować podwójne zliczenie danych. Niekompletny układ dzielony także
zostanie odrzucony; program nie dopisuje brakujących części jako zer.

Użyj źródła modelu głównego. W plikach historycznego modelu zastępców mogą
występować inne listy wykluczeń i stare wagi w I:J — te kolumny nie są importowane.
Wagi klientów podstawowych i zastępców są liczone przez Pythona, z zachowaniem
ewentualnych wymaganych wag z E:F.

Do obliczeń nie trzeba dostarczać plików .gms, .gdx, .lst, .lxi ani starych
wyników Wyniki_Pz. Mogą służyć do późniejszego porównania rezultatów.

### B. Jeden aktualny eksport zgód

Przygotuj XLSX zawierający **wyłącznie PPE z aktualną zgodą** i kolumny:

| Kolumna | Znaczenie |
|---|---|
| Kod PP Aktualny | PPE zapisany jako tekst, zgodny z identyfikatorem w profilach. |
| OSD Nazwa - PP Aktualny | OSD danego PPE, np. PGE Dystrybucja S.A. Oddział Białystok. |

Nagłówki powinny być w pierwszych 30 wierszach, w jednym arkuszu
(np. page). Program wybiera pierwszy arkusz zawierający oba nagłówki.
Inne kolumny mogą pozostać. Nazwa pliku jest dowolna.
Program traktuje obecność w tym eksporcie jako zgodę; nie interpretuje dodatkowych
kolumn TAK/NIE, więc eksport musi być wcześniej ograniczony do aktualnych zgód.

Identyfikatory PPE w każdym pliku muszą być tekstem. Zmiana formatu liczby
na „Tekst” po utracie cyfr w Excelu nie przywróci oryginalnego identyfikatora.
Wymagany PPE bez zgody albo jednocześnie wykluczony zatrzyma kontrolę danych.

### C. Spójność wejścia

Użyj tych samych jednostek i konwencji znaku dla profili PPE i bilansu OSD.
Kilka skoroszytów jednego OSD musi mieć te same daty, godziny, ich kolejność
oraz ten sam bilans oddziału. Powtórzony PPE o identycznym profilu jest
deduplikowany; sprzeczne profile lub wymagane wagi są zgłaszane jako błąd.

Zapisz przeliczone skoroszyty w Excelu przed odczytem, jeśli zawierają formuły.
Formuła bez zapisanego wyniku jest odrzucana. Puste komórki liczbowe są
traktowane jak zero zgodnie ze starym importem GAMS.
Log pokazuje nazwę aktualnie kontrolowanego pliku i rozpoznany układ.
Błędy układu lub danych importu zawierają nazwę pliku i szczegóły problemu.

Potrzeba co najmniej dwóch dopuszczonych PPE na każdą parę podstawowy–zastępca
w danym OSD. Dla 1100 podstawowych jest to minimum 2200 różnych dopuszczonych
PPE łącznie, odpowiednio rozłożonych po OSD. Sam zapas liczebny nie gwarantuje
wykonalności ograniczeń wag ani jakości dopasowania.

## 5. Co powstanie na wyjściu

Nie przygotowujesz ręcznie danych wyjściowych ani szablonu raportu.
Program zapisze w wybranym folderze:

- **Wyniki_pelny_DATA_GODZINA.xlsx** lub **Wyniki_proba_DATA_GODZINA.xlsx**:
  Podsumowanie, Wybrani, Zastepcy, Bilans, Diagnostyka, Solver,
  Lejek_danych, Konfiguracja i Tekst_do_maila.
- **Przebieg_TRYB_DATA_GODZINA.log**: użyte ścieżki, ustawienia, postęp,
  czasy grup i OSD, statusy oraz ewentualny błąd. Log może zawierać PPE z komunikatów błędu.
- **Wyniki_…_czesci_LOSOWYIDENTYFIKATOR/**: osobny XLSX dla każdego
  ukończonego OSD, zapisany od razu po wyborze jego klientów i zastępców.
  Raporty mają oznaczenie **CZĘŚCIOWY** w Konfiguracji i Tekście_do_maila.

Arkusz **Zastepcy wypisuje każdą parę**, a nie tylko przykłady: przy domyślnej
liczbie będzie 1100 wierszy danych. Każdy zawiera OSD, grupę, PPE podstawowy
i zastępczy, obie wagi, błędy podmiany oraz korelację profili. Zastępca pochodzi
z tego samego OSD, nie jest klientem podstawowym i nie powtarza się w innych parach.

Tryb sprawdzania tworzy tylko dziennik. Pełny raport jest zapisywany po
zakończeniu wszystkich OSD. Częściowe raporty ukończonych OSD pozostają także
po limicie czasu lub błędzie późniejszego etapu; obecnie nie ma automatycznego
wznowienia od ostatniego OSD. Nie traktuj częściowego raportu jako pełnej listy 1100 par.
Nowe nazwy zawierają znacznik czasu. Wyników nie wpisuje się do plików wejściowych.

Solver kończy przy zadanej tolerancji luki MIP (domyślnie 10%) lub limicie czasu.
Status sukcesu nie oznacza dowodu ścisłego optimum przy zerowej luce.
Zastępcy są dobierani spośród krótkich list podobnych profili; skojarzenie 1:1
jest optymalizowane w obrębie tych list, a nie dowiedzione dla wszystkich
możliwych par. W raporcie oceniaj też błędy podmian.

## 6. Ile potrwa liczenie

**Maksymalnie 24 godziny na jeden przebieg, z możliwością wcześniejszego zakończenia.**
Jest to limit, nie oszacowanie czasu do znalezienia dobrego rozwiązania.
Na rzeczywistych plikach z komputera służbowego nie wykonano jeszcze pomiaru.
Na czas wpływa liczba kandydatów po zgodach i okresów, trudność wyboru,
procesor, RAM oraz odczyt dużych XLSX. Nie ma gwarancji znalezienia pełnego
rozwiązania dla 1100 par w tym budżecie.

Domyślnie grupa ma do **30 minut**. Przy 8 OSD × 4 grupy daje to do 16 godzin
samego solvera; odczyt, budowa modeli, zastępcy i eksport też muszą zmieścić
się w globalnych 24 godzinach. Próba ma do 60 sekund na grupę, czyli do
32 minut samego solvera. Wszystkie etapy mają wspólny limit globalny.

Program skraca limit kolejnego solve do udziału pozostałego czasu w liczbie
nierozwiązanych grup i rezerwuje do 10 minut (10% krótszego przebiegu) na
pozostałe etapy. Dokładny limit danego solve oraz pozostały czas są w logu.
To nie gwarantuje, że rezerwa wystarczy na wszystkie operacje wejścia/wyjścia.

Niezależny proces nadzorczy zatrzymuje worker po upływie limitu także wtedy,
gdy trwa odczyt Excela, kod natywny solvera albo dobór zastępców. Kod zakończenia
**124** oznacza wyczerpanie budżetu czasu. Wcześniej ukończone raporty OSD
pozostają w folderze *_czesci_*. Bieżący, nieukończony OSD może zostać utracony;
pełny raport może nie powstać. Zapisany atomowo XLSX nie jest zastępowany
nieukończonym eksportem. Przerwanie może zostawić ukryty plik `.tmp.xlsx` —
nie traktuj go jako wyniku. Samo zakończenie procesu i domknięcie logu mogą
potrwać jeszcze chwilę; obliczeniom nie przyznaje się dodatkowego czasu.

Nadzór działa przy uruchomieniu strzałką oraz poleceniu
`python -m representative_clients.portfolio_cli`. Nie uruchamiaj bezpośrednio
modułu `portfolio_worker`; wywołanie funkcji `main()` z własnego skryptu
zapewnia tylko kontrole między etapami, bez zewnętrznego nadzorcy.
Starsze polecenie `python -m representative_clients` nie jest tym trybem.

W konsoli ustawienia odpowiadają `--total-time-limit 86400 --time-limit 1800`.
Pierwszy parametr można zmniejszyć, np. `43200` dla 12 godzin; wartości większe
niż 86400 są odrzucane. Solver może zakończyć wcześniej, gdy osiągnie tolerancję
luki MIP (domyślnie 10%). Skrócenie czasu zwiększa ryzyko dużej luki lub braku
rozwiązania dopuszczalnego.

Pierwszy tryb sprawdzania zmierzy koszt odczytu rzeczywistych plików. Krótka
próba pokaże, czy solver znajduje rozwiązania. Czasy czterech grup i całego
pierwszego OSD w logu dadzą lepszy punkt odniesienia dla pełnego przebiegu;
pozostałe OSD mogą mieć inną trudność. Próbę 60-sekundową traktuj jako kontrolę
uruchomienia, nie wiarygodny pomiar czasu potrzebnego do uzyskania docelowej jakości.

Program podaje rozmiar macierzy podczas sprawdzania. Solver potrzebuje
dodatkowej pamięci poza tą macierzą. Duże XLSX czytaj z lokalnego dysku;
na długi przebieg pozostaw komputer włączony bez uśpienia. System w uśpieniu
lub zawieszony nie może egzekwować terminowego zakończenia procesu.

## 7. Weryfikacja pakietu

Testy korzystają wyłącznie z syntetycznych danych i można uruchomić je tak:

~~~powershell
.\.venv-representative-clients\Scripts\python.exe -m unittest discover -s tests -p "test_representative*.py" -v
~~~

To potwierdza działanie kodu na przykładach testowych. Pierwszy rzeczywisty
wynik trzeba jeszcze porównać z bilansem i wcześniejszym wynikiem GAMS.
