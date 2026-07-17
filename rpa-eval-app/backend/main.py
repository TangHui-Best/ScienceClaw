from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import create_access_token, verify_reset_token
from database import SessionLocal
from database import ensure_app_dirs, recreate_database
from fixtures import FIXTURE_PROFILES, load_fixtures, reset_downloads_dir
from models import User
from routes import acceptance, approvals, auth, contracts, purchase_orders, purchase_requests, reports, suppliers
from schemas import EvalTokenRequest, EvalTokenResponse, UserOut


app = FastAPI(title="RPA Golden Evaluation Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_app_dirs()
    recreate_database()
    db: Session = SessionLocal()
    try:
        load_fixtures(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rpa-eval-backend"}


@app.post("/api/eval/reset", dependencies=[Depends(verify_reset_token)])
def reset_eval(profile: str | None = Query(default=None)) -> dict[str, str]:
    if profile is not None and profile not in FIXTURE_PROFILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown fixture profile")
    recreate_database()
    reset_downloads_dir()
    db = SessionLocal()
    try:
        load_fixtures(db, profile)
    finally:
        db.close()
    return {
        "status": "reset",
        "profile": profile or "default",
        "database": "reloaded",
        "downloads": "cleared",
    }


@app.post(
    "/api/eval/auth-token",
    response_model=EvalTokenResponse,
    dependencies=[Depends(verify_reset_token)],
)
def issue_eval_auth_token(payload: EvalTokenRequest) -> EvalTokenResponse:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == payload.username).one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval user not found")
        return EvalTokenResponse(
            access_token=create_access_token(user.username),
            user=UserOut.model_validate(user),
        )
    finally:
        db.close()


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(suppliers.router, prefix="/api/suppliers", tags=["suppliers"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(
    purchase_requests.router,
    prefix="/api/purchase-requests",
    tags=["purchase requests"],
)
app.include_router(
    purchase_orders.router,
    prefix="/api/purchase-orders",
    tags=["purchase orders"],
)
app.include_router(approvals.router, prefix="/api/approvals", tags=["approvals"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(
    acceptance.business_router,
    prefix="/api/acceptance",
    tags=["acceptance"],
)
app.include_router(
    acceptance.oracle_router,
    prefix="/api/eval/oracle",
    tags=["eval oracle"],
)
