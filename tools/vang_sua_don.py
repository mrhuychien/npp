#!/usr/bin/env python3
"""Dữ liệu vàng cho SỬA / HUỶ / XOÁ đơn — đường ghi thẳng bảng của nppsale (applyOrderEdit: xoá dòng → sửa dòng → thêm dòng → lưu
đầu đơn; màn chi tiết đơn: đổi trạng thái, ghi chú; RPC cancel_order) chạy trên CHÍNH trigger + RLS của nppsale ở Postgres tham chiếu.

Mỗi tình huống là một chuỗi lệnh, MỖI LỆNH MỘT GIAO DỊCH như một lần gọi PostgREST (ràng buộc hoãn chạy ở cuối lệnh), dưới vai
`authenticated` của đúng người; lệnh hỏng thì lui đúng lệnh ấy và dừng tình huống. Ghi lại kết quả từng lệnh (số dòng chạm tới / lỗi)
và trạng thái cuối của đơn. tests/test_sua_don.py chạy cùng chuỗi lệnh qua cổng trên site Frappe và so.

	python3 tools/vang_sua_don.py   → nppsale/tests/du_lieu/sua_don_mau.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vang_tao_don import (  # noqa: E402
	GIA,
	HANG,
	KHACH,
	NGUOI,
	NHOM,
	NS,
	PSQL,
	_lit,
	dong,
	ref,
	sql_nen,
	tong,
	uid,
)

GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICH = os.path.join(GOC, "nppsale", "tests", "du_lieu", "sua_don_mau.json")


# ---------------------------------------------------------------- dựng lệnh
def tao(nguoi, lines, ma, *, khach="@C1", giam_don=0, tru=0, **o):
	t = tong(lines, giam_don, tru)
	oo = {"order_code": "TAM-1", "customer_id": khach, "payment_terms": "COD", "expected_delivery": None, "notes": None, "status": "draft",
		"approval_reason": None, "sales_user_id": None, **t}
	oo.update(o)
	return {"buoc": "rpc", "nguoi": nguoi, "ten": "create_order_with_lines", "tham_so": {"p": {
		"client_request_id": str(uuid.uuid5(NS, "sua:" + ma)), "order": oo, "lines": lines, "returns": None, "return_lines": []}}}


def loc_dong(sp="@P1", dv="Lon"):
	return [["order_id", "eq", "@don"], ["product_id", "eq", sp], ["unit_name", "eq", dv]]


def sua_dong(nguoi, gia_tri, sp="@P1", dv="Lon"):
	return {"buoc": "ghi", "nguoi": nguoi, "bang": "sales_order_lines", "hanh_dong": "update", "gia_tri": gia_tri, "loc": loc_dong(sp, dv)}


def xoa_dong(nguoi, sp="@P1", dv="Lon"):
	return {"buoc": "ghi", "nguoi": nguoi, "bang": "sales_order_lines", "hanh_dong": "delete", "loc": loc_dong(sp, dv)}


def them_dong(nguoi, *ds):
	return {"buoc": "ghi", "nguoi": nguoi, "bang": "sales_order_lines", "hanh_dong": "insert",
		"gia_tri": [{**{k: v for k, v in d.items() if k != "line_total"}, "order_id": "@don", "line_total": d["line_total"]} for d in ds]}


def dau(nguoi, **gia_tri):
	return {"buoc": "ghi", "nguoi": nguoi, "bang": "sales_orders", "hanh_dong": "update", "gia_tri": gia_tri, "loc": [["id", "eq", "@don"]]}


def tien(lines, giam_don=0, tru=0):
	return tong(lines, giam_don, tru)


def xoa_don(nguoi):
	return {"buoc": "ghi", "nguoi": nguoi, "bang": "sales_orders", "hanh_dong": "delete", "loc": [["id", "eq", "@don"]]}


def huy(nguoi, ly_do="Khach doi y"):
	return {"buoc": "rpc", "nguoi": nguoi, "ten": "cancel_order", "tham_so": {"p_order_id": "@don", "p_reason": ly_do}}


def tinh_huong() -> list[dict]:
	A = [dong(sl=2, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]
	A3 = [dong(sl=3, gia=9500), dong(sp="@P2", dv="Chai", gia=5000, thue=0.1)]
	T = []

	def th(ma, *buoc):
		T.append({"ma": ma, "buoc": list(buoc)})

	# --- applyOrderEdit: sửa SL / giá / thêm / bớt / thay hết, rồi lưu đầu đơn
	th("sua_sl_roi_luu_dau", tao("sales_a", A, "sua_sl_roi_luu_dau"), sua_dong("sales_a", {"quantity": 3, "line_total": 28500}),
		dau("sales_a", **tien(A3), status="draft"))
	th("sua_gia_xuong_khong_quyen", tao("sales_a", A, "sua_gia_xuong_khong_quyen"), sua_dong("sales_a", {"unit_price": 9000, "line_total": 18000}))
	th("sua_gia_xuong_co_quyen", tao("sales_giam", A, "sua_gia_xuong_co_quyen"),
		sua_dong("sales_giam", {"unit_price": 9000, "line_discount": 1000, "line_total": 18000}),
		dau("sales_giam", **tien([dong(sl=2, gia=9000), A[1]])))
	th("giu_gia_cu_cao_hon_tran", tao("owner", [dong(sl=1, gia=12000)], "giu_gia_cu_cao_hon_tran", sales_user_id="@u:sales_a",
		status="submitted"), sua_dong("sales_a", {"quantity": 2, "line_total": 24000}), dau("sales_a", **tien([dong(sl=2, gia=12000)])),
		sua_dong("sales_a", {"unit_price": 12100, "line_total": 24200}))
	th("them_dong_roi_luu", tao("sales_a", A, "them_dong_roi_luu"), them_dong("sales_a", dong(sp="@P2", dv="Hop", hs=10, gia=50000, thue=0.1)),
		dau("sales_a", **tien([*A, dong(sp="@P2", dv="Hop", hs=10, gia=50000, thue=0.1)])))
	th("them_dong_duoi_gia", tao("sales_a", A, "them_dong_duoi_gia"), them_dong("sales_a", dong(sp="@P2", dv="Hop", hs=10, gia=49000, thue=0.1)))
	th("xoa_dong_roi_luu", tao("sales_a", A, "xoa_dong_roi_luu"), xoa_dong("sales_a", "@P2", "Chai"), dau("sales_a", **tien(A[:1])))
	th("thay_het_dong", tao("sales_a", A, "thay_het_dong"), xoa_dong("sales_a"), xoa_dong("sales_a", "@P2", "Chai"),
		them_dong("sales_a", dong(dv="Thung", hs=24, gia=228000, sl=1)), dau("sales_a", **tien([dong(dv="Thung", hs=24, gia=228000, sl=1)])))
	th("thay_het_dong_dung_gia", tao("sales_a", A, "thay_het_dong_dung_gia"), xoa_dong("sales_a"), xoa_dong("sales_a", "@P2", "Chai"),
		them_dong("sales_a", dong(dv="Loc", hs=6, gia=57000, sl=1)), dau("sales_a", **tien([dong(dv="Loc", hs=6, gia=57000, sl=1)])))
	th("doi_khach_va_dieu_khoan", tao("sales_a", A, "doi_khach_va_dieu_khoan"), dau("sales_a", customer_id="@C2", payment_terms="NET15",
		expected_delivery="2026-12-05", notes="Doi khach", **tien(A)))
	th("dv_rong_khi_sua", tao("sales_a", A, "dv_rong_khi_sua"), sua_dong("sales_a", {"unit_name": "", "quantity": 3, "line_total": 28500}))
	th("thue_ngoai_khoang", tao("sales_a", A, "thue_ngoai_khoang"), sua_dong("sales_a", {"vat_rate": 8}))
	th("ghi_tay_da_xuat", tao("sales_a", A, "ghi_tay_da_xuat"), sua_dong("sales_a", {"invoiced_qty": 1}))
	th("sua_dong_khong_doi_tien", tao("sales_a", A, "sua_dong_khong_doi_tien"), sua_dong("sales_a", {"note": "giao som"}),
		dau("sales_a", **tien(A)))
	# --- giảm giá cả đơn: mốc gốc chụp lúc dòng đầu tiên đổi, so khi lưu đầu đơn
	th("giam_don_tang_khong_quyen", tao("sales_a", A, "giam_don_tang_khong_quyen"), dau("sales_a", **tien(A, giam_don=1000)))
	th("giam_don_giu_nguyen_khi_sua_dong", tao("sales_giam5", [dong(sl=10, gia=9500)], "giam_don_giu", giam_don=4750),
		sua_dong("sales_giam5", {"quantity": 11, "line_total": 104500}), dau("sales_giam5", **tien([dong(sl=11, gia=9500)], giam_don=4750)))
	th("giam_don_tang_vuot_tran", tao("sales_giam5", [dong(sl=10, gia=9500)], "giam_don_tang_vuot", giam_don=4750),
		sua_dong("sales_giam5", {"quantity": 11, "line_total": 104500}), dau("sales_giam5", **tien([dong(sl=11, gia=9500)], giam_don=5300)))
	th("giam_don_tang_trong_tran", tao("sales_giam5", [dong(sl=10, gia=9500)], "giam_don_tang_trong", giam_don=4750),
		sua_dong("sales_giam5", {"quantity": 11, "line_total": 104500}), dau("sales_giam5", **tien([dong(sl=11, gia=9500)], giam_don=5226)))
	th("giam_don_moc_qua_lan_hong", tao("sales_giam", [dong(sl=2, gia=9500)], "giam_don_moc", giam_don=1000),
		sua_dong("sales_giam", {"quantity": 3, "line_total": 28500}), dau("sales_a", **tien([dong(sl=3, gia=9500)], giam_don=1000)),
		dau("sales_giam", **tien([dong(sl=3, gia=9500)], giam_don=1500)))
	th("chu_giam_don_tuy_y", tao("sales_a", A, "chu_giam_don_tuy_y", status="submitted"), dau("owner", **tien(A, giam_don=20000)))
	th("tru_hang_tra_khi_luu", tao("sales_a", A, "tru_hang_tra_khi_luu"), dau("sales_a", **tien(A, tru=3000)))
	# --- trạng thái
	th("nhap_sang_gui", tao("sales_a", A, "nhap_sang_gui"), dau("sales_a", status="submitted"))
	th("gui_ve_nhap", tao("sales_a", A, "gui_ve_nhap", status="submitted"), dau("sales_a", status="draft"))
	th("nhap_sang_hoan_thanh", tao("owner", A, "nhap_sang_hoan_thanh"), dau("owner", status="completed"))
	th("gui_sang_hoan_thanh", tao("owner", A, "gui_sang_hoan_thanh", status="submitted"), dau("owner", status="completed"))
	th("trang_thai_la", tao("owner", A, "trang_thai_la"), dau("owner", status="approved"))
	th("huy_bang_cap_nhat", tao("sales_a", A, "huy_bang_cap_nhat", status="submitted"), dau("sales_a", status="cancelled"),
		dau("sales_a", status="draft"))
	th("huy_qua_rpc", tao("sales_a", A, "huy_qua_rpc", status="submitted"), huy("sales_a"), them_dong("sales_a", dong(gia=9500)))
	th("huy_qua_rpc_hai_lan", tao("sales_a", A, "huy_qua_rpc_hai_lan"), huy("sales_a"), huy("sales_a", "lan 2"))
	th("chu_huy_don_nv", tao("sales_a", A, "chu_huy_don_nv", status="submitted"), huy("owner", "NPP huy"))
	th("nv_khac_huy", tao("sales_a", A, "nv_khac_huy", status="submitted"), huy("sales_b"))
	th("ke_toan_huy", tao("sales_a", A, "ke_toan_huy", status="submitted"), huy("accountant"))
	th("sua_dong_don_da_huy", tao("sales_a", A, "sua_dong_don_da_huy", status="submitted"), huy("sales_a"),
		sua_dong("owner", {"quantity": 5, "line_total": 47500}))
	th("xoa_dong_don_da_huy", tao("sales_a", A, "xoa_dong_don_da_huy", status="submitted"), huy("sales_a"), xoa_dong("owner"))
	# --- quyền theo người
	th("nv_khac_sua_dau", tao("sales_a", A, "nv_khac_sua_dau", status="submitted"), dau("sales_b", notes="sua tram"))
	th("nv_khac_sua_dong", tao("sales_a", A, "nv_khac_sua_dong", status="submitted"), sua_dong("sales_b", {"quantity": 9, "line_total": 85500}))
	th("chu_sua_nhap_nguoi_khac", tao("sales_a", A, "chu_sua_nhap_nguoi_khac"), dau("owner", notes="chu sua"),
		sua_dong("owner", {"quantity": 9, "line_total": 85500}))
	th("chu_sua_don_gui", tao("sales_a", A, "chu_sua_don_gui", status="submitted"), sua_dong("owner", {"quantity": 4, "line_total": 38000}),
		dau("owner", **tien([dong(sl=4, gia=9500), A[1]])))
	th("kho_sua_don_gui", tao("sales_a", A, "kho_sua_don_gui", status="submitted"), dau("warehouse", notes="kho ghi"))
	th("chu_doi_nguoi_dung_ten", tao("sales_a", A, "chu_doi_nguoi_dung_ten", status="submitted"), dau("owner", sales_user_id="@u:sales_b"))
	th("nv_doi_nguoi_dung_ten", tao("sales_a", A, "nv_doi_nguoi_dung_ten", status="submitted"), dau("sales_a", sales_user_id="@u:sales_b"))
	th("chu_dung_ten_kho", tao("sales_a", A, "chu_dung_ten_kho", status="submitted"), dau("owner", sales_user_id="@u:warehouse"))
	# --- ghi chú / đếm lần sửa
	th("ghi_chu_hai_lan", tao("sales_a", A, "ghi_chu_hai_lan"), dau("sales_a", notes="lan 1"), dau("sales_a", notes="lan 2"))
	th("luu_khong_doi_gi", tao("sales_a", A, "luu_khong_doi_gi"), dau("sales_a", **tien(A), notes=None, status="draft"))
	# --- xoá đơn
	th("nv_xoa_nhap", tao("sales_a", A, "nv_xoa_nhap"), xoa_don("sales_a"))
	th("nv_xoa_don_gui", tao("sales_a", A, "nv_xoa_don_gui", status="submitted"), xoa_don("sales_a"))
	th("chu_xoa_don_gui", tao("sales_a", A, "chu_xoa_don_gui", status="submitted"), xoa_don("owner"))
	th("chu_xoa_don_huy", tao("sales_a", A, "chu_xoa_don_huy", status="submitted"), huy("sales_a"), xoa_don("owner"))
	th("nv_xoa_don_huy", tao("sales_a", A, "nv_xoa_don_huy", status="submitted"), huy("sales_a"), xoa_don("sales_a"))
	return T


# ---------------------------------------------------------------- chạy trên Postgres tham chiếu
def _gia(v) -> str:
	if v is None:
		return "NULL"
	if isinstance(v, bool):
		return "true" if v else "false"
	if isinstance(v, (int, float)):
		return repr(v)
	return _lit(str(v))


def sql_lenh(b: dict, i: int) -> str:
	"""Một lệnh → câu SQL (như PostgREST dựng) + đếm dòng chạm tới vào v_n."""
	b = ref(b)
	if b["buoc"] == "rpc":
		if b["ten"] == "create_order_with_lines":
			return (f"SELECT r.order_id INTO v_don FROM public.create_order_with_lines({_lit(json.dumps(b['tham_so']['p']))}::jsonb) r; "
				"v_n := 1;")
		ts = ", ".join(f"{k} => {_gia(v)}" if k != "p_order_id" else f"{k} => v_don" for k, v in b["tham_so"].items())
		return f"PERFORM public.{b['ten']}({ts}); v_n := 1;"
	bang = b["bang"]

	def dk():
		ds = []
		for cot, op, gt in b.get("loc") or []:
			gt = "v_don" if gt == ref("@don") else _gia(gt)
			ds.append(f"{cot} = {gt}" if op == "eq" else f"{cot} IN ({gt})")
		return " AND ".join(ds) or "true"

	if b["hanh_dong"] == "update":
		gan = ", ".join(f"{k} = {_gia(v)}" for k, v in b["gia_tri"].items())
		return f"WITH x AS (UPDATE public.{bang} SET {gan} WHERE {dk()} RETURNING 1) SELECT count(*) INTO v_n FROM x;"
	if b["hanh_dong"] == "delete":
		return f"WITH x AS (DELETE FROM public.{bang} WHERE {dk()} RETURNING 1) SELECT count(*) INTO v_n FROM x;"
	ds = b["gia_tri"]
	cot = list(dict.fromkeys(k for d in ds for k in d))
	j = json.dumps([{k: d.get(k) for k in cot} for d in ds])
	sel = ", ".join(cot)
	return (f"WITH x AS (INSERT INTO public.{bang} ({sel}) SELECT {sel} FROM jsonb_populate_recordset(NULL::public.{bang}, "
		f"replace({_lit(j)}, {_lit(ref('@don'))}, v_don::text)::jsonb) RETURNING 1) SELECT count(*) INTO v_n FROM x;")


def sql_tinh_huong(t: dict) -> str:
	khoi = []
	for i, b in enumerate(t["buoc"]):
		u = uid("u:" + b["nguoi"])
		khoi.append(f"""
  IF NOT v_dung THEN
    BEGIN
      EXECUTE 'SET CONSTRAINTS ALL DEFERRED';  -- mỗi lệnh = một giao dịch mới: ràng buộc hoãn về mặc định
      PERFORM set_config('request.jwt.claim.sub', {_lit(u)}, true);
      EXECUTE 'SET LOCAL ROLE authenticated';
      {sql_lenh(b, i)}
      EXECUTE 'SET CONSTRAINTS ALL IMMEDIATE';
      EXECUTE 'RESET ROLE';
      v_kq := v_kq || jsonb_build_object('ok', true, 'so_dong', v_n);
    EXCEPTION WHEN OTHERS THEN
      v_kq := v_kq || jsonb_build_object('ok', false, 'ma_loi', SQLSTATE, 'loi', SQLERRM);
      v_dung := true;
    END;
    EXECUTE 'RESET ROLE';
    EXECUTE 'SET CONSTRAINTS ALL DEFERRED';
  END IF;""")
	return f"""
