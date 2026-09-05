"""Shipment REST API — Word spec §7 operator workspace."""

from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.enums import (
    DocType,
    ErrorSeverity,
    ErrorType,
    PermitDatabaseSource,
    ProfileType,
    ShipmentStatus,
)
from app.models.item import Item
from app.models.permit import PermitDatabase
from app.models.shipment import Shipment
from app.models.uploaded_file import UploadedFile
from app.models.validation_error import ValidationError
from app.parsing.pdf_extractor import sniff_kind
from app.parsing.pipeline import parse_file
from app.schemas.api import (
    ExportOut,
    FileOut,
    HeaderFieldsSchema,
    ItemOut,
    ItemUpdate,
    PermitCandidate,
    PermitSearchOut,
    ShipmentCreateResponse,
    ValidationErrorOut,
    WorkspaceOut,
)
from app.services.catalog import CatalogIndex
from app.services.export import export_18233, export_beijing
from app.services.export_18233_templates import export_18233_from_templates
from app.services.materials_18233 import kit_sources, materials_available
from app.services.profile_18233 import parse_bundle, reconcile_18233
from app.services.reconcile import items_to_dicts, reconcile_documents

SUPPORTED_UPLOAD_SUFFIXES = {
    ".xlsx",
    ".xls",
    ".xlsm",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def _validate_upload_filename(filename: str) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Формат «{suffix or 'без расширения'}» не поддерживается. "
                "Можно загружать Excel (.xlsx, .xls), PDF и изображения (.png, .jpg)."
            ),
        )


def _allow_ocr_for_upload(path: Path) -> bool:
    return sniff_kind(str(path)) in {"pdf", "image"}


def _guess_doc_type(filename: str, parsed_type: DocType | None) -> DocType | None:
    kind = _classify_18233_filename(filename)
    if kind == "invoice":
        return DocType.INVOICE
    if kind == "packing":
        return DocType.PACKING_LIST
    if kind == "specification":
        return DocType.SPECIFICATION
    name_l = filename.lower()
    if name_l.endswith(".pdf") or name_l.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        if any(token in name_l for token in ("описание", "description", "desc")):
            return DocType.SPECIFICATION
        if any(token in name_l for token in ("permit", "разреш", "рд", "rd")):
            return DocType.PERMIT
    return parsed_type


def _classify_18233_filename(filename: str) -> str | None:
    """Map upload name → invoice | packing | specification (EN + RU)."""
    name = filename.upper()
    stem = Path(filename).stem.upper()
    if (
        "INVOICE" in name
        or "ИНВОЙС" in name
        or stem.endswith("_CI")
        or stem.endswith("-CI")
        or stem.endswith(" CI")
        or " COMMERCIAL INVOICE" in f" {name}"
    ):
        return "invoice"
    if (
        "-PL" in name
        or "_PL." in name
        or stem.endswith("_PL")
        or stem.endswith("-PL")
        or "PACKING" in name
        or name.endswith("PL.XLSX")
        or name.endswith("PL.PDF")
        or "ПАКИНГ" in name
    ):
        return "packing"
    if "SPEC" in name or "СПЕЦИФ" in name:
        return "specification"
    return None


def _is_ready_etalon_filename(filename: str) -> bool:
    """Customer «02_Готовые» / our export — not source inputs from «01_Исходники»."""
    name = filename.upper()
    if "ЦВЕТАМ" in name:
        return True
    if "YS-RMB-EXW" in name or "SPECIFICATION.XLS" in name:
        return False
    # Russian ready templates look like «18233 ИНВОЙС 626-1.xlsx»
    if any(token in name for token in ("ИНВОЙС", "ПАКИНГ", "СПЕЦИФ")) and "18233" in name:
        return True
    return False


def _looks_like_18233(paths: list[Path]) -> bool:
    """Zhongfang 626-x kits must use dedicated parser (not generic BEIJING path)."""
    names = [path.name.upper() for path in paths]
    blob = " ".join(names)
    return any(token in blob for token in ("YS-RMB-EXW", "626-1", "626-2", "ZHONGFANG"))


