"""Wewnętrzny worker. Uruchamiaj portfolio_cli lub launcher, aby mieć nadzór czasu."""
import os

from .portfolio_cli import main
from .runtime import DEADLINE_ENV, WORKDIR_ENV


if __name__ == "__main__":
    deadline = os.environ.get(DEADLINE_ENV)
    if deadline is None:
        raise SystemExit("Uruchom python -m representative_clients.portfolio_cli, nie portfolio_worker.")
    # Import modułu startuje z katalogu pakietu; względne ścieżki użytkownika
    # nadal odnoszą się do katalogu, z którego wywołał polecenie.
    os.chdir(os.environ[WORKDIR_ENV])
    raise SystemExit(main(deadline=float(deadline)))
