"""P4 (M0) — DocType `NPP Cong No NCC` mới dựng: chiếu một lần mọi nguồn công nợ NCC đang có trên site (Purchase Invoice đã ghi sổ, phiếu chi NCC
còn tiền) — từ nay doc_events giữ bản chiếu (nppsale.su_kien.cong_no_ncc), việc đêm khám sổ so với Payment Ledger (đặc tả kho_mua §2.8)."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "NPP Cong No NCC"):
		return
	from nppsale.su_kien.cong_no_ncc import chieu_ncc

	for ncc in sorted(set(frappe.get_all("Purchase Invoice", filters={"docstatus": 1}, pluck="supplier"))
			| set(frappe.get_all("Payment Entry", filters={"docstatus": 1, "party_type": "Supplier"}, pluck="party"))):
		if ncc:
			chieu_ncc(ncc)
