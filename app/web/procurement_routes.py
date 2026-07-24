"""Procurement documents — the PO the user downloads and sends to the vendor.
(Email delivery arrives at launch via procurement.service.deliver_po.)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.procurement import documents as pdocs
from .deps import require_scope

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/po/{po_id}/document")
def po_doc(po_id: int, user=Depends(require_scope("procurement", 1)),
           session: Session = Depends(get_session)):
    try:
        filename, data = pdocs.build_po_xlsx(session, po_id)
    except ValueError:
        raise HTTPException(status_code=404)
    return StreamingResponse(iter([data]), media_type=_XLSX,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
