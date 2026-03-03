from __future__ import annotations

from app.models import ExpenseItem, ItemMode
from app.routers.projects import _build_preview_diff_rows, _norm_key


def _mk_item(title: str, *, mode: ItemMode, qty: float | None = None, unit: float | None = None, base: float = 0.0) -> ExpenseItem:
    return ExpenseItem(
        stable_item_id=f"item_{_norm_key(title) or 'x'}",
        project_id=1,
        group_id=1,
        parent_item_id=1,
        title=title,
        mode=mode,
        qty=qty,
        unit_price_base=unit,
        base_total=base,
        include_in_estimate=False,
        extra_profit_enabled=False,
        extra_profit_amount=0.0,
    )


def test_diff_rows_detect_new_changed_removed() -> None:
    parent = _mk_item("Блок", mode=ItemMode.SINGLE_TOTAL, base=0.0)
    old_a = _mk_item("Позиция A", mode=ItemMode.QTY_PRICE, qty=2, unit=100, base=200)
    old_b = _mk_item("Позиция B", mode=ItemMode.SINGLE_TOTAL, base=300)
    existing = {_norm_key("Блок"): (parent, [old_a, old_b])}

    parsed = [
        {
            "title": "Блок",
            "items": [
                {"title": "Позиция A", "qty": 2, "unit": 125, "amount": 250},  # changed
                {"title": "Позиция C", "qty": None, "unit": None, "amount": 80},  # new
            ],
        }
    ]

    rows = _build_preview_diff_rows(parsed, existing)
    statuses = {(r["row_title"], r["status"]) for r in rows}
    assert ("Позиция A", "changed") in statuses
    assert ("Позиция C", "new") in statuses
    assert ("Позиция B", "removed") in statuses

