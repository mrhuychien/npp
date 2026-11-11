#!/usr/bin/env python3
"""Sinh DocType JSON của app từ bảng trường trong blueprint (docs/chuyen-doi/blueprint/02_doctype_blueprint.md).

Mỗi khối "### DocType: NPP Ten (npp_ten)" gồm các dòng đầu (- **Module**: … · **Naming**: … · **Is Single**: …) và bảng
"#### Fields" (| Fieldname | Label | Type | Options | Reqd | InList | InStandard | Notes |). Công cụ đọc bảng, dựng JSON đúng khuôn
Frappe v16 và ghi vào nppsale/<module>/doctype/<ten>/ (kèm __init__.py, controller rỗng nếu chưa có — controller có sẵn KHÔNG bị
đè). Cờ trong cột Notes (default, read_only, unique, set_only_once, search_index, no_copy, hidden, depends_on, precision, length,
permlevel của Section Break) được nhận theo từ khoá — in bảng tóm tắt để soát tay trước khi migrate.

	python3 tools/dung_doctype.py <blueprint.md> [--ghi] [--chi "NPP Nhan Vien,NPP Cai Dat"] [--goc nppsale]
Không --ghi: chỉ in tóm tắt (chạy thử).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

KIEU = {
	"Data", "Link", "Dynamic Link", "Select", "Check", "Int", "Float", "Currency", "Percent", "Date", "Datetime", "Time",
	"Small Text", "Text", "Long Text", "Text Editor", "Markdown Editor", "HTML Editor", "Code", "JSON", "Table",
	"Table MultiSelect", "Password", "Section Break", "Column Break", "Tab Break", "Attach", "Attach Image", "Geolocation",
	"Duration", "Read Only", "HTML", "Phone", "Rating", "Color", "Barcode", "Signature", "Autocomplete", "Icon", "Image",
	"Button", "Heading",
}
KIEU_SO = {"Int", "Float", "Currency", "Percent", "Check", "Rating", "Duration"}
KIEU_BO_CUC = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}
NGAY = "2026-11-11 00:00:00.000000"
CO = ("read_only", "unique", "set_only_once", "search_index", "no_copy", "hidden", "bold", "allow_on_submit", "print_hide",
	"in_global_search", "ignore_user_permissions", "translatable")


def ten_thu_muc(ten: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", ten.lower()).strip("_")


def bo_dau_ma(s: str) -> str:
	return s.strip().strip("`").strip()


def doc_khoi(md: str) -> list[dict]:
	"""Tách các khối DocType: tên, tên thư mục, dòng đầu (chuỗi), các dòng bảng Fields."""
	khoi = []
	dong = md.splitlines()
	i = 0
	while i < len(dong):
		m = re.match(r"^###\s+DocType:\s*(.+?)\s*\(([a-z0-9_]+)\)\s*$", dong[i])
		if not m:
			i += 1
			continue
		k = {"ten": m.group(1).strip(), "thu_muc": m.group(2), "dau": [], "bang": []}
		i += 1
		while i < len(dong) and not dong[i].startswith("#### Fields") and not dong[i].startswith("### "):
			if dong[i].strip():
				k["dau"].append(dong[i])
			i += 1
		if i < len(dong) and dong[i].startswith("#### Fields"):
			i += 1
			while i < len(dong) and not dong[i].startswith("|"):
				i += 1
			while i < len(dong) and dong[i].startswith("|"):
				k["bang"].append(dong[i])
				i += 1
		khoi.append(k)
	return khoi


def _o(dong: str) -> list[str]:
	"""Tách ô của một dòng bảng markdown (giữ `|` nằm trong dấu ` `)."""
	o, cur, ma = [], [], False
	for ch in dong.strip().strip("|"):
		if ch == "`":
			ma = not ma
		if ch == "|" and not ma:
			o.append("".join(cur).strip())
			cur = []
			continue
		cur.append(ch)
	o.append("".join(cur).strip())
	return o


def doc_dau(dau: list[str]) -> dict:
	s = " ".join(dau)

	def lay(nhan):
		m = re.search(r"\*\*" + re.escape(nhan) + r"\*\*:\s*(.+?)(?=\s*·\s*\*\*|\s*-\s*\*\*|$)", s)
		return m.group(1).strip() if m else ""

	return {
		"module": re.sub(r"\s*\(.*$", "", lay("Module")).strip(),
		"naming": lay("Naming"),
		"submit": lay("Is Submittable"),
		"single": lay("Is Single"),
		"child": lay("Is Child Table"),
		"single_child": lay("Is Single / Is Child Table"),
		"track": lay("Track Changes"),
		"title": lay("Title Field"),
		"search": lay("Search Fields"),
	}


def co_khong(s: str) -> bool:
	s = (s or "").replace("*", "").strip().lower()
	return s.startswith("yes") or s.startswith("có") or s.startswith("✓")


def dat_ten(nm: str, ten_dt: str) -> dict:
	"""Chuỗi Naming của blueprint → autoname + naming_rule."""
	n = nm.strip()
	low = n.lower()
	ma = re.findall(r"`([^`]+)`", n)
	if low.startswith("single") or "is single" in low:
		return {}
	for x in ma:
		if re.fullmatch(r"(autoname:\s*)?uuid", x.strip().lower()):
			return {"autoname": "UUID", "naming_rule": "UUID"}
	for x in ma:
		if x.startswith("field:"):
			return {"autoname": x, "naming_rule": "By fieldname"}
		if x.startswith("format:"):
			return {"autoname": x, "naming_rule": "Expression"}
		if x.startswith("naming_series:"):
			return {"autoname": "naming_series:", "naming_rule": 'By "Naming Series" field'}
		if re.match(r"^[A-Z0-9]+-\.?#+", x) or ".#" in x:
			return {"autoname": x, "naming_rule": "Expression (old style)"}
	if low.startswith("uuid") or low.startswith("autoname: uuid"):
		return {"autoname": "UUID", "naming_rule": "UUID"}
	if "autoincrement" in low.split(" ")[0]:
		return {"autoname": "autoincrement", "naming_rule": "Autoincrement"}
	if low.startswith("hash") or "hash" in low.split()[0:2]:
		return {"autoname": "hash", "naming_rule": "Random"}
	if "set by user" in low or "prompt" in low:
		return {"autoname": "prompt", "naming_rule": "Set by user"}
	return {"autoname": "hash", "naming_rule": "Random"}


def doc_truong(bang: list[str], ten_dt: str) -> tuple[list[dict], list[str]]:
	if len(bang) < 3:
		return [], [f"{ten_dt}: không có bảng trường"]
	tieu_de = [c.lower() for c in _o(bang[0])]
	vi = {t: i for i, t in enumerate(tieu_de)}
	canh_bao = []

	def o(cot, ten):
		i = vi.get(ten)
		return cot[i] if i is not None and i < len(cot) else ""

	ra = []
	permlevel_khoi = 0
	for dong in bang[2:]:
		cot = _o(dong)
		fn = bo_dau_ma(o(cot, "fieldname"))
		if not fn or fn.startswith("~"):
			continue
		kieu = o(cot, "type").strip()
		if kieu not in KIEU:
			canh_bao.append(f"{ten_dt}.{fn}: kiểu lạ {kieu!r}")
			continue
		f = {"fieldname": fn, "fieldtype": kieu}
		nhan = o(cot, "label").strip()
		if nhan:
			f["label"] = nhan
		tuy = o(cot, "options").strip()
		ghi = o(cot, "notes")
		m_len = re.search(r"\blength\s+(\d+)", tuy + " " + ghi)
		if m_len:
			f["length"] = int(m_len.group(1))
			tuy = re.sub(r"\blength\s+\d+", "", tuy).strip()
		if kieu == "Select":
			ds = [bo_dau_ma(x) for x in re.split(r"<br\s*/?>|\n|↵", tuy)]
			if tuy.startswith("<br") or tuy.startswith("↵"):
				ds = [""] + [x for x in ds if x]
			else:
				ds = [x for x in ds if x != ""]
			f["options"] = "\n".join(ds)
		elif tuy and kieu in ("Link", "Table", "Table MultiSelect", "Data", "Dynamic Link", "Code"):
			f["options"] = bo_dau_ma(tuy)
		if "✓" in o(cot, "reqd"):
			f["reqd"] = 1
		if "✓" in o(cot, "inlist"):
			f["in_list_view"] = 1
		if "✓" in o(cot, "instandard"):
			f["in_standard_filter"] = 1
		# Cờ trong Notes: chỉ nhận từ khoá đứng riêng, không đi sau "không"/"bỏ"
		for c in CO:
			if re.search(r"(?<![\w.])" + c + r"(?![\w])", ghi) and not re.search(r"(không|bỏ|chưa)\s+" + c, ghi):
				if c == "unique" and re.search(r"unique\s+(của|ở|trên)", ghi):
					continue
				f[c] = 1
		m_def = re.search(r"\bdefault\s+(hôm nay|bây giờ|`[^`]*`|[^\s,;)]+)", ghi)
		if m_def:
			d = bo_dau_ma(m_def.group(1))
			if not m_def.group(1).startswith("`"):
				d = d.rstrip(".")
			d = {"hôm nay": "today", "bây giờ": "now"}.get(d.lower(), d)
			if kieu in KIEU_SO:
				d2 = d.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", d) else d
				if re.fullmatch(r"-?\d+(\.\d+)?", d2):
					f["default"] = d2
				else:
					canh_bao.append(f"{ten_dt}.{fn}: default số lạ {d!r}")
			elif kieu in ("Datetime", "Date") and d.lower() in ("now", "now()", "today"):
				f["default"] = "Now" if kieu == "Datetime" else "Today"
			elif kieu == "Select" and d not in f.get("options", "").split("\n"):
				canh_bao.append(f"{ten_dt}.{fn}: default {d!r} không nằm trong lựa chọn")
			else:
				f["default"] = d
		m_dep = re.search(r"depends_on\s+`([^`]+)`", ghi)
		if m_dep:
			e = m_dep.group(1).strip()
			f["depends_on"] = e if e.startswith("eval:") or not re.fullmatch(r"[a-z_][a-z0-9_]*", e) else f"eval:doc.{e}"
		m_pre = re.search(r"\bprecision\s+(\d)", ghi)
		if m_pre and kieu in ("Float", "Currency", "Percent"):
			f["precision"] = m_pre.group(1)
		if kieu == "Section Break":
			m_pl = re.search(r"permlevel\s+(\d)", ghi)
			permlevel_khoi = int(m_pl.group(1)) if m_pl else 0
		elif kieu == "Tab Break":
			permlevel_khoi = 0
		elif permlevel_khoi:
			f["permlevel"] = permlevel_khoi
		m_pl_rieng = re.search(r"(?<![\w])permlevel\s+(\d)(?!\s+cả)", ghi)
		if m_pl_rieng and kieu not in KIEU_BO_CUC:
			f["permlevel"] = int(m_pl_rieng.group(1))
		if f.get("unique") and kieu in ("Small Text", "Text", "Long Text", "JSON", "Code", "Table"):
			canh_bao.append(f"{ten_dt}.{fn}: unique trên {kieu} — bỏ cờ")
			f.pop("unique")
		ra.append(f)
	ten = [f["fieldname"] for f in ra]
	for t in set(ten):
		if ten.count(t) > 1:
			canh_bao.append(f"{ten_dt}: trùng fieldname {t}")
	for f in ra:
		if f["fieldtype"] in ("Link", "Table", "Table MultiSelect") and not f.get("options"):
			canh_bao.append(f"{ten_dt}.{f['fieldname']}: {f['fieldtype']} thiếu options")
	return ra, canh_bao


def dung(k: dict) -> tuple[dict, list[str]]:
	d = doc_dau(k["dau"])
	ten = k["ten"]
	truong, canh_bao = doc_truong(k["bang"], ten)
	if d["single_child"]:
		phan = [x.replace("*", "").strip() for x in d["single_child"].split("/")]
		la_single = co_khong(phan[0])
		la_con = len(phan) > 1 and co_khong(phan[1])
	else:
		la_single = co_khong(d["single"]) or d["naming"].lower().startswith("single")
		la_con = co_khong(d["child"])
	j = {
		"actions": [],
		"creation": NGAY,
		"doctype": "DocType",
		"engine": "InnoDB",
		"field_order": [f["fieldname"] for f in truong],
		"fields": truong,
		"index_web_pages_for_search": 0,
		"links": [],
		"modified": NGAY,
		"modified_by": "Administrator",
		"module": d["module"],
		"name": ten,
		"owner": "Administrator",
		"permissions": [],
		"row_format": "Dynamic",
		"sort_field": "creation",
		"sort_order": "DESC",
		"states": [],
	}
	if la_single:
		j["issingle"] = 1
	if la_con:
		j["istable"] = 1
		j["editable_grid"] = 1
	if co_khong(d["submit"]) and not la_con:
		j["is_submittable"] = 1
	if co_khong(d["track"]) and not la_con:
		j["track_changes"] = 1
	if not la_single:
		j.update(dat_ten(d["naming"], ten))
	tf = re.findall(r"`([a-z0-9_]+)`", d["title"] or "")
	if tf:
		j["title_field"] = tf[0]
		if "show_title_field_in_link" in d["title"]:
			j["show_title_field_in_link"] = 1
	sf = re.findall(r"`([^`]+)`", d["search"] or "")
	if sf:
		j["search_fields"] = sf[0].replace(" ", "")
	if not la_con:
		j["permissions"] = [{"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1,
			"role": "System Manager", "share": 1, "write": 1}]
		if la_single:
			j["permissions"][0].pop("delete")
			j["permissions"][0].pop("export")
			j["permissions"][0].pop("report")
	if not d["module"]:
		canh_bao.append(f"{ten}: thiếu Module")
	for f in truong:
		if j.get("title_field") == f["fieldname"]:
			break
	else:
		if j.get("title_field"):
			canh_bao.append(f"{ten}: title_field {j['title_field']} không có trong bảng trường")
	for s in (j.get("search_fields") or "").split(","):
		if s and s not in j["field_order"]:
			canh_bao.append(f"{ten}: search field {s} không có trong bảng trường")
	return j, canh_bao


CONTROLLER = '''# Copyright (c) 2026, Huy Chien and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class {lop}(Document):
	pass
'''


def ghi(j: dict, goc: str, thu_muc: str):
	mod = ten_thu_muc(j["module"])
	d = os.path.join(goc, mod, "doctype", thu_muc)
	os.makedirs(d, exist_ok=True)
	for p in (os.path.join(goc, mod, "__init__.py"), os.path.join(goc, mod, "doctype", "__init__.py"), os.path.join(d, "__init__.py")):
		if not os.path.exists(p):
			open(p, "w").close()
	tep = os.path.join(d, f"{thu_muc}.json")
	cu = {}
	if os.path.exists(tep):
		cu = json.load(open(tep, encoding="utf-8"))
		j["creation"] = cu.get("creation", j["creation"])
		# Quyền do tệp 03 / tay khai thì giữ, không đè bằng mặc định
		if cu.get("permissions"):
			j["permissions"] = cu["permissions"]
		for khoa in ("links", "actions"):
			if cu.get(khoa):
				j[khoa] = cu[khoa]
	with open(tep, "w", encoding="utf-8") as f:
		json.dump(j, f, ensure_ascii=False, indent=1, sort_keys=True)
		f.write("\n")
	py = os.path.join(d, f"{thu_muc}.py")
	if not os.path.exists(py):
		lop = "".join(p.capitalize() for p in thu_muc.split("_"))
		with open(py, "w", encoding="utf-8") as f:
			f.write(CONTROLLER.format(lop=lop))


def tom_tat(j: dict) -> str:
	dong = [f"== {j['name']}  [{j['module']}]  autoname={j.get('autoname', '-')}  single={j.get('issingle', 0)} child={j.get('istable', 0)} "
		f"submit={j.get('is_submittable', 0)} title={j.get('title_field', '-')} search={j.get('search_fields', '-')}"]
	for f in j["fields"]:
		co = [c for c in ("reqd", "unique", "read_only", "set_only_once", "search_index", "no_copy", "hidden", "in_list_view",
			"in_standard_filter") if f.get(c)]
		them = []
		for c in ("options", "default", "depends_on", "precision", "length", "permlevel"):
			if f.get(c) not in (None, ""):
				v = str(f[c]).replace("\n", "|")
				them.append(f"{c}={v[:60]}")
		dong.append(f"   {f['fieldname']:<26} {f['fieldtype']:<14} {' '.join(co):<40} {' '.join(them)}")
	return "\n".join(dong)


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("blueprint", nargs="+")
	ap.add_argument("--ghi", action="store_true")
	ap.add_argument("--chi", default="")
	ap.add_argument("--goc", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nppsale"))
	a = ap.parse_args()
	chi = {x.strip() for x in a.chi.split(",") if x.strip()}
	tat_ca_canh_bao = []
	so = 0
	for bp in a.blueprint:
		for k in doc_khoi(open(bp, encoding="utf-8").read()):
			if chi and k["ten"] not in chi:
				continue
			j, cb = dung(k)
			so += 1
			print(tom_tat(j))
			tat_ca_canh_bao += cb
			if a.ghi:
				ghi(j, a.goc, k["thu_muc"])
	print(f"\n{so} DocType" + (" — đã ghi" if a.ghi else " — chạy thử (chưa ghi)"))
	if tat_ca_canh_bao:
		print("CẢNH BÁO:")
		for c in tat_ca_canh_bao:
			print("  - " + c)
	return 0


if __name__ == "__main__":
	sys.exit(main())
