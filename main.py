import os
import random
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import (
    Organization, UserRole,
    Patient, TestOrder, Sample, ResultEntry, ValidationRecord, TATRecord,
    Product, Requisition, RequisitionItem, PurchaseOrder,
    Shipment, ShipmentLocation, ReturnRequest,
    InventoryItem, ForecastRequest, ForecastResponse,
    Invoice, InvoiceItem, Payment,
    ComplianceDoc, ChatMessage,
)

app = FastAPI(title="Synapsis - LIMS & Supply Chain API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Synapsis API is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()[:20]
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ------------- Schema Introspection -------------
@app.get("/schema")
def get_schema():
    # Expose Pydantic model JSON schemas for viewer/tools
    from pydantic import BaseModel as _BM
    import schemas as s

    model_map = {}
    for name in dir(s):
        obj = getattr(s, name)
        if isinstance(obj, type) and issubclass(obj, _BM) and obj is not _BM:
            try:
                model_map[name] = obj.model_json_schema()
            except Exception:
                pass
    return {"models": model_map}


# ------------- RBAC (Mock) -------------
class LoginRequest(BaseModel):
    email: str
    role: str

@app.post("/auth/mock-login")
def mock_login(payload: LoginRequest):
    role = payload.role.lower()
    permissions = {
        "admin": ["all"],
        "lab_manager": ["lims", "inventory", "tat", "reports"],
        "pathologist": ["validation", "reporting"],
        "technician": ["worksheets", "entry"],
        "procurement_officer": ["catalog", "requisition", "po"],
        "finance": ["ap", "payments", "invoices"],
    }.get(role, [])
    return {"user": payload.email, "role": role, "permissions": permissions}


# ------------- Dashboard -------------
@app.get("/dashboard/summary")
def dashboard_summary():
    # Light aggregation/simulated KPIs + charts
    reports_to_validate = db["resultentry"].count_documents({"abnormal_flag": {"$in": ["H", "L", "CRIT"]}}) if db else 0
    pending_reqs = db["requisition"].count_documents({"status": "pending"}) if db else 0
    low_stock = db["inventoryitem"].count_documents({"qty": {"$lt": 10}}) if db else 0
    nabl_tasks = db["compliancedoc"].count_documents({"std": "NABL", "status": {"$ne": "complete"}}) if db else 0

    # Simulated 12-month P&L and Spend
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    pnl = []
    spend = []
    base_rev = 120000
    base_cost = 70000
    for i, m in enumerate(months, start=1):
        revenue = base_rev + random.randint(-10000, 15000)
        cost = base_cost + random.randint(-8000, 12000)
        pnl.append({"month": m, "revenue": revenue, "cost": cost, "profit": revenue - cost})
        spend.append({"month": m, "reagents": random.randint(15000, 30000), "consumables": random.randint(5000, 15000), "logistics": random.randint(3000, 10000)})

    return {
        "cards": {
            "reports_to_validate": reports_to_validate,
            "pending_requisitions": pending_reqs,
            "low_stock": low_stock,
            "nabl_compliance_pending": nabl_tasks,
        },
        "pnl": pnl,
        "spend": spend,
    }


# ------------- LIMS -------------
@app.post("/lims/sample/receive")
def receive_sample(sample: Sample):
    sample.received_at = datetime.now(timezone.utc)
    sample.status = "received" if not sample.rejection_reason else "rejected"
    sid = create_document("sample", sample)
    return {"id": sid, "status": sample.status}

class RejectRequest(BaseModel):
    barcode: str
    reason: str

@app.post("/lims/sample/reject")
def reject_sample(req: RejectRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    res = db["sample"].update_one({"barcode": req.barcode}, {"$set": {"status": "rejected", "rejection_reason": req.reason, "updated_at": datetime.now(timezone.utc)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"barcode": req.barcode, "status": "rejected"}

@app.get("/lims/worksheets")
def worksheets(department: Optional[str] = Query(None)):
    if db is None:
        return {"items": []}
    q: Dict[str, Any] = {}
    if department:
        q["ordered_tests.department"] = department
    q["status"] = {"$in": ["received", "in_progress"]}
    items = list(db["sample"].find(q, {"_id": 0}))
    return {"items": items}

@app.post("/lims/result")
def add_result(entry: ResultEntry):
    # derive abnormal flag
    flag = None
    if entry.ref_low is not None and entry.value < entry.ref_low:
        flag = "L"
    if entry.ref_high is not None and entry.value > entry.ref_high:
        flag = "H"
    if flag is not None:
        entry.abnormal_flag = flag
    entry.entered_at = datetime.now(timezone.utc)
    rid = create_document("resultentry", entry)
    # mark sample in_progress
    if db is not None:
        db["sample"].update_one({"barcode": entry.barcode}, {"$set": {"status": "in_progress", "updated_at": datetime.now(timezone.utc)}})
    return {"id": rid, "flag": entry.abnormal_flag}

@app.get("/lims/validation-queue")
def validation_queue():
    if db is None:
        return {"items": []}
    items = list(db["resultentry"].find({"abnormal_flag": {"$in": ["H", "L", "CRIT"]}}, {"_id": 0}).limit(200))
    return {"items": items}

class ValidateRequest(BaseModel):
    barcode: str
    reviewed_by: str
    comments: Optional[str] = None

@app.post("/lims/validate")
def validate_results(req: ValidateRequest):
    record = ValidationRecord(
        barcode=req.barcode,
        reviewed_by=req.reviewed_by,
        comments=req.comments,
        validated_at=datetime.now(timezone.utc),
        status="validated",
    )
    vid = create_document("validationrecord", record)
    if db is not None:
        db["sample"].update_one({"barcode": req.barcode}, {"$set": {"status": "validated", "updated_at": datetime.now(timezone.utc)}})
    return {"id": vid, "status": "validated"}

@app.get("/lims/tat")
def tat_overview():
    if db is None:
        return {"avg_mins": 0, "on_time_pct": 0}
    records = list(db["validationrecord"].find({}, {"_id": 0, "barcode": 1, "validated_at": 1}))
    on_time = 0
    total = 0
    deltas = []
    for r in records:
        s = db["sample"].find_one({"barcode": r["barcode"]}, {"received_at": 1, "ordered_tests": 1, "_id": 0})
        if not s or not s.get("received_at"):
            continue
        # assume target 240 mins default
        target = 240
        mins = (r["validated_at"] - s["received_at"]).total_seconds() / 60.0
        deltas.append(mins)
        total += 1
        if mins <= target:
            on_time += 1
    avg = sum(deltas) / len(deltas) if deltas else 0
    pct = round(100.0 * on_time / total, 2) if total else 0
    return {"avg_mins": round(avg, 1), "on_time_pct": pct}


# ------------- Procurement & Catalog -------------
@app.get("/catalog")
def get_catalog():
    items = list(db["product"].find({}, {"_id": 0})) if db else []
    if not items:
        # seed a few items
        seed = [
            Product(sku="EQ-BC-200", title="Biochemistry Analyzer", vendor="Acme Med",
                    specifications="200 tests/hr", cold_chain=False, hsn="9018", gst_rate=12.0, category="equipment", price=450000.0),
            Product(sku="RG-GLU-100", title="Glucose Reagent", vendor="ChemLabs",
                    specifications="Kit 4x100ml", cold_chain=True, hsn="3822", gst_rate=12.0, category="reagent", price=3200.0),
            Product(sku="CS-VAC-2ML", title="2ml Vacutainer", vendor="HealthSup",
                    specifications="Pack of 100", cold_chain=False, hsn="3926", gst_rate=18.0, category="consumable", price=600.0),
        ]
        for p in seed:
            try:
                create_document("product", p)
            except Exception:
                pass
        items = [p.model_dump() for p in seed]
    return {"items": items}

@app.post("/requisitions")
def create_requisition(req: Requisition):
    rid = create_document("requisition", req)
    return {"id": rid, "status": req.status}

@app.get("/requisitions")
def list_requisitions(status: Optional[str] = None):
    q = {"status": status} if status else {}
    items = list(db["requisition"].find(q, {"_id": 0})) if db else []
    return {"items": items}

class ReqAction(BaseModel):
    req_id: str
    approver: str
    action: str  # approve/reject
    remarks: Optional[str] = None

@app.post("/requisitions/action")
def req_action(act: ReqAction):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    new_status = "approved" if act.action == "approve" else "rejected"
    res = db["requisition"].update_one({"_id": {"$exists": True}, "req_id": act.req_id}, {"$set": {"status": new_status, "approver": act.approver, "remarks": act.remarks, "updated_at": datetime.now(timezone.utc)}})
    # If req_id is not stored, update by any with status pending - simple demo approach
    if res.matched_count == 0:
        db["requisition"].update_one({"status": "pending"}, {"$set": {"status": new_status, "approver": act.approver, "remarks": act.remarks, "updated_at": datetime.now(timezone.utc)}})
    return {"status": new_status}

class POCreate(BaseModel):
    req_id: str
    po_number: str
    vendor: str

@app.post("/purchase-orders")
def create_po(po: POCreate):
    # Fetch req items
    req = db["requisition"].find_one({"_id": {"$exists": True}, "req_id": po.req_id}) or db["requisition"].find_one({"status": {"$in": ["approved", "pending"]}})
    if not req:
        raise HTTPException(status_code=404, detail="Requisition not found")
    po_doc = PurchaseOrder(req_id=po.req_id, po_number=po.po_number, vendor=po.vendor, items=req.get("items", []), status="pending_finance")
    pid = create_document("purchaseorder", po_doc)
    db["requisition"].update_one({"_id": req["_id"]}, {"$set": {"status": "po_created", "updated_at": datetime.now(timezone.utc)}})
    return {"id": pid, "po_number": po.po_number}


# ------------- Logistics & Tracking -------------
@app.post("/shipments/start")
def start_shipment(po_number: str):
    s = Shipment(po_number=po_number, status="dispatched", last_location=ShipmentLocation(lat=28.6139, lng=77.2090, temp_c=4.0, timestamp=datetime.now(timezone.utc)))
    sid = create_document("shipment", s)
    return {"id": sid, "status": s.status}

@app.get("/shipments/{po_number}/track")
def track_shipment(po_number: str):
    # Simulate GPS drift + cold chain monitoring
    base = db["shipment"].find_one({"po_number": po_number}) if db else None
    lat, lng, temp = 28.6139, 77.2090, 4.0
    if base and base.get("last_location"):
        lat = base["last_location"].get("lat", lat)
        lng = base["last_location"].get("lng", lng)
        temp = base["last_location"].get("temp_c", temp)
    lat += random.uniform(-0.02, 0.02)
    lng += random.uniform(-0.02, 0.02)
    temp += random.uniform(-0.5, 0.7)
    location = {"lat": round(lat, 5), "lng": round(lng, 5), "temp_c": round(temp, 2), "timestamp": datetime.now(timezone.utc)}
    alert = None
    if temp < 2.0 or temp > 8.0:
        alert = "Temperature excursion detected"
    return {"po_number": po_number, "location": location, "alert": alert}


# ------------- Inventory -------------
@app.get("/inventory/low-stock")
def low_stock():
    items = list(db["inventoryitem"].find({"qty": {"$lt": 10}}, {"_id": 0})) if db else []
    return {"items": items}

class ConsumeRequest(BaseModel):
    sku: str
    qty: int

@app.post("/inventory/consume")
def consume(req: ConsumeRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["inventoryitem"].update_one({"sku": req.sku}, {"$inc": {"qty": -abs(req.qty)}, "$set": {"updated_at": datetime.now(timezone.utc)}}, upsert=True)
    item = db["inventoryitem"].find_one({"sku": req.sku}, {"_id": 0})
    return {"item": item}

@app.post("/inventory/forecast")
def forecast(req: ForecastRequest) -> ForecastResponse:
    # Simple moving average + safety stock (1 stddev)
    data = req.last_30d_consumption or [random.randint(0, 5) for _ in range(30)]
    avg = sum(data) / len(data)
    variance = sum((x - avg) ** 2 for x in data) / len(data)
    stddev = math.sqrt(variance)
    safety = max(2, int(round(stddev)))
    lead_time_days = 7
    reorder_point = int(round(avg * lead_time_days + safety))
    reorder_qty = int(max(5, round(avg * 14)))
    return ForecastResponse(sku=req.sku, recommended_reorder_qty=reorder_qty, safety_stock=safety, reorder_point=reorder_point)


# ------------- Finance -------------
@app.post("/invoices")
def create_invoice(inv: Invoice):
    iid = create_document("invoice", inv)
    return {"id": iid}

@app.post("/payments")
def add_payment(p: Payment):
    pid = create_document("payment", p)
    # update invoice status (simplified)
    if db is not None:
        inv = db["invoice"].find_one({"invoice_no": p.invoice_no})
        if inv:
            paid = sum(x.get("amount", 0) for x in db["payment"].find({"invoice_no": p.invoice_no}))
            total = 0.0
            for it in inv.get("items", []):
                total += it.get("qty", 0) * it.get("price", 0)
                total += (it.get("qty", 0) * it.get("price", 0)) * (it.get("gst_rate", 0) / 100.0)
            status = "paid" if paid >= total else ("partial" if paid > 0 else "unpaid")
            db["invoice"].update_one({"_id": inv["_id"]}, {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}})
    return {"id": pid}

@app.get("/finance/kpis")
def finance_kpis():
    inv_count = db["invoice"].count_documents({}) if db else 0
    overdue = db["invoice"].count_documents({"status": "overdue"}) if db else 0
    payables = inv_count - overdue
    credit_limit = 1000000
    used_credit = random.randint(200000, 600000)
    return {"invoices": inv_count, "overdue": overdue, "payables": payables, "credit_limit": credit_limit, "used_credit": used_credit}


# ------------- Compliance -------------
@app.get("/compliance")
def compliance_list():
    items = list(db["compliancedoc"].find({}, {"_id": 0})) if db else []
    if not items:
        seed = [
            ComplianceDoc(title="Method validation records", std="NABL", status="in_progress", owner="qa@lab.com"),
            ComplianceDoc(title="Equipment calibration schedule", std="ISO15189", status="pending", owner="biomed@lab.com"),
        ]
        for d in seed:
            try:
                create_document("compliancedoc", d)
            except Exception:
                pass
        items = [d.model_dump() for d in seed]
    return {"items": items}


# ------------- AI Assistant (Simulated Gemini) -------------
@app.post("/ai/ask")
def ai_ask(msg: ChatMessage):
    # Simulate helpful response grounded on requested module
    hints = {
        "inventory": "Current low stock items can be reviewed in Inventory > Alerts. Consider reordering high ABC-class reagents first.",
        "finance": "Net 30 invoices due this week total INR 2.4L. Paying early could save ~2% in discounts.",
        "lims": "3 samples have abnormal results awaiting validation in Biochemistry.",
        "procurement": "Two requisitions are pending approval. Recommended vendor for glucose reagent is ChemLabs.",
    }
    key = next((k for k in hints if k in msg.content.lower()), "lims")
    answer = f"Insight: {hints[key]}\nYou asked: {msg.content[:300]}"
    # store conversation
    try:
        create_document("chatmessage", msg)
        create_document("chatmessage", ChatMessage(role="assistant", content=answer, context="auto"))
    except Exception:
        pass
    return {"answer": answer}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
