from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 50


class Ok(BaseModel):
    ok: bool = True
    message: str | None = None
    data: Any | None = None


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)
