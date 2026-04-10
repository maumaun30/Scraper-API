from sqlalchemy import String, Text, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from datetime import datetime
from typing import Optional


class ScrapedItem(Base):
    __tablename__ = "scraped_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[Optional[str]] = mapped_column(String(500))
    content: Mapped[Optional[str]] = mapped_column(Text)
    excerpt: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)

    # All scraped fields as flexible JSON
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)

    scraped_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
