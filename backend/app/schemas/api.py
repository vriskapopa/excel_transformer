from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import DocType, ErrorSeverity, ErrorType, ProfileType, ShipmentStatus


class HeaderFieldsSchema(BaseModel):
    buyer: str | None = None
    seller: str | None = None
    contract_no: str | None = None
    contract_date: str | None = None
    incoterms: str | None = None
    date: str | None = None
    invoice_no: str | None = None
    invoice_date: str | None = None
    manufacturer: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    delivery_date: str | None = None
    warehouse_address: str | None = None
    consignee: str | None = None
    shipper: str | None = None
    subkits: list[str] = Field(default_factory=list)


class FileOut(BaseModel):
    id: uuid.UUID
    filename: str
    doc_type: DocType | None
    ocr_confidence: float | None

    model_config = {"from_attributes": True}


class ValidationErrorOut(BaseModel):
    id: uuid.UUID | None = None
    field_name: str
    error_type: ErrorType | str
    severity: ErrorSeverity | str
    details: dict[str, Any] | None = None
    message: str | None = None
    resolved: bool = False


class ItemOut(BaseModel):
    id: uuid.UUID
    article: str | None
    model: str | None
    normalized_article: str
    commercial_data: dict[str, Any]
    packing_data: dict[str, Any]
    customs_data: dict[str, Any]
    source_traces: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[ValidationErrorOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ItemUpdate(BaseModel):
    article: str | None = None
    model: str | None = None
    commercial_data: dict[str, Any] | None = None
    packing_data: dict[str, Any] | None = None
    customs_data: dict[str, Any] | None = None


class ShipmentCreateResponse(BaseModel):
    id: uuid.UUID
    title: str
    profile_type: ProfileType
    status: ShipmentStatus
    files: list[FileOut]
    item_count: int
    warning_count: int


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    title: str
    profile_type: ProfileType
    status: ShipmentStatus
    header_fields: dict[str, Any]
    files: list[FileOut]
    items: list[ItemOut]
    created_at: datetime | None = None


class PermitCandidate(BaseModel):
    id: uuid.UUID
    database_source: str
    tnved_code: str
    manufacturer: str | None
    brand: str | None
    doc_number: str
    status: str
    valid_until: str | None = None


class PermitSearchOut(BaseModel):
    item_id: uuid.UUID | None = None
    article: str | None = None
    by_database: dict[str, list[PermitCandidate]]


class ExportOut(BaseModel):
    files: list[str]
    download_base: str
