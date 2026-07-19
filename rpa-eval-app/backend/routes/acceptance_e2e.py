from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from os import getenv
from secrets import compare_digest, token_hex, token_urlsafe
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import verify_reset_token
from database import SessionLocal, get_db, recreate_database
from fixtures import load_acceptance_profile, load_fixtures, reset_downloads_dir
from models import AcceptanceRecord, AcceptanceTask, PurchaseOrder
from schemas import (
    AcceptanceOracleResult,
    AcceptanceRecordCreate,
    AcceptanceRecordOut,
    AcceptanceSourceOrderOut,
    AcceptanceTaskCreate,
    AcceptanceTaskCreated,
    AcceptanceTaskOut,
)


router = APIRouter()
MONEY_QUANTUM = Decimal("0.01")


def normalize_money(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def hash_task_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def source_order_out(order: PurchaseOrder) -> AcceptanceSourceOrderOut:
    return AcceptanceSourceOrderOut(
        order_no=order.number,
        business_type=order.business_type,
        supplier_name=order.supplier.name,
        contract_no=order.purchase_request.contract.number,
        amount=normalize_money(order.total_amount),
        currency=order.currency,
        order_date=order.order_date,
    )


def authorized_task(db: Session, task_id: str, token: str) -> AcceptanceTask:
    task = db.query(AcceptanceTask).filter(AcceptanceTask.task_id == task_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance task not found")
    if not compare_digest(task.task_token_hash, hash_task_token(token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid task token")
    return task


def verify_oracle_token(
    token: str | None = Header(default=None, alias="X-RPA-Eval-Oracle-Token"),
) -> None:
    expected = getenv("RPA_EVAL_ORACLE_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Oracle token is not configured",
        )
    if token is None or not compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Oracle token")


@router.post(
    "/reset/{profile}",
    dependencies=[Depends(verify_reset_token)],
)
def reset_acceptance_profile(profile: str) -> dict[str, str]:
    normalized = profile.upper()
    if normalized not in {"A", "B"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown fixture profile")
    recreate_database()
    reset_downloads_dir()
    db = SessionLocal()
    try:
        load_fixtures(db)
        load_acceptance_profile(db, normalized)
    finally:
        db.close()
    return {"status": "reset", "profile": normalized}


@router.get("/system-a/orders", response_model=list[AcceptanceSourceOrderOut])
def list_acceptance_orders(
    business_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    supplier_name: str | None = None,
    order_no: str | None = None,
    db: Session = Depends(get_db),
) -> list[AcceptanceSourceOrderOut]:
    orders = (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.profile.in_(["A", "B"]))
        .order_by(PurchaseOrder.display_position)
        .all()
    )

    def matches(order: PurchaseOrder) -> bool:
        return all(
            (
                business_type is None or order.business_type == business_type,
                date_from is None or order.order_date >= date_from,
                date_to is None or order.order_date <= date_to,
                supplier_name is None or supplier_name in order.supplier.name,
                order_no is None or order_no in order.number,
            )
        )

    # The eval result grid intentionally keeps distractor rows visible. Filters must
    # match at least one row, but never collapse the row-context challenge to one row.
    if any((business_type, date_from, date_to, supplier_name, order_no)) and not any(
        matches(order) for order in orders
    ):
        return []
    return [source_order_out(order) for order in orders]


@router.post(
    "/acceptance-tasks",
    response_model=AcceptanceTaskCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_acceptance_task(
    payload: AcceptanceTaskCreate,
    db: Session = Depends(get_db),
) -> AcceptanceTaskCreated:
    order = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.number == payload.order_no,
            PurchaseOrder.profile.in_(["A", "B"]),
        )
        .one_or_none()
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")

    task_id = f"task-{token_hex(12)}"
    token = token_urlsafe(24)
    task = AcceptanceTask(
        task_id=task_id,
        task_token_hash=hash_task_token(token),
        profile=order.profile,
        purchase_order_id=order.id,
    )
    db.add(task)
    db.commit()
    query = urlencode({"token": token})
    return AcceptanceTaskCreated(
        task_id=task_id,
        token=token,
        url=f"/system-b/acceptance/{task_id}?{query}",
        profile=order.profile,
        order_no=order.number,
    )


@router.get("/acceptance-tasks/{task_id}", response_model=AcceptanceTaskOut)
def get_acceptance_task(
    task_id: str,
    token: str = Query(min_length=1),
    db: Session = Depends(get_db),
) -> AcceptanceTaskOut:
    task = authorized_task(db, task_id, token)
    return AcceptanceTaskOut(
        task_id=task.task_id,
        profile=task.profile,
        source_order=source_order_out(task.purchase_order),
    )


@router.post(
    "/acceptance-tasks/{task_id}/records",
    response_model=AcceptanceRecordOut,
    status_code=status.HTTP_201_CREATED,
)
def create_acceptance_record(
    task_id: str,
    payload: AcceptanceRecordCreate,
    token: str = Query(min_length=1),
    db: Session = Depends(get_db),
) -> AcceptanceRecordOut:
    task = authorized_task(db, task_id, token)
    existing = (
        db.query(AcceptanceRecord)
        .filter(AcceptanceRecord.task_id == task.id)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Acceptance record already exists for this task",
        )
    record = AcceptanceRecord(
        task_id=task.id,
        order_no=payload.order_no,
        supplier_name=payload.supplier_name,
        contract_no=payload.contract_no,
        amount=normalize_money(payload.amount),
        currency=payload.currency,
        order_date=payload.order_date,
        description=payload.description,
        confirmed=payload.confirmed,
    )
    db.add(record)
    db.commit()
    return AcceptanceRecordOut(task_id=task.task_id, **payload.model_dump())


@router.get(
    "/oracle/{task_id}",
    response_model=AcceptanceOracleResult,
    dependencies=[Depends(verify_oracle_token)],
)
def evaluate_acceptance_oracle(
    task_id: str,
    db: Session = Depends(get_db),
) -> AcceptanceOracleResult:
    task = db.query(AcceptanceTask).filter(AcceptanceTask.task_id == task_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance task not found")

    records = (
        db.query(AcceptanceRecord)
        .filter(AcceptanceRecord.task_id == task.id)
        .order_by(AcceptanceRecord.id)
        .all()
    )
    targets = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.profile == task.profile,
            PurchaseOrder.acceptance_target.is_(True),
        )
        .all()
    )
    mismatches: list[str] = []
    target = targets[0] if len(targets) == 1 else None
    if target is None:
        mismatches.append("target_order")
        source = source_order_out(task.purchase_order)
    else:
        source = source_order_out(target)
        if task.purchase_order_id != target.id:
            mismatches.append("target_order")
    expected = {
        "order_no": source.order_no,
        "supplier_name": source.supplier_name,
        "contract_no": source.contract_no,
        "amount": normalize_money(source.amount),
        "currency": source.currency,
        "order_date": source.order_date,
        "description": "自动创建",
        "confirmed": True,
    }
    actual_payload: AcceptanceRecordCreate | None = None
    if len(records) != 1:
        mismatches.append("record_count")
    if records:
        record = records[0]
        actual = {
            "order_no": record.order_no,
            "supplier_name": record.supplier_name,
            "contract_no": record.contract_no,
            "amount": normalize_money(record.amount),
            "currency": record.currency,
            "order_date": record.order_date,
            "description": record.description,
            "confirmed": record.confirmed,
        }
        actual_payload = AcceptanceRecordCreate(**actual)
        mismatches.extend(
            name for name, expected_value in expected.items() if actual[name] != expected_value
        )

    return AcceptanceOracleResult(
        passed=not mismatches,
        task_id=task.task_id,
        profile=task.profile,
        target_order_no=target.number if target is not None else None,
        selected_order_no=task.purchase_order.number,
        record_count=len(records),
        mismatches=mismatches,
        actual=actual_payload,
    )
