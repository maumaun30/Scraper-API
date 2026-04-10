from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.scraped_item import ScrapedItem
from app.models.user import User

router = APIRouter(prefix="/items", tags=["items"])


class ScrapedItemOut(BaseModel):
    id: int
    title: Optional[str]
    excerpt: Optional[str]
    source_url: str
    raw_data: dict[str, Any]
    scraped_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaginatedItems(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ScrapedItemOut]


@router.get("/", response_model=PaginatedItems)
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(ScrapedItem)

    if search:
        query = query.where(
            ScrapedItem.title.ilike(f"%{search}%")
            | ScrapedItem.excerpt.ilike(f"%{search}%")
        )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.order_by(ScrapedItem.scraped_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    items = result.scalars().all()

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/{item_id}", response_model=ScrapedItemOut)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(ScrapedItem).where(ScrapedItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(ScrapedItem).where(ScrapedItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
