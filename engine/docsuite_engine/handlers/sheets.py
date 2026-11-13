"""Spreadsheet I/O (sheet.*) for the Spreadsheets module."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any, List

from ..rpc import EngineError, method
from ..util import atomic_output, in_path

DEFAULT_MAX_ROWS = 5000
MAX_COLS = 256

def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _trim(rows: List[list]) -> List[list]:
    while rows and all(c == "" for c in rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, c in enumerate(r) if c != ""), default=0) for r in rows), default=0)
    return [r[:width] + [""] * (width - len(r)) for r in rows]


@method("sheet.read")
def sheet_read(params, ctx):
    """{input, max_rows?} -> {sheets: [{name, rows, total_rows, truncated}]}.

    ``rows`` holds what the user would type: formulas stay as "=SUM(A1:A3)".
    ``values`` (xlsx only) holds the results Excel cached at last save.
    """
    path = in_path(params)
    max_rows = int(params.get("max_rows", DEFAULT_MAX_ROWS))
    ext = path.suffix.lower()

    if ext in (".csv", ".tsv"):
        rows: List[list] = []
        total = 0
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            delimiter = "\t" if ext == ".tsv" else ","
            if ext == ".csv":
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    pass
            for row in csv.reader(fh, delimiter=delimiter):
                total += 1
                if total <= max_rows:
                    rows.append(row[:MAX_COLS])
        return {
            "path": str(path),
            "format": ext[1:],
            "sheets": [{"name": path.stem, "rows": _trim(rows), "total_rows": total, "truncated": total > max_rows}],
        }

    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        sheets = []
        formulas = load_workbook(str(path), read_only=True, data_only=False)
        cached = load_workbook(str(path), read_only=True, data_only=True)
        try:
            for ws, ws_values in zip(formulas.worksheets, cached.worksheets):
                rows = [
                    [_cell(v) for v in row]
                    for row in ws.iter_rows(values_only=True, max_row=max_rows, max_col=MAX_COLS)
                ]
                values = [
                    [_cell(v) for v in row]
                    for row in ws_values.iter_rows(values_only=True, max_row=max_rows, max_col=MAX_COLS)
                ]
                rows = _trim(rows)
                width = len(rows[0]) if rows else 0
                values = [r[:width] + [""] * (width - len(r)) for r in values[: len(rows)]]
                total = ws.max_row or len(rows)
                sheets.append(
                    {"name": ws.title, "rows": rows, "values": values, "total_rows": total, "truncated": total > max_rows}
                )
        finally:
            formulas.close()
            cached.close()
        return {"path": str(path), "format": "xlsx", "sheets": sheets}

    raise EngineError("unsupported_format", f"Cannot open {ext or 'this file'} as a spreadsheet yet")


def _coerce(value: Any) -> Any:
    """Typed-in text -> number where it is unambiguously one."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "":
        return None
    if text.startswith("="):
        return text
    if text[0] in "+-0123456789." and "_" not in text:
        # Keep identifiers such as "007" or "+44 20..." as text.
        if len(text) > 1 and text[0] == "0" and text[1].isdigit():
            return value
        try:
            return int(text) if text.lstrip("+-").isdigit() and text[0] != "+" else float(text)
        except ValueError:
            return value
    return value


@method("sheet.write")
def sheet_write(params, ctx):
    """{output, sheets: [{name, rows}]} -> .xlsx or .csv by extension."""
    output = Path(str(params["output"]))
    sheets = params["sheets"]
    if not sheets:
        raise EngineError("bad_params", "Nothing to save")
    ext = output.suffix.lower()

    if ext == ".csv":
        with atomic_output(output) as tmp, open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerows(sheets[0]["rows"])
        return {"output": str(output), "sheets": 1, "note": "CSV holds one sheet" if len(sheets) > 1 else None}

    if ext == ".xlsx":
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        for sheet in sheets:
            ws = wb.create_sheet(title=str(sheet.get("name") or "Sheet")[:31])
            for row in sheet["rows"]:
                ws.append([_coerce(v) for v in row])
        with atomic_output(output) as tmp:
            wb.save(str(tmp))
        return {"output": str(output), "sheets": len(sheets)}

    raise EngineError("unsupported_format", f"Cannot save a spreadsheet as {ext or 'this type'}")
