"""Hợp đồng lỗi của app: method / RPC ném NppLoi(ma) → trình duyệt nhận {code, message} như PostgREST trả lỗi RAISE của
Postgres (code P0001, message = mã nppsale) để explainInvoiceError, errorMessage, kiemLaiSauLoiXuat của nppsale chạy nguyên."""
from __future__ import annotations


class NppLoi(Exception):
	def __init__(self, ma: str, chi_tiet: str | None = None, code: str = "P0001", http: int = 400, goi_y: str | None = None):
		super().__init__(ma)
		self.ma, self.chi_tiet, self.code, self.http, self.goi_y = ma, chi_tiet, code, http, goi_y

	def to_dict(self):
		return {"message": self.ma, "code": self.code, "details": self.chi_tiet, "hint": self.goi_y}
