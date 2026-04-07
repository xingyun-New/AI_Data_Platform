"""Prompt file management — list / read / update prompt .txt files."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.config import settings

router = APIRouter()


class PromptFile(BaseModel):
    filename: str
    content: str


class PromptUpdate(BaseModel):
    content: str


def _prompts_dir() -> Path:
    return Path(settings.prompts_dir)


@router.get("", response_model=list[PromptFile])
def list_prompts(_user: dict = Depends(get_current_user)):
    d = _prompts_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("*.txt"))
    return [
        PromptFile(filename=f.name, content=f.read_text(encoding="utf-8"))
        for f in files
    ]


@router.get("/{filename}", response_model=PromptFile)
def get_prompt(filename: str, _user: dict = Depends(get_current_user)):
    path = (_prompts_dir() / filename).resolve()
    if not path.is_relative_to(_prompts_dir().resolve()):
        raise HTTPException(status_code=403, detail="非法的文件路径")
    if not path.exists() or not path.suffix == ".txt":
        raise HTTPException(status_code=404, detail="提示词文件不存在")
    return PromptFile(filename=filename, content=path.read_text(encoding="utf-8"))


@router.put("/{filename}", response_model=PromptFile)
def update_prompt(filename: str, body: PromptUpdate, _user: dict = Depends(get_current_user)):
    path = (_prompts_dir() / filename).resolve()
    if not path.is_relative_to(_prompts_dir().resolve()):
        raise HTTPException(status_code=403, detail="非法的文件路径")
    if not path.suffix == ".txt":
        raise HTTPException(status_code=400, detail="只允许编辑 .txt 文件")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    return PromptFile(filename=filename, content=body.content)
