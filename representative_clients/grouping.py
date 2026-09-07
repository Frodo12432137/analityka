from __future__ import annotations

from typing import Dict, Iterable, Sequence, Tuple


def round_robin_groups(
    client_ids: Sequence[str], excluded: Iterable[str], group_count: int
) -> Dict[str, Tuple[str, ...]]:
    """Odtwarza mapowanie c1->w1, ..., cn->wn z GAMS v8."""

    if group_count <= 0:
        raise ValueError("group_count musi być dodatnie.")
    excluded_set = set(excluded)
    groups = {f"w{index + 1}": [] for index in range(group_count)}
    eligible = [client_id for client_id in client_ids if client_id not in excluded_set]
    for position, client_id in enumerate(eligible):
        groups[f"w{position % group_count + 1}"].append(client_id)
    return {name: tuple(values) for name, values in groups.items()}

