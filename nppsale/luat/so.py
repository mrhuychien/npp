"""Số của báo cáo / RPC đọc — luật thuần (đặc tả báo cáo P6 L12, §2.13; dời từ `rpc/cong_no_doc.py` để mọi RPC báo cáo dùng chung MỘT luật).

- `numeric` của Postgres ra JSON: số nguyên không phần lẻ (`ra`) — không để `Decimal` lọt ra (portal/rest.py in `Decimal` thành CHUỖI).
- `frappe.db.sql` đổi DECIMAL → float (CONVERSION_MAP NEWDECIMAL) ⇒ cộng tiếp ở Python bằng `Decimal(str(x))` (`d`).
- ROUND của Postgres trên numeric là NỬA XA SỐ 0 (`ROUND(2.5) = 3`, `ROUND(-2.5) = -3`; MariaDB DECIMAL cũng vậy) → `Decimal.quantize(…, ROUND_HALF_UP)`
  (`tron`), không `round()` của Python (nửa về số chẵn).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def d(v) -> Decimal:
	"""Giá trị số của sổ (float / Decimal / int / chuỗi số) → Decimal chính xác; None → 0 (COALESCE(x, 0) của câu SUM)."""
	return Decimal(str(v)) if v is not None else Decimal(0)


def ra(x: Decimal):
	"""numeric của Postgres ra JSON: số nguyên không phần lẻ (`int`), lẻ → `float`."""
	return int(x) if x == x.to_integral_value() else float(x)


def tron(x: Decimal, so_le: int = 0):
	"""ROUND(x, so_le) của Postgres — nửa xa số 0. so_le = 0 → int."""
	q = x.quantize(Decimal(1).scaleb(-so_le), rounding=ROUND_HALF_UP)
	return int(q) if so_le == 0 else q