def _detect_kit_code(paths: list[Path]) -> str | None:
    blob = " ".join(p.name for p in paths).upper()
    if "626-2" in blob:
        return "626-2"
    if "626-1" in blob:
        return "626-1"
    return None


def _complete_18233_kit(saved_paths: list[Path]) -> tuple[list[Path], list[str]]:
    """If PL/Spec missing, pull them from local MVP materials for the same kit."""
    present = {k: p for p in saved_paths if (k := _classify_18233_filename(p.name))}
    missing = {"invoice", "packing", "specification"} - set(present)
    if not missing or not materials_available():
        return saved_paths, []
    kit = _detect_kit_code(saved_paths)
    if kit is None:
        return saved_paths, []
    try:
        sources = kit_sources(kit)
    except Exception:
        return saved_paths, []

    completed = list(saved_paths)
    notes: list[str] = []
    known = {p.resolve() for p in completed}
    for role in ("invoice", "packing", "specification"):
        if role in present:
            continue
        src = sources.get(role)
        if src is None or not src.exists():
            continue
        if src.resolve() in known:
            continue
        completed.append(src)
        known.add(src.resolve())
        notes.append(src.name)
    return completed, notes


router = APIRouter(prefix="/api/v1/shipments", tags=["shipments"])

UPLOAD_ROOT = Path("uploads")
EXPORT_ROOT = Path("exports")


def _save_upload(shipment_id: uuid.UUID, upload: UploadFile) -> Path:
    dest_dir = UPLOAD_ROOT / str(shipment_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename or "upload.bin").name
    dest = dest_dir / safe_name
    with dest.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    return dest


def _persist_reconciled(db: Session, shipment: Shipment, reconciled: list[dict[str, Any]]) -> None:
    for old in list(shipment.items):
        db.delete(old)
    db.flush()

    for row in reconciled:
        item = Item(
            shipment_id=shipment.id,
            article=row.get("article"),
            model=row.get("model"),
            normalized_article=row.get("normalized_article") or "",
            commercial_data=row.get("commercial_data") or {},
            packing_data=row.get("packing_data") or {},
            customs_data=row.get("customs_data") or {},
            source_traces=row.get("source_traces") or {},
        )
        db.add(item)
        db.flush()
        for flag in row.get("validation_errors") or []:
            db.add(
                ValidationError(
                    item_id=item.id,
                    field_name=flag["field_name"],
                    error_type=ErrorType(flag["error_type"]),
                    severity=ErrorSeverity(flag["severity"]),
                    details=flag.get("details"),
                    message=flag.get("message"),
                )
            )


def _item_out(item: Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        article=item.article,
        model=item.model,
        normalized_article=item.normalized_article,
        commercial_data=item.commercial_data or {},
        packing_data=item.packing_data or {},
        customs_data=item.customs_data or {},
        source_traces=item.source_traces or {},
        validation_errors=[
            ValidationErrorOut(
                id=err.id,
                field_name=err.field_name,
                error_type=err.error_type,
                severity=err.severity,
                details=err.details,
                message=err.message,
                resolved=err.resolved,
            )
            for err in item.validation_errors
        ],
    )


