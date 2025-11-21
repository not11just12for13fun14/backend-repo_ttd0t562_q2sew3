"""
Synapsis LIMS & Supply Chain - Database Schemas

Each Pydantic model below maps to a MongoDB collection using the lowercase
class name as the collection name (e.g., Sample -> "sample").

These schemas cover core modules: RBAC, LIMS, Procurement, Orders, Inventory,
Finance, Logistics, Compliance, and AI Assistant logs.
"""
from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# ------------ RBAC & Orgs ------------
class Organization(BaseModel):
    name: str
    org_type: Literal[
        "standalone_lab", "corporate_chain", "hospital_lab", "vendor"
    ]
    address: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool = True

class UserRole(BaseModel):
    user_id: str
    role: Literal[
        "admin",
        "lab_manager",
        "pathologist",
        "technician",
        "procurement_officer",
        "finance",
    ]
    organization_id: Optional[str] = None

# ------------ LIMS ------------
class Patient(BaseModel):
    first_name: str
    last_name: str
    gender: Literal["male", "female", "other"]
    dob: Optional[str] = None

class TestOrder(BaseModel):
    code: str
    name: str
    department: Literal["hematology", "biochemistry", "microbiology", "immunology"]
    target_tat_mins: int = 240

class Sample(BaseModel):
    barcode: str
    patient: Patient
    ordered_tests: List[TestOrder]
    status: Literal["received", "rejected", "in_progress", "validated"] = "received"
    rejection_reason: Optional[str] = None
    received_at: Optional[datetime] = None

class ResultEntry(BaseModel):
    barcode: str
    test_code: str
    parameter: str
    value: float
    unit: str
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    abnormal_flag: Optional[Literal["L", "H", "CRIT"]] = None
    entered_by: Optional[str] = None
    entered_at: Optional[datetime] = None

class ValidationRecord(BaseModel):
    barcode: str
    reviewed_by: str
    comments: Optional[str] = None
    validated_at: datetime
    status: Literal["validated", "query"] = "validated"

class TATRecord(BaseModel):
    barcode: str
    test_code: str
    received_at: datetime
    validated_at: Optional[datetime] = None

# ------------ Procurement & Catalog ------------
class Product(BaseModel):
    sku: str
    title: str
    vendor: Optional[str] = None
    specifications: Optional[str] = None
    cold_chain: bool = False
    hsn: Optional[str] = None
    gst_rate: float = 0.0
    category: Literal["equipment", "reagent", "consumable"] = "reagent"
    price: float = 0.0

class RequisitionItem(BaseModel):
    sku: str
    qty: int
    needed_by: Optional[str] = None

class Requisition(BaseModel):
    created_by: str
    items: List[RequisitionItem]
    status: Literal["pending", "approved", "rejected", "po_created"] = "pending"
    approver: Optional[str] = None
    remarks: Optional[str] = None

class PurchaseOrder(BaseModel):
    req_id: str
    po_number: str
    vendor: str
    items: List[RequisitionItem]
    status: Literal["pending_finance", "dispatched", "in_transit", "delivered"] = "pending_finance"

# ------------ Orders, Logistics & Returns ------------
class ShipmentLocation(BaseModel):
    lat: float
    lng: float
    temp_c: Optional[float] = None
    timestamp: Optional[datetime] = None

class Shipment(BaseModel):
    po_number: str
    status: Literal["pending_finance", "dispatched", "in_transit", "delivered"]
    last_location: Optional[ShipmentLocation] = None

class ReturnRequest(BaseModel):
    po_number: str
    reason: Literal["damaged", "expired", "other"]
    status: Literal["requested", "approved", "rejected", "completed"] = "requested"

# ------------ Inventory ------------
class InventoryItem(BaseModel):
    sku: str
    batch: str
    qty: int
    unit: str
    expiry: Optional[str] = None
    location: Optional[str] = None

class ForecastRequest(BaseModel):
    sku: str
    last_30d_consumption: List[int] = Field(default_factory=list)

class ForecastResponse(BaseModel):
    sku: str
    recommended_reorder_qty: int
    safety_stock: int
    reorder_point: int

# ------------ Finance ------------
class InvoiceItem(BaseModel):
    sku: str
    qty: int
    price: float
    gst_rate: float

class Invoice(BaseModel):
    invoice_no: str
    po_number: str
    items: List[InvoiceItem]
    due_date: Optional[str] = None
    payment_terms: Literal["net30", "net60", "bnpl"] = "net30"
    status: Literal["unpaid", "partial", "paid", "overdue"] = "unpaid"

class Payment(BaseModel):
    invoice_no: str
    amount: float
    method: Literal["standard", "bnpl"] = "standard"

# ------------ Compliance ------------
class ComplianceDoc(BaseModel):
    title: str
    std: Literal["NABL", "ISO15189"]
    status: Literal["pending", "in_progress", "complete"] = "pending"
    owner: Optional[str] = None

# ------------ Assistant ------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    context: Optional[str] = None
