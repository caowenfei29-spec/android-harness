"""User profile config API."""
from fastapi import APIRouter
from pydantic import BaseModel

from .. import db

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileReq(BaseModel):
    language: str = "zh"
    default_browser_package: str = "mark.via"
    app_aliases: dict | None = None
    messaging_style: str = "paste_first_for_short_reply"
    notes: str = ""


@router.get("")
def get_profile():
    return db.get_profile()


@router.put("")
def put_profile(req: ProfileReq):
    data = req.model_dump()
    db.set_profile(data)
    return data
