"""SQLAlchemy-модели для общей БД бота (data/users.sqlite)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)

    dates: Mapped[list["UserDate"]] = relationship(
        "UserDate",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __str__(self) -> str:
        name = self.first_name or self.username or str(self.telegram_id)
        if self.username:
            return f"{name} (@{self.username})"
        return name


class UserDate(Base):
    __tablename__ = "user_dates"
    __table_args__ = (
        UniqueConstraint("telegram_id", "date", name="uq_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="dates")

    def __str__(self) -> str:
        return f"{self.telegram_id}: {self.date}"
