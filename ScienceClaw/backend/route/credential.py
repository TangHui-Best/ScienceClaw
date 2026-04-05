"""Credential management API."""
import logging
from fastapi import APIRouter, Depends, HTTPException

from backend.user.dependencies import get_current_user, User
from backend.credential.models import CredentialCreate, CredentialUpdate
from backend.credential.vault import get_vault

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("")
async def list_credentials(current_user: User = Depends(get_current_user)):
    vault = get_vault()
    creds = await vault.list_for_user(str(current_user.id))
    return {"status": "success", "credentials": [c.model_dump() for c in creds]}


@router.post("")
async def create_credential(
    body: CredentialCreate,
    current_user: User = Depends(get_current_user),
):
    vault = get_vault()
    cred = await vault.create(str(current_user.id), body)
    return {"status": "success", "credential": cred.model_dump()}


@router.put("/{cred_id}")
async def update_credential(
    cred_id: str,
    body: CredentialUpdate,
    current_user: User = Depends(get_current_user),
):
    vault = get_vault()
    cred = await vault.update(str(current_user.id), cred_id, body)
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "success", "credential": cred.model_dump()}


@router.delete("/{cred_id}")
async def delete_credential(
    cred_id: str,
    current_user: User = Depends(get_current_user),
):
    vault = get_vault()
    deleted = await vault.delete(str(current_user.id), cred_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "success"}
