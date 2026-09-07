"""Wspólny limit czasu rzeczywistego dla okna VS Code i polecenia konsolowego."""
from __future__ import annotations

import math
from datetime import datetime
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Sequence

MAX_RUN_SECONDS = 24 * 60 * 60
TIMEOUT_EXIT_CODE = 124
DEADLINE_ENV = "PGE_REPRESENTATIVE_DEADLINE"
WORKDIR_ENV = "PGE_REPRESENTATIVE_WORKING_DIRECTORY"


class RunTimeLimitError(RuntimeError):
    pass


def validate_run_seconds(seconds: Optional[float]) -> Optional[float]:
    if seconds is None:
        return None
    if not math.isfinite(seconds) or not 0 < seconds <= MAX_RUN_SECONDS:
        raise ValueError("Limit całego przebiegu musi być większy od zera i nie większy niż 86400 s (24 h).")
    return seconds


class RunBudget:
    def __init__(self, seconds: Optional[float], deadline: Optional[float] = None):
        self.seconds = validate_run_seconds(seconds)
        local_deadline = math.inf if seconds is None else time.monotonic() + seconds
        self.deadline = min(local_deadline, deadline) if deadline is not None else local_deadline

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def check(self) -> None:
        if self.remaining() <= 0:
            raise RunTimeLimitError("Osiągnięto limit czasu całego przebiegu.")

    def group_seconds(self, cap: Optional[float], remaining_groups: int) -> Optional[float]:
        # Zostaw trochę czasu na podmiany i eksport; niezależny proces nadzorczy
        # zatrzyma również etap odczytu/C/solver, który nie oddaje sterowania.
        if not math.isfinite(self.deadline):
            return cap
        available = self.remaining() - min(3600.0, (self.seconds or 36000) * 0.10)
        if available <= 0:
            raise RunTimeLimitError("Brak bezpiecznego budżetu na kolejną grupę; zakończono przed limitem globalnym.")
        share = available / max(1, remaining_groups)
        return share if cap is None else min(cap, share)


def configured_seconds(args, now: Optional[datetime] = None) -> Optional[float]:
    """Termin jest w lokalnej strefie komputera; ISO z offsetem także jest obsługiwane."""
    if args.no_time_limit:
        if args.time_limit is not None:
            raise ValueError("Tryb bez limitu nie może mieć jednocześnie limitu grupy.")
        return None
    if args.finish_by:
        try:
            finish = datetime.fromisoformat(args.finish_by)
        except ValueError as exc:
            raise ValueError("Termin wpisz jako RRRR-MM-DD GG:MM, np. 2026-09-08 08:00.") from exc
        current = now or datetime.now().astimezone()
        seconds = finish.timestamp() - current.timestamp()
        if seconds <= 0:
            raise ValueError("Termin raportu musi być w przyszłości.")
        return validate_run_seconds(seconds)
    return validate_run_seconds(args.total_time_limit)


def supervise(
    command: Sequence[str],
    seconds: Optional[float],
    on_line: Callable[[str], None],
    *,
    cwd: Optional[Path] = None,
) -> int:
    """Nadzorca pozostaje poza workerem; nie czeka na linię stdout ani na GIL workera."""
    budget = RunBudget(seconds)
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.pop(DEADLINE_ENV, None)
    if math.isfinite(budget.deadline):
        env[DEADLINE_ENV] = str(budget.deadline)
    env[WORKDIR_ENV] = str(Path.cwd())
    lines: queue.Queue = queue.Queue()
    with subprocess.Popen(
        list(command), cwd=cwd, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        start_new_session=(os.name != "nt"),
    ) as process:
        def read_output() -> None:
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        exhausted = False
        code = None
        try:
            while True:
                remaining = budget.remaining()
                if remaining <= 0:
                    # Bez okresu łaski dla obliczeń po terminie. kill działa też
                    # na Windows; nie polegamy na sygnale obsługiwanym przez Python.
                    process.kill()
                    code = TIMEOUT_EXIT_CODE
                    break
                if exhausted and process.poll() is not None:
                    code = process.returncode
                    break
                try:
                    line = lines.get(timeout=min(0.1, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    exhausted = True
                else:
                    on_line(line)
        except KeyboardInterrupt:
            process.kill()
            code = 130
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=1)
            while not lines.empty():
                line = lines.get_nowait()
                if line is not None:
                    on_line(line)
        if code == TIMEOUT_EXIT_CODE:
            on_line(
                f"STOP: limit całego przebiegu {seconds / 3600:g} h. "
                "Pełny raport może nie istnieć. Jeśli zapisano raporty OSD, pozostają "
                "w folderze *_czesci_*; nie są pełnym wynikiem portfela.\n"
            )
        return code


def run_portfolio(arguments: Optional[Sequence[str]] = None, on_line=None) -> int:
    """Publiczny punkt startowy z twardym nadzorem procesu obliczeniowego."""
    from .portfolio_cli import build_parser

    argv = list(sys.argv[1:] if arguments is None else arguments)
    parser = build_parser()
    if on_line is None:
        on_line = lambda line: print(line, end="", flush=True)
    captured = io.StringIO()
    try:
        with redirect_stdout(captured), redirect_stderr(captured):
            args = parser.parse_args(argv)
        seconds = configured_seconds(args)
    except SystemExit as exc:
        on_line(captured.getvalue())
        return int(exc.code)
    except ValueError as exc:
        on_line(f"BŁĄD: {exc}\n")
        return 2
    on_line("Limit całego przebiegu: bez limitu czasu.\n" if seconds is None else
            f"Limit całego przebiegu: {seconds / 3600:g} h; model może skończyć wcześniej.\n")
    if args.finish_by:
        on_line(f"Termin gotowego raportu: {args.finish_by} (czas komputera).\n")
    return supervise(
        [sys.executable, "-u", "-m", "representative_clients.portfolio_worker", *argv],
        seconds,
        on_line,
        cwd=Path(__file__).resolve().parent.parent,
    )
