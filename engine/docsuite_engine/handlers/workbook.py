"""Full-fidelity workbook I/O for the spreadsheet editor (sheet.open / sheet.save).

The editor is Univer; its document model is a JSON "workbook snapshot". This
module converts between that snapshot and files:

    .xlsx / .xlsm  read + write   values, formulas, styles, merges, sizes, freeze panes
    .csv / .tsv    read + write   values only (first sheet on write)
    .xls           read only      values only (legacy format, via xlrd)

Snapshot shape used here (a subset of Univer's IWorkbookData):

    {id, name, sheetOrder: [sheetId], styles: {styleId: style},
     sheets: {sheetId: {id, name, rowCount, columnCount,
                        cellData: {row: {col: {v, t, f, s}}},
                        mergeData: [{startRow, endRow, startColumn, endColumn}],
                        rowData: {row: {h, hd}}, columnData: {col: {w, hd}},
                        freeze: {xSplit, ySplit, startRow, startColumn}}}}

Cell `t`: 1 string, 2 number, 3 boolean. Style keys: ff fs bl it ul st cl bg ht vt tb n bd.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..rpc import EngineError, method
from ..util import atomic_output, in_path

MAX_CELLS = 400_000          # beyond this the grid is truncated and saving is refused
MIN_ROWS, MIN_COLS = 200, 26
PX_PER_CHAR = 7.0            # Excel column width unit (characters of the default font) -> pixels
COL_PAD_PX = 5.0
PX_PER_PT = 96.0 / 72.0

T_STRING, T_NUMBER, T_BOOL = 1, 2, 3

_H_ALIGN = {"left": 1, "center": 2, "right": 3, "justify": 4, "distributed": 6}
_V_ALIGN = {"top": 1, "center": 2, "bottom": 3}
_BORDER = {
    "thin": 1, "hair": 2, "dotted": 3, "dashed": 4, "dashDot": 5, "dashDotDot": 6, "double": 7,
    "medium": 8, "mediumDashed": 9, "mediumDashDot": 10, "mediumDashDotDot": 11, "slantDashDot": 12, "thick": 13,
}
_H_ALIGN_OUT = {v: k for k, v in _H_ALIGN.items()}
_V_ALIGN_OUT = {v: k for k, v in _V_ALIGN.items()}
_BORDER_OUT = {v: k for k, v in _BORDER.items()}
_SIDES = (("t", "top"), ("r", "right"), ("b", "bottom"), ("l", "left"))


# ------------------------------------------------------------------ reading

def _rgb(color: Any) -> Optional[str]:
    """openpyxl colour -> '#RRGGBB'. Theme/indexed colours are not resolved (returns None)."""
    if color is None or getattr(color, "type", None) != "rgb":
        return None
    value = color.rgb
    if not isinstance(value, str) or len(value) not in (6, 8):
        return None
    return "#" + value[-6:].upper()


def _style_in(cell: Any) -> Optional[dict]:
    style: Dict[str, Any] = {}
    font = cell.font
    if font is not None:
        if font.name and font.name != "Calibri":
            style["ff"] = font.name
        if font.sz and float(font.sz) != 11:
            style["fs"] = float(font.sz)
        if font.b:
            style["bl"] = 1
        if font.i:
            style["it"] = 1
        if font.underline:
            style["ul"] = {"s": 1}
        if font.strike:
            style["st"] = {"s": 1}
        rgb = _rgb(font.color)
        if rgb and rgb != "#000000":
            style["cl"] = {"rgb": rgb}
    fill = cell.fill
    if fill is not None and fill.fill_type == "solid":
        rgb = _rgb(fill.fgColor)
        if rgb:
            style["bg"] = {"rgb": rgb}
    align = cell.alignment
    if align is not None:
        if align.horizontal in _H_ALIGN:
            style["ht"] = _H_ALIGN[align.horizontal]
        if align.vertical in _V_ALIGN:
            style["vt"] = _V_ALIGN[align.vertical]
        if align.wrap_text:
            style["tb"] = 3
    if cell.number_format and cell.number_format != "General":
        style["n"] = {"pattern": cell.number_format}
    border = cell.border
    if border is not None:
        sides = {}
        for key, attr in _SIDES:
            side = getattr(border, attr)
            if side is not None and side.style in _BORDER:
                sides[key] = {"s": _BORDER[side.style], "cl": {"rgb": _rgb(side.color) or "#000000"}}
        if sides:
            style["bd"] = sides
    return style or None


def _value_in(value: Any) -> Tuple[Any, Optional[int]]:
    """Python value -> (v, t)."""
    from openpyxl.utils.datetime import to_excel

    if value is None:
        return None, None
    if isinstance(value, bool):
        return (1 if value else 0), T_BOOL
    if isinstance(value, (int, float)):
        return value, T_NUMBER
    if isinstance(value, (dt.datetime, dt.date)):
        return to_excel(value), T_NUMBER          # serial number; the cell's date format displays it
    if isinstance(value, dt.time):
        return (value.hour * 3600 + value.minute * 60 + value.second) / 86400, T_NUMBER
    if isinstance(value, dt.timedelta):
        return value.total_seconds() / 86400, T_NUMBER
    return str(value), T_STRING


def _blank_sheet(index: int, name: str) -> dict:
    return {
        "id": f"sheet-{index + 1}", "name": name, "rowCount": MIN_ROWS, "columnCount": MIN_COLS,
        "cellData": {}, "mergeData": [], "rowData": {}, "columnData": {},
    }


def _read_xlsx(path: Path) -> dict:
    from openpyxl import load_workbook
    from openpyxl.utils import column_index_from_string, coordinate_to_tuple

    try:
        wb = load_workbook(str(path))
        cached = load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 - zip/xml errors of several types
        raise EngineError("invalid_file", f"Could not read workbook: {exc}") from exc

    styles: Dict[str, dict] = {}
    style_ids: Dict[int, Optional[str]] = {}      # openpyxl style_id -> our style key
    sheets: Dict[str, dict] = {}
    order: List[str] = []
    notes: List[str] = []
    truncated = False
    budget = MAX_CELLS

    try:
        for index, ws in enumerate(wb.worksheets):
            sheet = _blank_sheet(index, ws.title)
            # Formula results Excel stored at last save, so cells show a value before recalculation.
            results: Dict[Tuple[int, int], Any] = {}
            has_formula = any(c.data_type == "f" for c in ws._cells.values())
            if has_formula:
                for row in cached[ws.title].iter_rows():
                    for c in row:
                        if c.value is not None:
                            results[(c.row, c.column)] = c.value

            cells: Dict[str, Dict[str, dict]] = {}
            max_row = max_col = 0
            for (r, c), cell in sorted(ws._cells.items()):
                if budget <= 0:
                    truncated = True
                    break
                entry: Dict[str, Any] = {}
                value = cell.value
                if cell.data_type == "f":
                    formula = getattr(value, "text", value)     # ArrayFormula keeps it in .text
                    entry["f"] = str(formula)
                    value = results.get((r, c))
                v, t = _value_in(value)
                if v is not None:
                    entry["v"], entry["t"] = v, t
                if cell.has_style:
                    if cell.style_id not in style_ids:
                        converted = _style_in(cell)
                        key = None
                        if converted:
                            key = f"s{len(styles) + 1}"
                            styles[key] = converted
                        style_ids[cell.style_id] = key
                    if style_ids[cell.style_id]:
                        entry["s"] = style_ids[cell.style_id]
                if not entry:
                    continue
                cells.setdefault(str(r - 1), {})[str(c - 1)] = entry
                max_row, max_col = max(max_row, r), max(max_col, c)
                budget -= 1
            sheet["cellData"] = cells

            for rng in ws.merged_cells.ranges:
                sheet["mergeData"].append(
                    {"startRow": rng.min_row - 1, "endRow": rng.max_row - 1,
                     "startColumn": rng.min_col - 1, "endColumn": rng.max_col - 1}
                )
                max_row, max_col = max(max_row, rng.max_row), max(max_col, rng.max_col)
            for letter, dim in ws.column_dimensions.items():
                col = column_index_from_string(letter) - 1
                data = {}
                if dim.width:
                    data["w"] = round(dim.width * PX_PER_CHAR + COL_PAD_PX)
                if dim.hidden:
                    data["hd"] = 1
                if data:
                    sheet["columnData"][str(col)] = data
            for number, dim in ws.row_dimensions.items():
                data = {}
                if dim.height:
                    data["h"] = round(dim.height * PX_PER_PT)
                if dim.hidden:
                    data["hd"] = 1
                if data:
                    sheet["rowData"][str(number - 1)] = data
            if ws.freeze_panes:
                row, col = coordinate_to_tuple(ws.freeze_panes)
                if row > 1 or col > 1:
                    sheet["freeze"] = {"xSplit": col - 1, "ySplit": row - 1, "startRow": row - 1, "startColumn": col - 1}
            if ws.sheet_state != "visible":
                sheet["hidden"] = 1

            sheet["rowCount"] = max(MIN_ROWS, max_row + 100)
            sheet["columnCount"] = max(MIN_COLS, max_col + 10)
            sheets[sheet["id"]] = sheet
            order.append(sheet["id"])

            lost = []
            if getattr(ws, "_charts", None):
                lost.append(f"{len(ws._charts)} chart(s)")
            if getattr(ws, "_images", None):
                lost.append(f"{len(ws._images)} image(s)")
            if ws.conditional_formatting:
                lost.append("conditional formatting")
            if ws.data_validations is not None and ws.data_validations.dataValidation:
                lost.append("data validation")
            if lost:
                notes.append(f"{ws.title}: {', '.join(lost)} not imported")
    finally:
        cached.close()
        wb.close()

    if truncated:
        notes.append(f"Only the first {MAX_CELLS:,} cells were loaded")
    return {"sheets": sheets, "sheetOrder": order, "styles": styles, "notes": notes, "truncated": truncated}


def _typed_text(text: str) -> Tuple[Any, int]:
    """CSV field -> number where unambiguous; '007' and '+44…' stay text."""
    raw = text.strip()
    if raw and (raw[0].isdigit() or raw[0] in "-.") and "_" not in raw:
        if not (len(raw) > 1 and raw[0] == "0" and raw[1].isdigit()):
            try:
                number = float(raw)
                return (int(number) if number.is_integer() and "." not in raw and "e" not in raw.lower() else number), T_NUMBER
            except ValueError:
                pass
    return text, T_STRING


def _grid_sheet(index: int, name: str, rows: List[List[Any]], typed: bool) -> dict:
    sheet = _blank_sheet(index, name)
    width = 0
    for r, row in enumerate(rows):
        line: Dict[str, dict] = {}
        for c, value in enumerate(row):
            if value is None or value == "":
                continue
            if typed and isinstance(value, str):
                if value.startswith("="):
                    line[str(c)] = {"f": value}
                    continue
                v, t = _typed_text(value)
            else:
                v, t = _value_in(value)
            line[str(c)] = {"v": v, "t": t}
        if line:
            sheet["cellData"][str(r)] = line
            width = max(width, len(row))
    sheet["rowCount"] = max(MIN_ROWS, len(rows) + 100)
    sheet["columnCount"] = max(MIN_COLS, width + 10)
    return sheet


def _read_delimited(path: Path) -> dict:
    ext = path.suffix.lower()
    rows: List[List[str]] = []
    truncated = False
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        delimiter = "\t" if ext == ".tsv" else ","
        if ext == ".csv":
            sample = fh.read(8192)
            fh.seek(0)
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                pass
        cells = 0
        for row in csv.reader(fh, delimiter=delimiter):
            cells += len(row)
            if cells > MAX_CELLS:
                truncated = True
                break
            rows.append(row)
    sheet = _grid_sheet(0, path.stem[:31] or "Sheet1", rows, typed=True)
    notes = [f"Only the first {len(rows):,} rows were loaded"] if truncated else []
    return {"sheets": {sheet["id"]: sheet}, "sheetOrder": [sheet["id"]], "styles": {}, "notes": notes, "truncated": truncated}


def _read_xls(path: Path) -> dict:
    import xlrd

    try:
        book = xlrd.open_workbook(str(path))
    except Exception as exc:  # noqa: BLE001
        raise EngineError("invalid_file", f"Could not read workbook: {exc}") from exc
    sheets: Dict[str, dict] = {}
    order: List[str] = []
    for index, ws in enumerate(book.sheets()):
        rows = []
        for r in range(ws.nrows):
            row = []
            for c in range(ws.ncols):
                cell = ws.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    row.append(bool(cell.value))
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                elif cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
                    row.append(int(cell.value))
                else:
                    row.append(cell.value)
            rows.append(row)
        sheet = _grid_sheet(index, ws.name, rows, typed=False)
        sheets[sheet["id"]] = sheet
        order.append(sheet["id"])
    notes = ["Legacy .xls: values only - formatting and formulas are not imported; save as .xlsx"]
    return {"sheets": sheets, "sheetOrder": order, "styles": {}, "notes": notes, "truncated": False}


@method("sheet.open")
def sheet_open(params, ctx):
    """{input} -> {workbook: <snapshot>, format, notes: [str], truncated}"""
    path = in_path(params)
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        data = _read_xlsx(path)
    elif ext in (".csv", ".tsv"):
        data = _read_delimited(path)
    elif ext == ".xls":
        data = _read_xls(path)
    else:
        raise EngineError("unsupported_format", f"Cannot open {ext or 'this file'} as a spreadsheet")
    notes, truncated = data.pop("notes"), data.pop("truncated")
    workbook = {"id": "workbook", "name": path.stem, "appVersion": "docsuite", "locale": "enUS", **data}
    return {"path": str(path), "format": ext[1:], "workbook": workbook, "notes": notes, "truncated": truncated}


# ------------------------------------------------------------------ writing

def _hex(color: Any) -> Optional[str]:
    """Univer colour {rgb: '#rrggbb' | 'rgb(r,g,b)'} -> 'RRGGBB'."""
    value = (color or {}).get("rgb") if isinstance(color, dict) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        return value.upper() if len(value) == 6 else None
    if value.startswith("rgb"):
        try:
            parts = [int(float(p)) for p in value[value.index("(") + 1 : value.index(")")].split(",")[:3]]
            return "".join(f"{max(0, min(255, p)):02X}" for p in parts)
        except (ValueError, IndexError):
            return None
    return None


def _apply_style(cell: Any, style: dict, cache: dict, key: Any) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    if key not in cache:
        font_args: Dict[str, Any] = {}
        if style.get("ff"):
            font_args["name"] = style["ff"]
        if style.get("fs"):
            font_args["sz"] = style["fs"]
        if style.get("bl"):
            font_args["b"] = True
        if style.get("it"):
            font_args["i"] = True
        if (style.get("ul") or {}).get("s"):
            font_args["underline"] = "single"
        if (style.get("st") or {}).get("s"):
            font_args["strike"] = True
        color = _hex(style.get("cl"))
        if color:
            font_args["color"] = "FF" + color
        fill = _hex(style.get("bg"))
        align_args: Dict[str, Any] = {}
        if style.get("ht") in _H_ALIGN_OUT:
            align_args["horizontal"] = _H_ALIGN_OUT[style["ht"]]
        if style.get("vt") in _V_ALIGN_OUT:
            align_args["vertical"] = _V_ALIGN_OUT[style["vt"]]
        if style.get("tb") == 3:
            align_args["wrap_text"] = True
        sides = {}
        for short, attr in _SIDES:
            side = (style.get("bd") or {}).get(short)
            if side and side.get("s") in _BORDER_OUT:
                sides[attr] = Side(style=_BORDER_OUT[side["s"]], color="FF" + (_hex(side.get("cl")) or "000000"))
        cache[key] = (
            Font(**font_args) if font_args else None,
            PatternFill(fill_type="solid", fgColor="FF" + fill) if fill else None,
            Alignment(**align_args) if align_args else None,
            Border(**sides) if sides else None,
            (style.get("n") or {}).get("pattern"),
        )
    font, fill_obj, alignment, border, pattern = cache[key]
    if font:
        cell.font = font
    if fill_obj:
        cell.fill = fill_obj
    if alignment:
        cell.alignment = alignment
    if border:
        cell.border = border
    if pattern:
        cell.number_format = pattern


def _value_out(cell: dict) -> Any:
    if cell.get("f"):
        formula = str(cell["f"])
        return formula if formula.startswith("=") else "=" + formula
    value = cell.get("v")
    if value is None or value == "":
        return None
    kind = cell.get("t")
    if kind == T_BOOL:
        return bool(value) and str(value).upper() not in ("0", "FALSE")
    if kind == T_NUMBER and isinstance(value, str):
        try:
            number = float(value)
            return int(number) if number.is_integer() and "." not in value else number
        except ValueError:
            return value
    return value


def _ordered_sheets(workbook: dict) -> List[dict]:
    sheets = workbook.get("sheets") or {}
    order = [sid for sid in workbook.get("sheetOrder") or [] if sid in sheets] or list(sheets)
    if not order:
        raise EngineError("bad_params", "Workbook has no sheets")
    return [sheets[sid] for sid in order]


_CHARTS = {"bar": "BarChart", "line": "LineChart", "pie": "PieChart", "scatter": "ScatterChart"}


def _add_chart(ws: Any, spec: dict) -> None:
    """{type, title?, range: {startRow, endRow, startColumn, endColumn}, anchor?} -> native Excel chart.

    First row of the range = series names, first column = categories (x values for scatter).
    """
    import openpyxl.chart as charts
    from openpyxl.chart import Reference, Series

    kind = spec.get("type")
    if kind not in _CHARTS:
        raise EngineError("bad_params", f"Unknown chart type: {kind}")
    rng = spec["range"]
    r1, r2, c1, c2 = rng["startRow"] + 1, rng["endRow"] + 1, rng["startColumn"] + 1, rng["endColumn"] + 1
    if r2 - r1 < 1 or c2 - c1 < 1:
        raise EngineError("bad_params", "A chart needs a header row, a label column and at least one value")
    chart = getattr(charts, _CHARTS[kind])()
    chart.title = spec.get("title") or None
    chart.width, chart.height = 16, 9
    categories = Reference(ws, min_col=c1, min_row=r1 + 1, max_row=r2)
    if kind == "scatter":
        chart.style = 13
        for col in range(c1 + 1, c2 + 1):
            values = Reference(ws, min_col=col, min_row=r1, max_row=r2)
            chart.series.append(Series(values, categories, title_from_data=True))
    else:
        last = c1 + 1 if kind == "pie" else c2     # a pie shows one series
        chart.add_data(Reference(ws, min_col=c1 + 1, max_col=last, min_row=r1, max_row=r2), titles_from_data=True)
        chart.set_categories(categories)
    ws.add_chart(chart, spec.get("anchor") or "H2")


def _write_xlsx(target: Path, workbook: dict, charts: List[dict]) -> int:
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    styles = workbook.get("styles") or {}
    cache: dict = {}
    by_id: Dict[str, Any] = {}
    used_names: set = set()
    for sheet in _ordered_sheets(workbook):
        title = str(sheet.get("name") or "Sheet")[:31]
        for bad in '[]:*?/\\':
            title = title.replace(bad, "_")
        while title.lower() in used_names:
            title = title[:28] + f"_{len(used_names)}"
        used_names.add(title.lower())
        ws = wb.create_sheet(title=title)
        by_id[str(sheet.get("id"))] = ws

        for r, row in (sheet.get("cellData") or {}).items():
            for c, data in (row or {}).items():
                if not isinstance(data, dict):
                    continue
                value = _value_out(data)
                style = data.get("s")
                style_key = style if isinstance(style, str) else id(style)
                if isinstance(style, str):
                    style = styles.get(style)
                if value is None and not style:
                    continue
                cell = ws.cell(row=int(r) + 1, column=int(c) + 1)
                if value is not None:
                    cell.value = value
                if isinstance(style, dict) and style:
                    _apply_style(cell, style, cache, style_key)

        for m in sheet.get("mergeData") or []:
            if m["endRow"] > m["startRow"] or m["endColumn"] > m["startColumn"]:
                ws.merge_cells(
                    start_row=m["startRow"] + 1, end_row=m["endRow"] + 1,
                    start_column=m["startColumn"] + 1, end_column=m["endColumn"] + 1,
                )
        for c, data in (sheet.get("columnData") or {}).items():
            dim = ws.column_dimensions[get_column_letter(int(c) + 1)]
            if data.get("w"):
                dim.width = max(0.5, (float(data["w"]) - COL_PAD_PX) / PX_PER_CHAR)
            if data.get("hd"):
                dim.hidden = True
        for r, data in (sheet.get("rowData") or {}).items():
            dim = ws.row_dimensions[int(r) + 1]
            # Univer stores auto-fitted heights separately ("ah"); only explicit ones are written.
            if data.get("h") and not data.get("ia", 0):
                dim.height = float(data["h"]) / PX_PER_PT
            if data.get("hd"):
                dim.hidden = True
        freeze = sheet.get("freeze") or {}
        x, y = int(freeze.get("xSplit") or 0), int(freeze.get("ySplit") or 0)
        if x > 0 or y > 0:
            ws.freeze_panes = ws.cell(row=y + 1, column=x + 1)
        if sheet.get("hidden"):
            ws.sheet_state = "hidden"

    if all(ws.sheet_state != "visible" for ws in wb.worksheets):
        wb.worksheets[0].sheet_state = "visible"    # Excel refuses a workbook with no visible sheet
    for spec in charts:
        ws = by_id.get(str(spec.get("sheet")))
        if ws is None:
            raise EngineError("bad_params", "A chart references a sheet that does not exist")
        _add_chart(ws, spec)
    wb.save(str(target))
    return len(wb.worksheets)


def _write_delimited(target: Path, workbook: dict, delimiter: str) -> None:
    sheet = _ordered_sheets(workbook)[0]
    cells = sheet.get("cellData") or {}
    rows_idx = sorted(int(r) for r, row in cells.items() if row)
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        for r in range((rows_idx[-1] + 1) if rows_idx else 0):
            row = cells.get(str(r)) or {}
            width = max((int(c) for c in row), default=-1) + 1
            line = []
            for c in range(width):
                data = row.get(str(c)) or {}
                value = data.get("v")          # the computed value for formula cells
                if value is None:
                    value = data.get("f") or ""
                elif data.get("t") == T_BOOL:
                    value = "TRUE" if value and str(value).upper() not in ("0", "FALSE") else "FALSE"
                line.append(value)
            writer.writerow(line)


@method("sheet.save")
def sheet_save(params, ctx):
    """{output, workbook: <snapshot>, charts?: [chart spec]} -> .xlsx / .csv / .tsv by extension."""
    output = Path(str(params["output"]))
    workbook = params["workbook"]
    if not isinstance(workbook, dict):
        raise EngineError("bad_params", "workbook must be an object")
    charts = params.get("charts") or []
    ext = output.suffix.lower()
    if ext == ".xlsx":
        with atomic_output(output) as tmp:
            count = _write_xlsx(tmp, workbook, charts)
        return {"output": str(output), "sheets": count, "charts": len(charts)}
    if ext in (".csv", ".tsv"):
        with atomic_output(output) as tmp:
            _write_delimited(tmp, workbook, "\t" if ext == ".tsv" else ",")
        note = "Only the first sheet was saved; CSV has no formatting or formulas" if len(workbook.get("sheets") or {}) > 1 else None
        return {"output": str(output), "sheets": 1, "warning": note} if note else {"output": str(output), "sheets": 1}
    raise EngineError("unsupported_format", f"Cannot save a spreadsheet as {ext or 'this type'}")
