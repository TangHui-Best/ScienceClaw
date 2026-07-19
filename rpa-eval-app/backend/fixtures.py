from datetime import datetime
from decimal import Decimal
from os import getenv
from pathlib import Path
from secrets import token_urlsafe
from shutil import rmtree

from sqlalchemy.orm import Session

from auth import hash_password
from database import DOWNLOADS_DIR
from models import (
    ApprovalTask,
    Contract,
    PurchaseOrder,
    PurchaseRequest,
    PurchaseRequestItem,
    Supplier,
    User,
)


def reset_downloads_dir() -> None:
    if DOWNLOADS_DIR.exists():
        rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_fixtures(db: Session) -> None:
    def fixture_password(username: str) -> str:
        env_key = f"RPA_EVAL_{username.upper()}_PASSWORD"
        return getenv(env_key) or token_urlsafe(24)

    users = [
        User(
            username="admin",
            password_hash=hash_password(fixture_password("admin")),
            display_name="系统管理员",
            role="admin",
            department="数字化管理部",
        ),
        User(
            username="buyer",
            password_hash=hash_password(fixture_password("buyer")),
            display_name="采购专员",
            role="buyer",
            department="采购管理部",
        ),
        User(
            username="approver",
            password_hash=hash_password(fixture_password("approver")),
            display_name="合规审批经理",
            role="approver",
            department="风控合规部",
        ),
    ]
    db.add_all(users)

    suppliers = [
        Supplier(
            number="SUP-2026-001",
            name="上海智采云科技有限公司",
            status="active",
            category="RPA软件服务",
            region="华东",
            risk_level="low",
            compliance_rating="A",
            contact_person="陈晓琳",
            contact_phone="138-0000-2601",
            contact_email="chenxl@smartbuy.example",
        ),
        Supplier(
            number="SUP-2026-002",
            name="北京合规数科有限公司",
            status="pending_contact",
            category="合规审计服务",
            region="华北",
            risk_level="medium",
            compliance_rating="B",
        ),
        Supplier(
            number="SUP-2026-003",
            name="深圳云链供应链管理有限公司",
            status="active",
            category="供应链实施",
            region="华南",
            risk_level="low",
            compliance_rating="A",
            contact_person="林俊峰",
            contact_phone="139-0000-2603",
            contact_email="linjf@cloudchain.example",
        ),
    ]
    db.add_all(suppliers)
    db.flush()
    supplier_by_number = {supplier.number: supplier for supplier in suppliers}

    contracts = [
        Contract(
            number="CT-2026-RPA-001",
            title="采购流程RPA机器人年度订阅合同",
            contract_type="software_subscription",
            status="effective",
            supplier_id=supplier_by_number["SUP-2026-001"].id,
            amount=680000.0,
            owner_department="采购管理部",
            start_date="2026-01-01",
            end_date="2026-12-31",
            compliance_clause="供应商须满足数据本地化、操作留痕和年度安全审计要求。",
        ),
        Contract(
            number="CT-2026-RPA-002",
            title="第三方供应商合规筛查服务合同",
            contract_type="compliance_service",
            status="pending_review",
            supplier_id=supplier_by_number["SUP-2026-002"].id,
            amount=320000.0,
            owner_department="风控合规部",
            start_date="2026-02-01",
            end_date="2027-01-31",
            compliance_clause="服务报告需覆盖反商业贿赂、制裁名单和关联交易核查。",
        ),
        Contract(
            number="CT-2026-RPA-003",
            title="供应链主数据治理实施合同",
            contract_type="implementation",
            status="effective",
            supplier_id=supplier_by_number["SUP-2026-003"].id,
            amount=450000.0,
            owner_department="供应链运营部",
            start_date="2026-03-01",
            end_date="2026-09-30",
            compliance_clause="项目交付必须通过内控抽样复核并保留验收证据。",
        ),
    ]
    db.add_all(contracts)
    db.flush()

    contract = contracts[0]
    purchase_request = PurchaseRequest(
        number="PR-2026-RPA-001",
        title="采购流程自动化机器人许可采购",
        contract_id=contract.id,
        department="采购管理部",
        requester="王敏",
        status="approved",
        total_amount=188000.0,
        created_at=datetime(2026, 1, 8, 9, 30, 0),
    )
    db.add(purchase_request)
    db.flush()
    db.add_all(
        [
            PurchaseRequestItem(
                purchase_request_id=purchase_request.id,
                name="RPA采购审批机器人许可",
                quantity=20,
                unit_price=6800.0,
                cost_center="PROC-RPA-2026",
            ),
            PurchaseRequestItem(
                purchase_request_id=purchase_request.id,
                name="供应商门户流程配置服务",
                quantity=1,
                unit_price=52000.0,
                cost_center="PROC-RPA-2026",
            ),
        ]
    )

    purchase_order = PurchaseOrder(
        number="PO-2026-RPA-001",
        purchase_request_id=purchase_request.id,
        supplier_id=contract.supplier_id,
        status="pending_approval",
        priority="high",
        total_amount=188000.0,
        created_at=datetime(2026, 1, 9, 10, 0, 0),
    )
    db.add(purchase_order)
    db.flush()
    db.add(
        ApprovalTask(
            task_id="TASK-2026-RPA-001",
            purchase_order_id=purchase_order.id,
            assignee="approver",
            status="pending",
            updated_at=datetime(2026, 1, 9, 10, 5, 0),
        )
    )
    db.commit()