DO $c$
DECLARE
  v_don uuid; v_n int; v_kq jsonb := '[]'::jsonb; v_dung boolean := false; v_ct jsonb;
BEGIN
  BEGIN
    {''.join(khoi)}
    SELECT jsonb_build_object(
      'con', true, 'status', so.status, 'sales_user', (SELECT u.full_name FROM users u WHERE u.id = so.sales_user_id),
      'khach', (SELECT c.store_name FROM customers c WHERE c.id = so.customer_id),
      'payment_terms', so.payment_terms, 'expected_delivery', so.expected_delivery, 'notes', so.notes, 'approval_reason', so.approval_reason,
      'subtotal', so.subtotal, 'vat', so.vat, 'total', so.total, 'edit_no', so.edit_no, 'cancel_reason', so.cancel_reason,
      'cancelled_by', (SELECT u.full_name FROM users u WHERE u.id = so.cancelled_by), 'co_cancelled_at', so.cancelled_at IS NOT NULL,
      'giam_don', public._giam_don_hien_tai(so.id), 'co_moc_giam', EXISTS (SELECT 1 FROM giam_don_goc g WHERE g.order_id = so.id),
      'lich_su', (SELECT jsonb_agg(jsonb_build_array(h.from_status, h.to_status) ORDER BY h.changed_at, h.ctid) FROM order_status_history h
        WHERE h.order_id = so.id),
      'thong_bao', (SELECT count(*) FROM notifications n WHERE n.type = 'order_cancelled' AND n.link_url = '/orders/' || so.id::text),
      'dong', (SELECT jsonb_agg(jsonb_build_object('sp', (SELECT p.sku FROM products p WHERE p.id = l.product_id), 'dv', l.unit_name,
        'sl', l.quantity, 'gia', l.unit_price, 'giam', l.line_discount, 'hs', l.conversion_factor, 'thue', l.vat_rate, 'ghi_chu', l.note)
        ORDER BY (SELECT p.sku FROM products p WHERE p.id = l.product_id), l.unit_name) FROM sales_order_lines l WHERE l.order_id = so.id))
      INTO v_ct FROM sales_orders so WHERE so.id = v_don;
    IF v_ct IS NULL AND v_don IS NOT NULL THEN v_ct := jsonb_build_object('con', false); END IF;
    RAISE EXCEPTION USING ERRCODE = 'ZZ999';
  EXCEPTION WHEN SQLSTATE 'ZZ999' THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  INSERT INTO _vang_kq VALUES ({_lit(t['ma'])}, v_kq, v_ct);
