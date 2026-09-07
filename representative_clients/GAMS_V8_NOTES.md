# Rekonstrukcja `Model_dobor_klientow_v8.gms`

Dokument opisuje logikę odczytaną ze zdjęć kodu. Służy do audytu zgodności,
nie jest oryginalnym plikiem Marka.

## Dane i parametry

- `B[i,t]`: bilans klienta, suma `p_B_Klient_part_1` i
  `p_B_Klient_part_2`;
- `A[t]`: bilans wybranego oddziału;
- `K = 50`: maksymalna liczba wybranych klientów na grupę;
- `alpha = 0.20`;
- `L = (liczba wszystkich klientów / K) / 10`;
- `U = (liczba wszystkich klientów / K) * 5`;
- `C = alpha * mean(abs(A[t]))`.

## Zmienne jednej grupy

- `x[i]` — binarna decyzja wyboru;
- `w[i] >= 0` — waga klienta;
- `e_plus[t], e_minus[t] >= 0` — dwie strony błędu;
- `v_cel` — suma błędów.

## Model

```text
min  sum_t(e_plus[t] + e_minus[t])

sum_i x[i] <= K
L*x[i] <= w[i] <= U*x[i]
-C <= w[i]*B[i,t] <= C
sum_i w[i]*B[i,t] = A[t] + e_plus[t] - e_minus[t]
```

Klient wymagany ma `x=1` i wagę ustaloną na wartość z arkusza
`Ograniczenia`. Klient wykluczony nie trafia do zbioru kandydatów.

W Pythonie ograniczenia kontrybucji są zapisane równoważnie jako:

```text
w[i] <= C / max_t(abs(B[i,t]))
```

dla profilu niezerowego. Redukuje to liczbę ograniczeń klient × godzina bez
zmiany obszaru dopuszczalnego, ponieważ `w[i]` jest nieujemne.

## Podział grup

Po usunięciu wykluczonych klientów ich kolejność z arkusza `Klienci` jest
dzielona cyklicznie:

- 1., 5., 9., ... → `w1`;
- 2., 6., 10., ... → `w2`;
- 3., 7., 11., ... → `w3`;
- 4., 8., 12., ... → `w4`.

Każda grupa osobno aproksymuje pełny bilans oddziału. Są to cztery niezależne
zestawy kandydatów, a nie klastry lokalizacyjne.

## Różnice świadome względem kodu GAMS

- Python sprawdza konflikt „wymagany i wykluczony” oraz niedopuszczalną wagę;
- Python odrzuca brak rozwiązania dopuszczalnego. Jeżeli solver zwróci
  rozwiązanie dopuszczalne, lecz nie potwierdzi optymalności (np. osiągnie limit
  czasu), wynik może zostać zapisany z pełnym statusem w arkuszu `Diagnostyka`,
  a proces kończy się kodem `2`;
- udział poboru/oddania przy zerowym mianowniku zapisuje jako brak zamiast
  wykonywać dzielenie przez zero;
- wynik nie jest domyślnie nadpisywany;
- bilanse są opcjonalnie skalowane dla stabilności numerycznej, bez zmiany
  rozwiązania matematycznego.

Raport Pythona zachowuje arkusz `Wyniki` z blokami rozpoczynającymi się w
`B3`, `G2`, `N2` i `U2`, tak jak cztery wywołania GDXXRW. Dodaje też osobne
arkusze audytowe z jawnymi nagłówkami i statusem solvera.

Zbiór okresów jest odtwarzany jako globalny iloczyn wszystkich wartości
`s_Data_Hist × s_h`, także gdy skoroszyt zawiera więcej niż jeden oddział.

## Granice odpowiedzialności danych

- Model nie weryfikuje zgód marketingowych w źródłowym systemie. Lista w
  `Ograniczenia!A:A` musi zostać wcześniej przygotowana i zaktualizowana przez
  proces danych biznesowych.
- Osiem OSD/oddziałów uruchamia się osobno i zapisuje do ośmiu jednoznacznie
  nazwanych plików wynikowych.
- Tryb `--validate-only` nie uruchamia solvera ani nie zapisuje pliku, ale czyta
  cały skoroszyt XLSX.
- Wejściowy i wynikowy skoroszyt należy zamknąć w Excelu przed uruchomieniem.
