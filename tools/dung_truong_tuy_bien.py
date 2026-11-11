#!/usr/bin/env python3
"""Sinh danh sách Custom Field (trường `npp_*` trên DocType lõi) từ các bảng "Custom Field" của blueprint 02.

Bảng có cột (tên cột không phân biệt hoa thường, thứ tự tự do): `DocType lõi` | `fieldname` | `Label` | `Type` | `Options` |
`insert_after` | `Notes` (cột `Bảng` nếu có thì bỏ qua). Dòng "dùng <trường lõi>" (fieldname `—`, không bắt đầu bằng `npp_`, hoặc Label
`(lõi)`) là cột nppsale đi thẳng vào trường có sẵn — không sinh. Cờ trong Notes đọc như tools/dung_doctype.py (cùng hàm).

Kết quả: nppsale/thiet_lap/truong_tuy_bien.json — {DocType lõi: [trường]} — `nppsale.thiet_lap.truong_tuy_bien.ap()` gọi
`create_custom_fields(..., update=True)` ở after_install / after_migrate.

	python3 tools/dung_truong_tuy_bien.py <blueprint.md> [--ghi]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dung_doctype import CO, KIEU, KIEU_SO, _o, bo_dau_ma  # noqa: E402

DICH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nppsale", "thiet_lap", "truong_tuy_bien.json")


def doc_bang(md: str) -> list[tuple[list[str], list[str]]]:
	"""Mọi bảng markdown có cột `insert_after` và `fieldname` → (tiêu đề, các dòng)."""
	ra = []
	dong = md.splitlines()
	i = 0
	while i < len(dong):
		if dong[i].startswith("|") and i + 1 < len(dong) and re.match(r"^\|\s*:?-{3,}", dong[i + 1]):
			tieu_de = [c.strip().lower() for c in _o(dong[i])]
			j = i + 2
			than = []
			while j < len(dong) and dong[j].startswith("|"):
				than.append(dong[j])
				j += 1
			if "insert_after" in tieu_de and "fieldname" in tieu_de:
				ra.append((tieu_de, than))
			i = j
			continue
		i += 1
	return ra


def truong(tieu_de, dong, canh_bao):
	vi = {t: k for k, t in enumerate(tieu_de)}
	cot = _o(dong)

	def o(ten):
		k = vi.get(ten)
		return cot[k].strip() if k is not None and k < len(cot) else ""

	dt = bo_dau_ma(o("doctype lõi"))
	fn = bo_dau_ma(o("fieldname"))
	if not fn.startswith("npp_") or "(lõi)" in o("label"):
		return None, None
	dt = re.sub(r"\s*\(.*\)$", "", dt).strip()
	kieu = o("type")
	if kieu not in KIEU:
		canh_bao.append(f"{dt}.{fn}: kiểu lạ {kieu!r}")
		return None, None
	f = {"fieldname": fn, "fieldtype": kieu, "label": o("label"), "insert_after": bo_dau_ma(o("insert_after"))}
	tuy = o("options")
	ghi = o("notes")
	m_len = re.search(r"\blength\s+(\d+)", tuy + " " + ghi)
	if m_len:
		f["length"] = int(m_len.group(1))
		tuy = re.sub(r"\blength\s+\d+", "", tuy).strip()
	m_pre = re.search(r"\bprecision\s+(\d)", tuy + " " + ghi)
	if m_pre and kieu in ("Float", "Currency", "Percent"):
		f["precision"] = m_pre.group(1)
		tuy = re.sub(r"\bprecision\s+\d", "", tuy).strip()
	m_def_o = re.search(r"\bdefault\s+(\S+)", tuy)
	if m_def_o:
		tuy = tuy[: m_def_o.start()].strip()
	if kieu == "Select":
		ds = [bo_dau_ma(x) for x in re.split(r"<br\s*/?>|\n|↵", tuy)]
		f["options"] = "\n".join(([""] if tuy.startswith(("<br", "↵")) else []) + [x for x in ds if x])
	elif tuy:
		f["options"] = bo_dau_ma(tuy)
	# Cờ: AOS / RO / idx là viết tắt của phần Bán hàng
	ghi2 = re.sub(r"\bAOS\b", "allow_on_submit", re.sub(r"\bRO\b", "read_only", re.sub(r"\bidx\b", "search_index", ghi)))
	for c in CO + ("in_list_view", "in_standard_filter"):
		if re.search(r"(?<![\w.])" + c + r"(?![\w])", ghi2) and not re.search(r"(không|bỏ|chưa)\s+" + c, ghi2):
			if c == "unique" and re.search(r"unique\s+(của|ở|trên)", ghi2):
				continue
			f[c] = 1
	if re.search(r"(?<![\w.])in_list(?![\w])", ghi2):
		f["in_list_view"] = 1
	if re.search(r"\*\*unique\*\*", ghi):
		f["unique"] = 1
	m_def = re.search(r"\bdefault\s+(hôm nay|`[^`]*`|\"[^\"]*\"|[^\s,;)]+)", (m_def_o.group(0) if m_def_o else "") + " " + ghi)
	if m_def:
		d = m_def.group(1).strip('"')
		d = bo_dau_ma(d) if d.startswith("`") else d.rstrip(".")
		if kieu in KIEU_SO:
			d2 = d.replace(".", "") if re.fullmatch(r"\d{1,3}(\.\d{3})+", d) else d
			if re.fullmatch(r"-?\d+(\.\d+)?", d2):
				f["default"] = d2
			else:
				canh_bao.append(f"{dt}.{fn}: default số lạ {d!r}")
		elif kieu == "Select" and d not in f.get("options", "").split("\n"):
			canh_bao.append(f"{dt}.{fn}: default {d!r} không nằm trong lựa chọn")
		else:
			f["default"] = d
	m_dep = re.search(r"depends_on\s+`([^`]+)`", ghi)
	if m_dep:
		e = m_dep.group(1).strip()
		f["depends_on"] = e if e.startswith("eval:") or not re.fullmatch(r"[a-z_][a-z0-9_]*", e) else f"eval:doc.{e}"
	if f.get("unique") and kieu in ("Small Text", "Text", "Long Text", "JSON", "Code", "Table"):
		f.pop("unique")
		canh_bao.append(f"{dt}.{fn}: unique trên {kieu} — bỏ cờ")
	return dt, f


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("blueprint", nargs="+")
	ap.add_argument("--ghi", action="store_true")
	ap.add_argument("--chi-dt", default="", help="chỉ các DocType lõi này (phẩy ngăn)")
	a = ap.parse_args()
	chi_dt = {x.strip() for x in a.chi_dt.split(",") if x.strip()}
	kq: dict[str, list[dict]] = {}
	canh_bao: list[str] = []
	for bp in a.blueprint:
		for tieu_de, than in doc_bang(open(bp, encoding="utf-8").read()):
			for d in than:
				dt, f = truong(tieu_de, d, canh_bao)
				if not f or (chi_dt and dt not in chi_dt):
					continue
				ds = kq.setdefault(dt, [])
				cu = next((x for x in ds if x["fieldname"] == f["fieldname"]), None)
				if cu:
					if cu != f:
						canh_bao.append(f"{dt}.{f['fieldname']}: khai hai lần khác nhau — giữ bản đầu")
					continue
				ds.append(f)
	# insert_after phải trỏ trường đã có (trường lõi kiểm khi migrate; ở đây chỉ kiểm thứ tự trong cùng bảng npp_)
	for dt, ds in kq.items():
		ten = [f["fieldname"] for f in ds]
		for f in ds:
			ia = f.get("insert_after", "")
			if ia.startswith("npp_") and ia not in ten:
				canh_bao.append(f"{dt}.{f['fieldname']}: insert_after {ia} không có trong danh sách")
		print(f"== {dt}: {len(ds)} trường")
		for f in ds:
			co = [c for c in ("reqd", "unique", "read_only", "allow_on_submit", "search_index", "no_copy", "in_list_view",
				"in_standard_filter") if f.get(c)]
			them = " ".join(f"{c}={str(f[c]).replace(chr(10), '|')[:40]}" for c in ("options", "default", "precision", "length",
				"depends_on") if f.get(c) not in (None, ""))
			print(f"   {f['fieldname']:<28} {f['fieldtype']:<13} sau {f['insert_after']:<26} {' '.join(co):<34} {them}")
	print(f"\n{sum(len(v) for v in kq.values())} Custom Field trên {len(kq)} DocType lõi")
	if canh_bao:
		print("CẢNH BÁO:")
		for c in canh_bao:
			print("  - " + c)
	if a.ghi:
		os.makedirs(os.path.dirname(DICH), exist_ok=True)
		with open(DICH, "w", encoding="utf-8") as f:
			json.dump(kq, f, ensure_ascii=False, indent=1, sort_keys=True)
			f.write("\n")
		print(f"đã ghi {DICH}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
