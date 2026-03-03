from __future__ import annotations

from app.routers.estimate import _parse_group_ids


def test_parse_group_ids_filters_invalid_tokens() -> None:
    assert _parse_group_ids("1,2, 3, x, -1, 0, 2") == {1, 2, 3}


def test_parse_group_ids_tolerates_non_string_input() -> None:
    class Dummy:
        def __str__(self) -> str:  # pragma: no cover - tiny helper for explicit non-string path
            return "4, 5, bad"

    assert _parse_group_ids(Dummy()) == {4, 5}

