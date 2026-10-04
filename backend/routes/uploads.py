from __future__ import annotations

import io
import asyncio
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..models import DeliveryDraft, DeliveryUploadError, DeliveryUploadResult

router = APIRouter(prefix="/scenarios/uploads", tags=["uploads"])

REQUIRED_COLUMNS = (
    "customer_name",
    "lat",
    "lng",
    "demand_cases",
    "service_minutes",
    "receiving_window_start",
    "receiving_window_end",
)
OPTIONAL_COLUMNS = ("delivery_day", "customer_id")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
MAX_UPLOAD_BYTES = int(os.getenv("XLSX_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
MAX_ARCHIVE_ENTRIES = int(os.getenv("XLSX_MAX_ARCHIVE_ENTRIES", "200"))
MAX_ENTRY_BYTES = int(os.getenv("XLSX_MAX_ENTRY_BYTES", str(20 * 1024 * 1024)))
MAX_UNCOMPRESSED_BYTES = int(os.getenv("XLSX_MAX_UNCOMPRESSED_BYTES", str(50 * 1024 * 1024)))
MAX_COMPRESSION_RATIO = int(os.getenv("XLSX_MAX_COMPRESSION_RATIO", "100"))
MAX_WORKSHEETS = int(os.getenv("XLSX_MAX_WORKSHEETS", "5"))
MAX_ROWS = int(os.getenv("XLSX_MAX_ROWS", "5000"))
MAX_COLUMNS = int(os.getenv("XLSX_MAX_COLUMNS", "50"))
PARSE_TIMEOUT_SECONDS = float(os.getenv("XLSX_PARSE_TIMEOUT_SECONDS", "15"))
_parse_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="xlsx-parser")


def _reject_unsafe_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise HTTPException(status_code=413, detail="Workbook contains too many archive entries.")
            total = 0
            for entry in entries:
                normalized = entry.filename.replace("\\", "/").lower()
                if normalized.startswith("/") or "../" in normalized:
                    raise HTTPException(status_code=400, detail="Workbook contains an unsafe archive path.")
                if "vbaproject" in normalized or normalized.endswith(".bin"):
                    raise HTTPException(status_code=400, detail="Macro-enabled workbooks are not supported.")
                if entry.file_size > MAX_ENTRY_BYTES:
                    raise HTTPException(status_code=413, detail="Workbook contains an oversized entry.")
                total += entry.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=413, detail="Workbook expands beyond the supported size.")
                if entry.file_size and entry.file_size / max(entry.compress_size, 1) > MAX_COMPRESSION_RATIO:
                    raise HTTPException(status_code=413, detail="Workbook compression ratio is unsafe.")
                if normalized.endswith(".rels"):
                    relation_xml = archive.read(entry)
                    if b'TargetMode="External"' in relation_xml or b"TargetMode='External'" in relation_xml:
                        raise HTTPException(status_code=400, detail="External workbook relationships are not supported.")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Workbook is not a valid XLSX archive.") from exc


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _parse_int(value: object, *, field: str, row_num: int) -> int:
    if value is None or (isinstance(value, float) and value != value):
        raise ValueError(f"Row {row_num}: {field} is required")
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_num}: {field} must be an integer") from exc


def _parse_float(value: object, *, field: str, row_num: int) -> float:
    if value is None or (isinstance(value, float) and value != value):
        raise ValueError(f"Row {row_num}: {field} is required")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_num}: {field} must be a number") from exc


def _parse_time(value: object, *, field: str, row_num: int, default: str) -> str:
    if value is None or value == "":
        return default
    text = str(value).strip()
    if not TIME_PATTERN.match(text):
        raise ValueError(f"Row {row_num}: {field} must look like HH:MM")
    hours, minutes = text.split(":")
    return f"{int(hours):02d}:{int(minutes):02d}"


