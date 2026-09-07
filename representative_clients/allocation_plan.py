"""Stały przydział portfela, niezależny od zakresu pojedynczego uruchomienia."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .consent import BRANCH_ORDER
from .portfolio_data import allocate_branch_targets


def domain_digest(identifiers) -> str:
    return hashlib.sha256(json.dumps(sorted(identifiers), ensure_ascii=False).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: dict, *, replace: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_plan(domains: dict, total: int, sources: dict, consents: Path) -> dict:
    if set(domains) != set(BRANCH_ORDER):
        raise ValueError("Pierwszy plan wymaga list kandydatów ze wszystkich 8 OSD.")
    targets = allocate_branch_targets({key: len(ids) for key, ids in domains.items()}, total)
    plan = {
        "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "total_clients": total, "consents": str(consents.resolve()),
        "branches": {
            key: {"target": targets[key], "eligible": len(domains[key]),
                  "domain_sha256": domain_digest(domains[key]),
                  "sources": list(dict.fromkeys(str(path.resolve()) for path, _ in sources[key]))}
            for key in BRANCH_ORDER
        },
    }
    plan["plan_id"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:16]
    return plan


def load_plan(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        plan = json.load(stream)
    try:
        total = plan["total_clients"]
        branches = plan["branches"]
        if plan["version"] != 1 or type(total) is not int or not 500 <= total <= 1100:
            raise ValueError("Nieobsługiwana wersja lub liczba klientów.")
        if set(branches) != set(BRANCH_ORDER):
            raise ValueError("Plan musi zawierać wszystkie 8 oddziałów.")
        for row in branches.values():
            if type(row["target"]) is not int or type(row["eligible"]) is not int:
                raise ValueError("Niecałkowita liczba klientów.")
            if not 1 <= row["target"] <= row["eligible"] // 2:
                raise ValueError("Nieprawidłowa pojemność oddziału.")
            if len(row["domain_sha256"]) != 64 or not isinstance(row["sources"], list):
                raise ValueError("Nieprawidłowy opis źródeł.")
        if sum(row["target"] for row in branches.values()) != total:
            raise ValueError("Suma przydziałów różni się od celu portfela.")
        original_id = plan["plan_id"]
        payload = {key: value for key, value in plan.items() if key != "plan_id"}
        if original_id != hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]:
            raise ValueError("Plan został zmieniony. Utwórz nowy plan zamiast edytować przydziały ręcznie.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Nieprawidłowy plik planu podziału.") from exc
    return plan


def check_domain(plan: dict, key: str, identifiers) -> None:
    row = plan["branches"][key]
    if row["domain_sha256"] != domain_digest(identifiers):
        raise ValueError(
            f"{key}: lista dopuszczonych PPE różni się od zapisanego planu. "
            "Wskaż ten sam komplet części i zgód albo utwórz osobny nowy plan dla wszystkich OSD. "
            "Przydział istniejącego planu nie został zmieniony."
        )
