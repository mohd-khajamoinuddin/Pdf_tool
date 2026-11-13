from docsuite_engine.rpc import call


def test_sheet_roundtrip_keeps_types_and_formulas(tmp_path):
    xlsx = tmp_path / "book.xlsx"
    sheets = [
        {"name": "Sales", "rows": [["item", "qty", "code"], ["widget", "4", "007"], ["total", "=SUM(B2:B2)", ""]]},
        {"name": "Notes", "rows": [["hello"]]},
    ]
    call("sheet.write", {"output": str(xlsx), "sheets": sheets})
    back = call("sheet.read", {"input": str(xlsx)})
    assert [s["name"] for s in back["sheets"]] == ["Sales", "Notes"]
    rows = back["sheets"][0]["rows"]
    assert rows[1] == ["widget", 4, "007"]          # number coerced, leading-zero code kept as text
    assert rows[2][1] == "=SUM(B2:B2)"              # formula preserved

    csv_path = tmp_path / "book.csv"
    call("sheet.write", {"output": str(csv_path), "sheets": sheets})
    back = call("sheet.read", {"input": str(csv_path)})
    assert back["sheets"][0]["rows"][1] == ["widget", "4", "007"]

    semi = tmp_path / "semi.csv"
    semi.write_text("a;b\n1;2\n", encoding="utf-8")
    assert call("sheet.read", {"input": str(semi)})["sheets"][0]["rows"] == [["a", "b"], ["1", "2"]]


def test_sheet_read_truncates_large_files(tmp_path):
    big = tmp_path / "big.csv"
    big.write_text("\n".join(f"{i},x" for i in range(50)), encoding="utf-8")
    sheet = call("sheet.read", {"input": str(big), "max_rows": 10})["sheets"][0]
    assert len(sheet["rows"]) == 10 and sheet["total_rows"] == 50 and sheet["truncated"] is True