ACCEPTANCE_PROFILES = {
    "A": [
        {
            "order_no": "PO-2026-05017",
            "business_type": "设备采购",
            "supplier_name": "华东精密设备有限公司",
            "contract_no": "CT-2026-0088",
            "amount": Decimal("128600.50"),
            "currency": "CNY",
            "order_date": "2026-05-16",
        },
        {
            "order_no": "PO-2026-05031",
            "business_type": "设备采购",
            "supplier_name": "华南自动化设备有限公司",
            "contract_no": "CT-2026-0091",
            "amount": Decimal("98600.00"),
            "currency": "CNY",
            "order_date": "2026-05-20",
        },
        {
            "order_no": "PO-2026-05009",
            "business_type": "备件采购",
            "supplier_name": "西岭工业组件有限公司",
            "contract_no": "CT-2026-0079",
            "amount": Decimal("42680.25"),
            "currency": "EUR",
            "order_date": "2026-05-08",
        },
    ],
    "B": [
        {
            "order_no": "PO-2026-06011",
            "business_type": "软件采购",
            "supplier_name": "远航云服务有限公司",
            "contract_no": "CT-2026-0104",
            "amount": Decimal("38900.00"),
            "currency": "CNY",
            "order_date": "2026-06-03",
        },
        {
            "order_no": "PO-2026-06037",
            "business_type": "服务采购",
            "supplier_name": "青禾咨询有限公司",
            "contract_no": "CT-2026-0112",
            "amount": Decimal("23600.40"),
            "currency": "GBP",
            "order_date": "2026-06-06",
        },
        {
            "order_no": "PO-2026-06042",
            "business_type": "服务采购",
            "supplier_name": "北辰数字技术有限公司",
            "contract_no": "CT-2026-0116",
            "amount": Decimal("10150.75"),
            "currency": "USD",
            "order_date": "2026-06-08",
        },
    ],
}
ACCEPTANCE_TARGET_ORDER_NOS = {
    "A": "PO-2026-05017",
    "B": "PO-2026-06042",
}


def load_acceptance_profile(db: Session, profile: str) -> None:
    normalized = profile.upper()
    if normalized not in ACCEPTANCE_PROFILES:
        raise ValueError(f"Unknown acceptance profile: {profile}")

    for position, row in enumerate(ACCEPTANCE_PROFILES[normalized], start=1):
        suffix = f"{normalized}-{position}"
        supplier = Supplier(
            number=f"E2E-SUP-{suffix}",
            name=row["supplier_name"],
            status="active",
            category=row["business_type"],
            region="E2E",
            risk_level="low",
            compliance_rating="A",
        )
        db.add(supplier)
        db.flush()

        contract = Contract(
            number=row["contract_no"],
            title=f"{row['order_no']} 验收合同",
            contract_type="acceptance_e2e",
            status="effective",
            supplier_id=supplier.id,
            amount=float(row["amount"]),
            currency=row["currency"],
            owner_department="采购管理部",
            start_date=row["order_date"],
            end_date="2027-12-31",
            compliance_clause="用于首个阶段一 E2E 验收。",
        )
        db.add(contract)
        db.flush()

        request = PurchaseRequest(
            number=f"E2E-PR-{suffix}",
            title=f"{row['order_no']} 采购申请",
            contract_id=contract.id,
            department="采购管理部",
            requester="E2E",
            status="approved",
            total_amount=float(row["amount"]),
            created_at=datetime.fromisoformat(f"{row['order_date']}T08:00:00"),
        )
        db.add(request)
        db.flush()

        db.add(
            PurchaseOrder(
                number=row["order_no"],
                purchase_request_id=request.id,
                supplier_id=supplier.id,
                status="pending_acceptance",
                priority="normal",
                total_amount=float(row["amount"]),
                created_at=datetime.fromisoformat(f"{row['order_date']}T09:00:00"),
                profile=normalized,
                display_position=position,
                business_type=row["business_type"],
                currency=row["currency"],
                order_date=row["order_date"],
                acceptance_target=row["order_no"] == ACCEPTANCE_TARGET_ORDER_NOS[normalized],
            )
        )
    db.commit()


def write_placeholder_download(filename: str) -> Path:
    path = DOWNLOADS_DIR / filename
    path.touch(exist_ok=True)
    return path
