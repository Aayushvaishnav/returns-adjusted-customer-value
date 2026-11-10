"""Stream the original workbook without changing its contents."""

from datetime import date, datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path
import hashlib
import json

from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parents[1]
RAW_COLUMNS = (
    "invoice_raw", "stock_code_raw", "description_raw", "quantity_raw",
    "invoice_date_raw", "price_raw", "customer_id_raw", "country_raw",
)
COLUMNS = ("source_sheet", "source_row", *RAW_COLUMNS)


def load_config():
    return json.loads((PROJECT / "config/source.json").read_text(encoding="utf-8"))


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        raise ValueError("Boolean source cells are outside the workbook contract")
    if isinstance(value, (float, int)):
        return format(Decimal(str(value)), "f")
    return str(value)


def source_rows(path, config, scope):
    if scope not in {"sample", "full"}:
        raise ValueError(f"Unknown import scope: {scope}")
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if workbook.sheetnames != config["worksheets"]:
            raise ValueError(f"Unexpected worksheet names/order: {workbook.sheetnames}")
        for sheet_name in config["worksheets"]:
            sheet = workbook[sheet_name]
            if sheet.max_column != len(config["headers"]):
                raise ValueError(f"Unexpected column count in {sheet_name}")
            rows = sheet.iter_rows()
            header = [cell.value for cell in next(rows)]
            if header != config["headers"]:
                raise ValueError(f"Unexpected headers in {sheet_name}: {header}")
            selected = islice(rows, config["sample_rows_per_sheet"]) if scope == "sample" else rows
            for row_number, cells in enumerate(selected, start=2):
                if any(cell.data_type in {"f", "e"} for cell in cells):
                    raise ValueError(f"Formula/error source cell at {sheet_name}:{row_number}")
                yield (sheet_name, row_number, *(cell_text(cell.value) for cell in cells))
    finally:
        workbook.close()


def update_digest(digest, row):
    digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\n")