def parse_deliveries_workbook(content: bytes) -> DeliveryUploadResult:
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Workbook exceeds the upload size limit.")
    _reject_unsafe_archive(content)
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency declared in requirements
        raise HTTPException(status_code=500, detail="openpyxl is not installed") from exc

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), data_only=True, read_only=True, keep_links=False
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Workbook could not be parsed safely.") from exc
    if len(workbook.worksheets) > MAX_WORKSHEETS:
        workbook.close()
        raise HTTPException(status_code=413, detail="Workbook contains too many worksheets.")
    sheet = workbook.active
    if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS:
        workbook.close()
        raise HTTPException(status_code=413, detail="Workbook exceeds the supported row or column limit.")
    rows = sheet.iter_rows(values_only=True)
    first_row = next(rows, None)
    if first_row is None:
        workbook.close()
        return DeliveryUploadResult(deliveries=[], errors=[DeliveryUploadError(row=1, message="Workbook is empty")])

    headers = [_normalize_header(cell) for cell in first_row]
    header_index = {name: idx for idx, name in enumerate(headers) if name}
    missing = [col for col in REQUIRED_COLUMNS if col not in header_index]
    errors: list[DeliveryUploadError] = []
    if missing:
        return DeliveryUploadResult(
            deliveries=[],
            errors=[
                DeliveryUploadError(
                    row=1,
                    message=f"Missing required columns: {', '.join(missing)}",
                )
            ],
        )

    deliveries: list[DeliveryDraft] = []
    for excel_row_num, values in enumerate(rows, start=2):
        if excel_row_num > MAX_ROWS:
            workbook.close()
            raise HTTPException(status_code=413, detail="Workbook exceeds the supported row limit.")
        if values is None or all(cell is None or str(cell).strip() == "" for cell in values):
            continue

        def cell(name: str) -> Any:
            idx = header_index.get(name)
            if idx is None or idx >= len(values):
                return None
            return values[idx]

        try:
            customer_name = str(cell("customer_name") or "").strip()
            if not customer_name:
                raise ValueError(f"Row {excel_row_num}: customer_name is required")
            lat = _parse_float(cell("lat"), field="lat", row_num=excel_row_num)
            lng = _parse_float(cell("lng"), field="lng", row_num=excel_row_num)
            if not (-90 <= lat <= 90):
                raise ValueError(f"Row {excel_row_num}: lat must be between -90 and 90")
            if not (-180 <= lng <= 180):
                raise ValueError(f"Row {excel_row_num}: lng must be between -180 and 180")
            demand_cases = _parse_int(cell("demand_cases"), field="demand_cases", row_num=excel_row_num)
            service_minutes = _parse_int(
                cell("service_minutes"),
                field="service_minutes",
                row_num=excel_row_num,
            )
            window_start = _parse_time(
                cell("receiving_window_start"),
                field="receiving_window_start",
                row_num=excel_row_num,
                default="08:00",
            )
            window_end = _parse_time(
                cell("receiving_window_end"),
                field="receiving_window_end",
                row_num=excel_row_num,
                default="16:00",
            )
            delivery_day_raw = cell("delivery_day")
            delivery_day = str(delivery_day_raw).strip() if delivery_day_raw not in (None, "") else None
            customer_id_raw = cell("customer_id")
            customer_id = str(customer_id_raw).strip() if customer_id_raw not in (None, "") else None
            deliveries.append(
                DeliveryDraft(
                    customer_name=customer_name,
                    lat=lat,
                    lng=lng,
                    demand_cases=demand_cases,
                    service_minutes=service_minutes,
                    receiving_window_start=window_start,
                    receiving_window_end=window_end,
                    delivery_day=delivery_day,
                    customer_id=customer_id,
                )
            )
        except ValueError as exc:
            errors.append(DeliveryUploadError(row=excel_row_num, message=str(exc)))

    workbook.close()
    return DeliveryUploadResult(deliveries=deliveries, errors=errors)


def build_template_bytes() -> bytes:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="openpyxl is not installed") from exc

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "deliveries"
    headers = list(REQUIRED_COLUMNS) + list(OPTIONAL_COLUMNS)
    sheet.append(headers)
    sheet.append(
        [
            "Acme Market",
            42.35,
            -83.05,
            90,
            30,
            "08:00",
            "16:00",
            "Tuesday",
            "",
        ]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.read()


@router.post("/deliveries", response_model=DeliveryUploadResult)
async def upload_deliveries(file: UploadFile = File(...)) -> DeliveryUploadResult:
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Upload an .xlsx Excel workbook.")
    declared_size = file.headers.get("content-length")
    if declared_size and declared_size.isdigit() and int(declared_size) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Workbook exceeds the upload size limit.")
    content = bytearray()
    while chunk := await file.read(64 * 1024):
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Workbook exceeds the upload size limit.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_parse_executor, parse_deliveries_workbook, bytes(content)),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="Workbook parsing exceeded the time limit.") from exc


@router.get("/template")
def download_template() -> StreamingResponse:
    content = build_template_bytes()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="delivery_upload_template.xlsx"'},
    )
