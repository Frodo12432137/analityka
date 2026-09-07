from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Tuple


BRANCH_ORDER = (
    "bialystok",
    "lublin",
    "lodz_miasto",
    "lodz_teren",
    "rzeszow",
    "skarzysko_kamienna",
    "warszawa",
    "zamosc",
)

BRANCH_LABELS = {
    "bialystok": "Białystok",
    "lublin": "Lublin",
    "lodz_miasto": "Łódź Miasto",
    "lodz_teren": "Łódź Teren",
    "rzeszow": "Rzeszów",
    "skarzysko_kamienna": "Skarżysko-Kamienna",
    "warszawa": "Warszawa",
    "zamosc": "Zamość",
}


def _plain(value: object) -> str:
    text = str(value or "").translate(str.maketrans({"ł": "l", "Ł": "L"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def canonical_branch(value: object) -> str:
    """Mapuje nazwy techniczne i opisowe OSD na osiem stałych kluczy."""

    text = _plain(value)
    compact = text.replace(" ", "")
    rules = (
        ("skarzysko_kamienna", ("skarzysko", "kamienna")),
        ("lodz_miasto", ("lodz", "miasto")),
        ("lodz_teren", ("lodz", "teren")),
        ("bialystok", ("bialystok",)),
        ("lublin", ("lublin",)),
        ("rzeszow", ("rzeszow",)),
        ("warszawa", ("warszawa",)),
        ("zamosc", ("zamosc",)),
    )
    for key, words in rules:
        if all(word in compact for word in words):
            return key
    raise ValueError(f"Nie rozpoznano OSD z wartości {value!r}.")


def technical_branch(key: str) -> str:
    mapping = {
        "bialystok": "PGED_Bialystok",
        "lublin": "PGED_Lublin",
        "lodz_miasto": "PGED_Lodz_Miasto",
        "lodz_teren": "PGED_Lodz_Teren",
        "rzeszow": "PGED_Rzeszow",
        "skarzysko_kamienna": "PGED_Skarzysko_Kamienna",
        "warszawa": "PGED_Warszawa",
        "zamosc": "PGED_Zamosc",
    }
    return mapping[key]


@dataclass(frozen=True)
class ConsentIndex:
    by_branch: Mapping[str, frozenset[str]]
    source_rows: int
    duplicate_rows: int

    @property
    def unique_count(self) -> int:
        return sum(len(values) for values in self.by_branch.values())


def _header_positions(rows: Iterable[Tuple[object, ...]]) -> Tuple[int, int, int]:
    code_names = {"kod pp aktualny", "kod pp"}
    branch_names = {"osd nazwa pp aktualny", "osd nazwa", "osd"}
    for row_number, row in enumerate(rows, start=1):
        normalized = [_plain(value) for value in row]
        code_column = next(
            (index for index, value in enumerate(normalized) if value in code_names),
            None,
        )
        branch_column = next(
            (index for index, value in enumerate(normalized) if value in branch_names),
            None,
        )
        if code_column is not None and branch_column is not None:
            return row_number, code_column, branch_column
        if row_number >= 30:
            break
    raise ValueError(
        "Nie znaleziono nagłówków 'Kod PP Aktualny' i "
        "'OSD Nazwa - PP Aktualny' w pierwszych 30 wierszach pliku zgód."
    )


def load_consent_workbook(path: str | Path) -> ConsentIndex:
    """Czyta skoroszyt zawierający wyłącznie aktualne zgody marketingowe."""

    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Do odczytu zgód wymagany jest openpyxl.") from exc

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        selected = None
        positions = None
        for sheet in workbook.worksheets:
            try:
                positions = _header_positions(sheet.iter_rows(values_only=True))
            except ValueError:
                continue
            selected = sheet
            break
        if selected is None or positions is None:
            raise ValueError(
                "Żaden arkusz pliku zgód nie zawiera wymaganych nagłówków."
            )
        header_row, code_column, branch_column = positions
        by_branch: Dict[str, set[str]] = {key: set() for key in BRANCH_ORDER}
        owner: Dict[str, str] = {}
        source_rows = 0
        duplicates = 0
        maximum_column = max(code_column, branch_column) + 1
        for row_number, row in enumerate(
            selected.iter_rows(
                min_row=header_row + 1,
                max_col=maximum_column,
                values_only=True,
            ),
            start=header_row + 1,
        ):
            raw_code = row[code_column]
            raw_branch = row[branch_column]
            if raw_code in (None, "") and raw_branch in (None, ""):
                continue
            source_rows += 1
            if not isinstance(raw_code, str) or not raw_code.strip():
                raise ValueError(
                    f"{selected.title}!{row_number}: Kod PP Aktualny musi być "
                    "niepustym tekstem (nie liczbą Excela)."
                )
            code = raw_code.strip()
            branch = canonical_branch(raw_branch)
            previous = owner.get(code)
            if previous is not None:
                if previous != branch:
                    raise ValueError(
                        f"PPE {code!r} występuje w pliku zgód przy dwóch OSD."
                    )
                duplicates += 1
                continue
            owner[code] = branch
            by_branch[branch].add(code)
    finally:
        workbook.close()
    if not owner:
        raise ValueError("Plik zgód nie zawiera żadnego PPE.")
    return ConsentIndex(
        by_branch={key: frozenset(values) for key, values in by_branch.items()},
        source_rows=source_rows,
        duplicate_rows=duplicates,
    )
