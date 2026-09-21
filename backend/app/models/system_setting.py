"""SystemSetting model (Module 21 spec section 5) - a small admin-editable
key/value store, deliberately scoped to the handful of settings that are
actually safe to change at runtime (see app/services/system_settings.py
for exactly which keys exist and why). NOT a general configuration system:
Priority values, the workflow status graph, and AI provider / repository /
knowledge base configuration all stay code- or .env-driven, for the
reasons explained where each is surfaced to the admin UI (read-only there,
never written through this table).

value_json is a JSON-encoded value (usually a list of strings, e.g. the CR
categories list) so one table can hold different setting shapes without a
column per setting.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<SystemSetting {self.key}>"