@router.post("/", response_model=ShipmentCreateResponse)
async def create_shipment(
    title: str = Form(...),
    profile_type: ProfileType = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> ShipmentCreateResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Загрузите хотя бы один файл комплекта")

    shipment = Shipment(
        title=title,
        profile_type=profile_type,
        status=ShipmentStatus.PARSING,
        header_fields={},
    )
    db.add(shipment)
    db.flush()

    parsed_docs = []
    catalog: CatalogIndex | None = None
    file_outs: list[FileOut] = []
    saved_paths: list[Path] = []

    for upload in files:
        _validate_upload_filename(upload.filename or "")
        path = _save_upload(shipment.id, upload)
        saved_paths.append(path)
        try:
            document = parse_file(
                str(path),
                filename=upload.filename,
                allow_ocr=_allow_ocr_for_upload(path),
            )
        except Exception as exc:
            from app.parsing.schemas import ParsedDocument

            document = ParsedDocument(
                filename=upload.filename or path.name,
                file_path=str(path),
                mime_hint=sniff_kind(str(path)),
                warnings=[f"parse_failed:{exc}"],
            )
        document.doc_type = _guess_doc_type(upload.filename or path.name, document.doc_type)
        parsed_docs.append(document)

        name_l = (upload.filename or "").lower()
        if "сводная" in name_l or "svodn" in name_l or document.doc_type == DocType.CATALOG:
            document.doc_type = DocType.CATALOG
            try:
                catalog = CatalogIndex.from_excel(path)
            except Exception:
                pass

        db_file = UploadedFile(
            shipment_id=shipment.id,
            filename=upload.filename or path.name,
            doc_type=document.doc_type,
            file_path=str(path),
            mime_type=upload.content_type,
            ocr_confidence=document.ocr_confidence,
        )
        db.add(db_file)
        db.flush()
        file_outs.append(
            FileOut(
                id=db_file.id,
                filename=db_file.filename,
                doc_type=db_file.doc_type,
                ocr_confidence=db_file.ocr_confidence,
            )
        )

    shipment.status = ShipmentStatus.RECONCILING
    db.flush()

    # Dedicated 18233 parser only for Zhongfang kits — Tosun/BEIJING files go generic path
    use_18233 = _looks_like_18233(saved_paths) or (
        profile_type == ProfileType.PROFILE_18233
        and any(_classify_18233_filename(p.name) for p in saved_paths)
        and any(token in " ".join(p.name.upper() for p in saved_paths) for token in ("YS-RMB-EXW", "626-1", "626-2"))
    )
    if use_18233:
        if profile_type != ProfileType.PROFILE_18233:
            shipment.profile_type = ProfileType.PROFILE_18233

        ready = [p.name for p in saved_paths if _is_ready_etalon_filename(p.name)]
        if ready and not any(_classify_18233_filename(p.name) and not _is_ready_etalon_filename(p.name) for p in saved_paths):
            # Only ready files, no source YS-RMB-EXW — reject
            if all(_is_ready_etalon_filename(p.name) for p in saved_paths):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Загружены готовые/эталонные файлы ("
                        + ", ".join(ready)
                        + "). Нужны исходники из папки «01_Исходники»: "
                        "…INVOICE.XLSX, …PL.XLSX, …Specification.xls."
                    ),
                )

        parse_paths, auto_names = _complete_18233_kit(saved_paths)
        for extra in parse_paths[len(saved_paths) :]:
            dest_dir = UPLOAD_ROOT / str(shipment.id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / extra.name
            if not dest.exists():
                shutil.copy2(extra, dest)
            db_file = UploadedFile(
                shipment_id=shipment.id,
                filename=extra.name,
                doc_type=_guess_doc_type(extra.name, None),
                file_path=str(dest),
                mime_type="application/vnd.ms-excel",
                ocr_confidence=None,
            )
            db.add(db_file)
            db.flush()
            file_outs.append(
                FileOut(
                    id=db_file.id,
                    filename=db_file.filename,
                    doc_type=db_file.doc_type,
                    ocr_confidence=db_file.ocr_confidence,
                )
            )
        if auto_names:
            shipment.notes = (shipment.notes or "") + f" auto_kit:{','.join(auto_names)}"

        kinds = {k for p in parse_paths if (k := _classify_18233_filename(p.name))}
        has_excel_kit = "invoice" in kinds or "specification" in kinds
        if not has_excel_kit:
            scannable = [d for d in parsed_docs if d.mime_hint in {"pdf", "image"}]
            if scannable:
                reconciled = items_to_dicts(reconcile_documents(parsed_docs, catalog=catalog))
                if not reconciled:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Из PDF/скана не удалось извлечь позиции. "
                            "Нужен PDF с таблицей артикулов или Excel из «01_Исходники»."
                        ),
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Не найден инвойс или спецификация. Загрузите файл "
                        "…INVOICE.XLSX, …Specification.xls или PDF со сканом документов."
                    ),
                )
        else:
            bundle = parse_bundle(parse_paths)
            if bundle.header_hints:
                shipment.header_fields = {
                    **(shipment.header_fields or {}),
                    **{k: v for k, v in bundle.header_hints.items() if v},
                }
            reconciled = items_to_dicts(reconcile_18233(bundle))
            products = [
                r
                for r in reconciled
                if (r.get("source_traces") or {}).get("invoice")
                or (r.get("source_traces") or {}).get("specification")
            ]
            if not products:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Позиции не распознаны (0 артикулов). Проверьте, что загружены "
                        "исходные Invoice / PL / Specification.xls, а не файлы из «02_Готовые»."
                    ),
                )
    else:
        reconciled = items_to_dicts(reconcile_documents(parsed_docs, catalog=catalog))
        if not reconciled:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Не удалось найти товарные строки в файлах. "
                    "Нужен Excel или PDF с таблицей: колонки вроде артикул/название "
                    "и хотя бы количество, цена или вес."
                ),
            )
    _persist_reconciled(db, shipment, reconciled)

    warning_count = sum(len(r.get("validation_errors") or []) for r in reconciled)
    shipment.status = (
        ShipmentStatus.NEEDS_REVIEW if warning_count else ShipmentStatus.READY_TO_EXPORT
    )
    db.commit()
    db.refresh(shipment)

    return ShipmentCreateResponse(
        id=shipment.id,
        title=shipment.title,
        profile_type=shipment.profile_type,
        status=shipment.status,
        files=file_outs,
        item_count=len(reconciled),
        warning_count=warning_count,
    )


