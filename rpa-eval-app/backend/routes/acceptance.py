from hmac import compare_digest
from secrets import token_urlsafe
from uuid import uuid4
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import get_current_user, verify_reset_token
from database import get_db
from models import AcceptanceRecord, AcceptanceSourceOrder, AcceptanceTask, User
from schemas import (
    AcceptanceOrderOut,
    AcceptanceRecordCreate,
    AcceptanceRecordOut,
    AcceptanceTaskCreated,
    AcceptanceTaskOut,
)


business_router = APIRouter(dependencies=[Depends(get_current_user)])
oracle_router = APIRouter(dependencies=[Depends(verify_reset_token)])


def get_valid_task(db: Session, task_id: str, token: str) -> AcceptanceTask:
    task = db.query(AcceptanceTask).filter(AcceptanceTask.task_id == task_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance task not found")
    if not compare_digest(task.token, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid acceptance task token")
    return task


@business_router.get("/orders", response_model=list[AcceptanceOrderOut])
def list_acceptance_orders(
    business_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_name: str | None = None,
    order_no: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AcceptanceOrderOut]:
    query = db.query(AcceptanceSourceOrder)
    if business_type:
        query = query.filter(AcceptanceSourceOrder.business_type == business_type)
    if date_from:
        query = query.filter(AcceptanceSourceOrder.order_date >= date_from)
    if date_to:
        query = query.filter(AcceptanceSourceOrder.order_date <= date_to)
    if supplier_name:
        query = query.filter(AcceptanceSourceOrder.supplier_name.contains(supplier_name))
    if order_no:
        query = query.filter(AcceptanceSourceOrder.order_no.contains(order_no))
    return query.order_by(AcceptanceSourceOrder.fixture_position).all()


@business_router.post(
    "/orders/{order_no}/tasks",
    response_model=AcceptanceTaskCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_acceptance_task(
    order_no: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AcceptanceTaskCreated:
    order = (
        db.query(AcceptanceSourceOrder)
        .filter(AcceptanceSourceOrder.order_no == order_no)
        .one_or_none()
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source order not found")

    task_id = f"task-{uuid4().hex}"
    token = token_urlsafe(32)
    db.add(AcceptanceTask(task_id=task_id, token=token, source_order_id=order.id))
    db.commit()
    return AcceptanceTaskCreated(
        task_id=task_id,
        token=token,
        url=f"/system-b/acceptance/{task_id}?token={token}",
    )


@business_router.get("/tasks/{task_id}", response_model=AcceptanceTaskOut)
def get_acceptance_task(
    task_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AcceptanceTaskOut:
    task = get_valid_task(db, task_id, token)
    return AcceptanceTaskOut(
        task_id=task.task_id,
        non_business_frame_count=1 if task.source_order.profile == "case_a" else 2,
        order=AcceptanceOrderOut.model_validate(task.source_order),
    )


@business_router.post(
    "/tasks/{task_id}/records",
    response_model=AcceptanceRecordOut,
    status_code=status.HTTP_201_CREATED,
)
def create_acceptance_record(
    task_id: str,
    payload: AcceptanceRecordCreate,
    token: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AcceptanceRecord:
    task = get_valid_task(db, task_id, token)
    if task.record is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Acceptance task already saved")
    record = AcceptanceRecord(task_id=task.task_id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@oracle_router.get("/acceptance", response_model=AcceptanceRecordOut)
def get_acceptance_oracle(
    task_id: str,
    db: Session = Depends(get_db),
) -> AcceptanceRecord:
    record = (
        db.query(AcceptanceRecord)
        .filter(AcceptanceRecord.task_id == task_id)
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acceptance record not found")
    return record
