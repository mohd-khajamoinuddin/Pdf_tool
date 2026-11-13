import datetime as dt

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from docsuite_engine.rpc import EngineError, call


@pytest.fixture()
def styled_xlsx(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Region", "Q1", "Q2", "Total"])
    ws.append(["North", 120, 135.5, "=B2+C2"])
    ws.append(["South", 98, 110, "=SUM(B3:C3)"])
    ws["A1"].font = Font(bold=True, italic=True, sz=14, name="Arial", color="FFCC0000")
    ws["A1"].fill = PatternFill(fill_type="solid", fgColor="FFFFE699")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
    ws["A1"].border = Border(bottom=Side(style="thick", color="FF0000FF"))
    ws["C2"].number_format = "#,##0.00"
    ws["A5"] = dt.date(2026, 3, 14)
    ws["A5"].number_format = "yyyy-mm-dd"
    ws["B5"] = True
    ws["C5"] = "007"
    ws.merge_cells("A7:C8")
    ws["A7"] = "merged"
    ws.column_dimensions["A"].width = 30
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "B2"
    wb.create_sheet("Notes").append(["hello"])
    hidden = wb.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    path = tmp_path / "styled.xlsx"
    wb.save(str(path))
    return path


def test_open_reads_values_styles_and_layout(styled_xlsx):
    result = call("sheet.open", {"input": str(styled_xlsx)})
    wb = result["workbook"]
    assert result["truncated"] is False and result["notes"] == []
    assert [wb["sheets"][i]["name"] for i in wb["sheetOrder"]] == ["Sales", "Notes", "Hidden"]
    sales = wb["sheets"][wb["sheetOrder"][0]]
    cells = sales["cellData"]

    assert cells["1"]["0"] == {"v": "North", "t": 1}
    assert cells["1"]["1"] == {"v": 120, "t": 2}
    assert cells["1"]["3"]["f"] == "=B2+C2"                    # formula kept; no cached value in a fresh file
    assert cells["4"]["1"] == {"v": 1, "t": 3}                 # boolean
    assert cells["4"]["2"] == {"v": "007", "t": 1}             # text that looks numeric stays text
    assert cells["4"]["0"]["t"] == 2 and cells["4"]["0"]["v"] == 46095   # date -> Excel serial
    assert wb["styles"][cells["4"]["0"]["s"]]["n"] == {"pattern": "yyyy-mm-dd"}

    head = wb["styles"][cells["0"]["0"]["s"]]
    assert head["bl"] == 1 and head["it"] == 1 and head["fs"] == 14 and head["ff"] == "Arial"
    assert head["cl"] == {"rgb": "#CC0000"} and head["bg"] == {"rgb": "#FFE699"}
    assert head["ht"] == 2 and head["vt"] == 1 and head["tb"] == 3
    assert head["bd"]["b"] == {"s": 13, "cl": {"rgb": "#0000FF"}}
    assert wb["styles"][cells["1"]["2"]["s"]]["n"] == {"pattern": "#,##0.00"}

    assert sales["mergeData"] == [{"startRow": 6, "endRow": 7, "startColumn": 0, "endColumn": 2}]
    assert sales["columnData"]["0"]["w"] == 215
    assert sales["rowData"]["0"]["h"] == 40
    assert sales["freeze"] == {"xSplit": 1, "ySplit": 1, "startRow": 1, "startColumn": 1}
    assert wb["sheets"][wb["sheetOrder"][2]]["hidden"] == 1


def test_xlsx_round_trip_preserves_formatting(styled_xlsx, tmp_path):
    snapshot = call("sheet.open", {"input": str(styled_xlsx)})["workbook"]
    out = tmp_path / "round.xlsx"
    assert call("sheet.save", {"output": str(out), "workbook": snapshot})["sheets"] == 3

    ws = load_workbook(str(out))["Sales"]
    assert ws["B2"].value == 120 and ws["C2"].value == 135.5 and ws["D3"].value == "=SUM(B3:C3)"
    assert ws["B5"].value is True and ws["C5"].value == "007"
    assert ws["A5"].value == dt.datetime(2026, 3, 14) and ws["A5"].number_format == "yyyy-mm-dd"
    a1 = ws["A1"]
    assert a1.font.b and a1.font.i and a1.font.sz == 14 and a1.font.name == "Arial" and a1.font.color.rgb == "FFCC0000"
    assert a1.fill.fill_type == "solid" and a1.fill.fgColor.rgb == "FFFFE699"
    assert (a1.alignment.horizontal, a1.alignment.vertical, a1.alignment.wrap_text) == ("center", "top", True)
    assert a1.border.bottom.style == "thick" and a1.border.bottom.color.rgb == "FF0000FF"
    assert ws["C2"].number_format == "#,##0.00"
    assert [str(r) for r in ws.merged_cells.ranges] == ["A7:C8"]
    assert ws.column_dimensions["A"].width == pytest.approx(30, abs=0.1)
    assert ws.row_dimensions[1].height == pytest.approx(30, abs=0.1)
    assert ws.freeze_panes == "B2"
    assert load_workbook(str(out))["Hidden"].sheet_state == "hidden"

    # A second trip changes nothing: the conversion is stable.
    again = call("sheet.open", {"input": str(out)})["workbook"]
    assert again["sheets"]["sheet-1"]["cellData"] == snapshot["sheets"]["sheet-1"]["cellData"]
    assert again["styles"] == snapshot["styles"]


def test_editor_style_shapes_are_accepted(tmp_path):
    """The editor emits inline style objects, rgb() colours and formulas with computed values."""
    workbook = {
        "sheetOrder": ["a"],
        "styles": {},
        "sheets": {"a": {"id": "a", "name": "Data: 1/2", "cellData": {
            "0": {"0": {"v": "x", "t": 1, "s": {"bl": 1, "cl": {"rgb": "rgb(255, 0, 0)"}, "bg": {"rgb": "#0f0"}}}},
            "1": {"0": {"f": "=1+2", "v": 3, "t": 2}, "1": {"v": "12.50", "t": 2}, "2": {"v": 0, "t": 3}},
        }}},
    }
    out = tmp_path / "editor.xlsx"
    call("sheet.save", {"output": str(out), "workbook": workbook})
    ws = load_workbook(str(out)).worksheets[0]
    assert ws.title == "Data_ 1_2"                              # characters Excel forbids are replaced
    assert ws["A1"].font.b and ws["A1"].font.color.rgb == "FFFF0000" and ws["A1"].fill.fgColor.rgb == "FF00FF00"
    assert ws["A2"].value == "=1+2" and ws["B2"].value == 12.5 and ws["C2"].value is False


def test_charts_are_written_natively(tmp_path):
    workbook = {"sheetOrder": ["a"], "sheets": {"a": {"id": "a", "name": "S", "cellData": {
        "0": {"0": {"v": "Region", "t": 1}, "1": {"v": "Q1", "t": 1}, "2": {"v": "Q2", "t": 1}},
        "1": {"0": {"v": "North", "t": 1}, "1": {"v": 120, "t": 2}, "2": {"v": 135, "t": 2}},
        "2": {"0": {"v": "South", "t": 1}, "1": {"v": 98, "t": 2}, "2": {"v": 110, "t": 2}},
    }}}}
    rng = {"startRow": 0, "endRow": 2, "startColumn": 0, "endColumn": 2}
    out = tmp_path / "charts.xlsx"
    charts = [{"sheet": "a", "type": t, "title": t, "range": rng, "anchor": f"E{2 + 16 * i}"}
              for i, t in enumerate(["bar", "line", "pie", "scatter"])]
    assert call("sheet.save", {"output": str(out), "workbook": workbook, "charts": charts})["charts"] == 4
    ws = load_workbook(str(out)).worksheets[0]
    assert sorted(type(c).__name__ for c in ws._charts) == ["BarChart", "LineChart", "PieChart", "ScatterChart"]
    bar = next(c for c in ws._charts if isinstance(c, BarChart))
    assert len(bar.series) == 2 and "$B$2:$B$3" in bar.series[0].val.numRef.f.replace("'", "")

    for bad in ({"sheet": "zz", "type": "bar", "range": rng}, {"sheet": "a", "type": "donut", "range": rng},
                {"sheet": "a", "type": "bar", "range": {**rng, "endRow": 0}}):
        with pytest.raises(EngineError):
            call("sheet.save", {"output": str(tmp_path / "bad.xlsx"), "workbook": workbook, "charts": [bad]})
    assert not (tmp_path / "bad.xlsx").exists()


def test_unsupported_content_is_reported_not_silently_dropped(tmp_path):
    wb = Workbook()
    ws = wb.active
    for row in (["a", "b"], [1, 2], [3, 4]):
        ws.append(row)
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    ws.add_chart(chart, "D2")
    path = tmp_path / "chart.xlsx"
    wb.save(str(path))
    notes = call("sheet.open", {"input": str(path)})["notes"]
    assert notes == ["Sheet: 1 chart(s) not imported"]


def test_csv_tsv_and_xls(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("name;qty;code;calc\nwidget;4;007;=B2*2\ngadget;2.5;+44 20;x\n", encoding="utf-8")
    result = call("sheet.open", {"input": str(src)})
    cells = result["workbook"]["sheets"]["sheet-1"]["cellData"]
    assert result["format"] == "csv"
    assert cells["1"] == {"0": {"v": "widget", "t": 1}, "1": {"v": 4, "t": 2}, "2": {"v": "007", "t": 1}, "3": {"f": "=B2*2"}}
    assert cells["2"]["1"] == {"v": 2.5, "t": 2} and cells["2"]["2"] == {"v": "+44 20", "t": 1}

    # Saving CSV writes computed values (the editor fills `v` for formula cells).
    cells["1"]["3"]["v"] = 8
    out = tmp_path / "out.tsv"
    call("sheet.save", {"output": str(out), "workbook": result["workbook"]})
    assert out.read_text(encoding="utf-8-sig").splitlines() == ["name\tqty\tcode\tcalc", "widget\t4\t007\t8", "gadget\t2.5\t+44 20\tx"]

    with pytest.raises(EngineError) as err:
        call("sheet.open", {"input": str(tmp_path / "in.csv").replace("in.csv", "in.ods")})
    assert err.value.code in ("not_found", "unsupported_format")
    with pytest.raises(EngineError) as err:
        call("sheet.save", {"output": str(tmp_path / "x.ods"), "workbook": result["workbook"]})
    assert err.value.code == "unsupported_format"

    bad = tmp_path / "broken.xlsx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(EngineError) as err:
        call("sheet.open", {"input": str(bad)})
    assert err.value.code == "invalid_file"