@router.get("/{shipment_id}/workspace", response_model=WorkspaceOut)
def get_workspace(shipment_id: uuid.UUID, db: Session = Depends(get_db)) -> WorkspaceOut:
    shipment = db.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.files),
            selectinload(Shipment.items).selectinload(Item.validation_errors),
        )
    )
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return WorkspaceOut(
        id=shipment.id,
        title=shipment.title,
        profile_type=shipment.profile_type,
        status=shipment.status,
        header_fields=shipment.header_fields or {},
        files=[
            FileOut(
                id=f.id,
                filename=f.filename,
                doc_type=f.doc_type,
                ocr_confidence=f.ocr_confidence,
            )
            for f in shipment.files
        ],
        items=[_item_out(item) for item in shipment.items],
        created_at=shipment.created_at,
    )


@router.put("/{shipment_id}/items/{item_id}", response_model=ItemOut)
def update_item(
    shipment_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ItemUpdate,
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.scalar(
        select(Item)
        .where(Item.id == item_id, Item.shipment_id == shipment_id)
        .options(selectinload(Item.validation_errors))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if payload.article is not None:
        item.article = payload.article
    if payload.model is not None:
        item.model = payload.model
    if payload.commercial_data is not None:
        item.commercial_data = {**(item.commercial_data or {}), **payload.commercial_data}
    if payload.packing_data is not None:
        item.packing_data = {**(item.packing_data or {}), **payload.packing_data}
    if payload.customs_data is not None:
        item.customs_data = {**(item.customs_data or {}), **payload.customs_data}

    for err in item.validation_errors:
        err.resolved = True

    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.put("/{shipment_id}/header", response_model=WorkspaceOut)
def update_header(
    shipment_id: uuid.UUID,
    payload: HeaderFieldsSchema,
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    current = dict(shipment.header_fields or {})
    current.update(payload.model_dump(exclude_none=True))
    shipment.header_fields = current
    db.commit()
    return get_workspace(shipment_id, db)


@router.get("/{shipment_id}/permits", response_model=PermitSearchOut)
def search_permits(
    shipment_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    tnved_code: str | None = None,
    manufacturer: str | None = None,
    db: Session = Depends(get_db),
) -> PermitSearchOut:
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")

    article = None
    if item_id:
        item = db.get(Item, item_id)
        if item and item.shipment_id == shipment_id:
            article = item.article
            tnved_code = tnved_code or (item.customs_data or {}).get("tnved_code")
            manufacturer = manufacturer or (item.customs_data or {}).get("manufacturer")

    stmt = select(PermitDatabase)
    if tnved_code:
        stmt = stmt.where(PermitDatabase.tnved_code == tnved_code)
    if manufacturer:
        stmt = stmt.where(PermitDatabase.manufacturer.ilike(f"%{manufacturer}%"))

    rows = list(db.scalars(stmt).all())
    by_db: dict[str, list[PermitCandidate]] = {
        PermitDatabaseSource.DS_RD.value: [],
        PermitDatabaseSource.SS_RD.value: [],
        PermitDatabaseSource.SARMANT_RD.value: [],
    }
    for row in rows:
        by_db[row.database_source.value].append(
            PermitCandidate(
                id=row.id,
                database_source=row.database_source.value,
                tnved_code=row.tnved_code,
                manufacturer=row.manufacturer,
                brand=row.brand,
                doc_number=row.doc_number,
                status=row.status.value,
                valid_until=row.valid_until.isoformat() if row.valid_until else None,
            )
        )

    return PermitSearchOut(item_id=item_id, article=article, by_database=by_db)


@router.post("/{shipment_id}/export", response_model=ExportOut)
def export_shipment(shipment_id: uuid.UUID, db: Session = Depends(get_db)) -> ExportOut:
    shipment = db.scalar(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(selectinload(Shipment.items))
    )
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")

    items = [
        {
            "article": i.article,
            "model": i.model,
            "normalized_article": i.normalized_article,
            "commercial_data": i.commercial_data or {},
            "packing_data": i.packing_data or {},
            "customs_data": i.customs_data or {},
            "source_traces": i.source_traces or {},
            "invoice_subkit": (i.commercial_data or {}).get("invoice_subkit"),
        }
        for i in shipment.items
    ]

    out_dir = EXPORT_ROOT / str(shipment.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    shipment.status = ShipmentStatus.EXPORTING
    db.flush()

    if shipment.profile_type == ProfileType.BEIJING:
        path = export_beijing(items, out_dir / "beijing_export.xlsx", shipment.header_fields)
        paths = [path]
    else:
        # Prefer filling customer эталон templates when materials are present
        try:
            if materials_available():
                paths = export_18233_from_templates(
                    items,
                    out_dir,
                    header=shipment.header_fields,
                    shipment_title=shipment.title or "18233",
                )
            else:
                paths = export_18233(
                    items,
                    out_dir,
                    header=shipment.header_fields,
                    shipment_title=shipment.title or "18233",
                )
        except Exception as exc:
            # Fallback keeps export usable if template fill fails
            paths = export_18233(
                items,
                out_dir,
                header=shipment.header_fields,
                shipment_title=shipment.title or "18233",
            )
            shipment.notes = f"template_export_fallback:{exc}"

    shipment.status = ShipmentStatus.EXPORTED
    db.commit()

    # One ZIP so the browser can download everything in a single click
    safe_title = "".join(
        ch if ch.isalnum() or ch in "-_ " else "_" for ch in (shipment.title or "export")
    ).strip() or "export"
    zip_path = out_dir / f"{safe_title}_Excel.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            zf.write(path, arcname=path.name)

    names = [zip_path.name] + [p.name for p in paths]
    return ExportOut(
        files=names,
        download_base=f"/api/v1/shipments/{shipment_id}/export/download",
    )


@router.get("/{shipment_id}/export/download/{filename:path}")
def download_export(shipment_id: uuid.UUID, filename: str) -> FileResponse:
    # Accept both raw and URL-encoded Cyrillic names from the UI.
    safe_name = Path(filename).name
    path = EXPORT_ROOT / str(shipment_id) / safe_name
    if not path.exists():
        # Fallback: match by decoded name among exported files
        folder = EXPORT_ROOT / str(shipment_id)
        if folder.exists():
            for candidate in folder.iterdir():
                if candidate.name == safe_name or candidate.name.lower() == safe_name.lower():
                    path = candidate
                    break
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    suffix = path.suffix.lower()
    if suffix == ".zip":
        media = "application/zip"
    elif suffix in {".xlsx", ".xls"}:
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media = "application/octet-stream"
    return FileResponse(path, filename=path.name, media_type=media)


@router.get("/")
def list_shipments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Shipment).order_by(Shipment.created_at.desc())).all()
    return [
        {
            "id": str(s.id),
            "title": s.title,
            "profile_type": s.profile_type.value,
            "status": s.status.value,
        }
        for s in rows
    ]