END $c$;
"""


def main():
	T = tinh_huong()
	sql = ["BEGIN;", sql_nen(), "CREATE TEMP TABLE _vang_kq (ma text, buoc jsonb, ct jsonb);",
		"GRANT ALL ON _vang_kq TO authenticated;"]
	sql += [sql_tinh_huong(t) for t in T]
	sql.append("SELECT json_agg(json_build_object('ma', ma, 'buoc', buoc, 'ct', ct)) FROM _vang_kq;")
	sql.append("ROLLBACK;")
	ra = subprocess.run(PSQL, shell=True, input="\n".join(sql), capture_output=True, text=True, check=False)
	if ra.returncode != 0:
		raise SystemExit(ra.stderr[-4000:])
	kq = {k["ma"]: k for k in json.loads(ra.stdout.strip().splitlines()[-1])}
	tep = {"ghi_chu": "Sinh bởi tools/vang_sua_don.py — chuỗi lệnh sửa / huỷ / xoá đơn trên trigger + RLS thật của nppsale.",
		"nen": {"nguoi": NGUOI, "nhom": NHOM, "khach": KHACH, "hang": HANG, "gia": GIA},
		"tinh_huong": [dict(t, mong={"buoc": kq[t["ma"]]["buoc"], "ct": kq[t["ma"]]["ct"]}) for t in T]}
	with open(DICH, "w", encoding="utf-8") as f:
		json.dump(tep, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{len(T)} tình huống → {DICH}")
	for t in T:
		k = kq[t["ma"]]
		bs = " | ".join(("ok" + (f"({x['so_dong']})" if x["so_dong"] != 1 else "")) if x["ok"] else f"{x['ma_loi']} {x['loi'][:70]}"
			for x in k["buoc"])
		ct = k["ct"] or {}
		print(f"  {t['ma']:<34} {bs}  → {ct.get('status')} e{ct.get('edit_no')} {'' if ct.get('con', True) else 'ĐÃ XOÁ'}")


if __name__ == "__main__":
	main()
