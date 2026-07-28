"""SQLAdmin для Visametric: пользователи и даты поиска (общая SQLite с ботом)."""

from __future__ import annotations

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqlalchemy.ext.asyncio import create_async_engine

from admin.auth import AdminAuth
from admin.config import load_admin_config
from src.db_models import User, UserDate
from src.user_dates import _ensure_db

config = load_admin_config()
_ensure_db()

engine = create_async_engine(url=config.database_url, echo=False)

app = FastAPI(title="Visametric Admin")
authentication_backend = AdminAuth(secret_key=config.secret_key)

admin = Admin(
    app=app,
    engine=engine,
    authentication_backend=authentication_backend,
    title="Visametric",
)


class UserAdmin(ModelView, model=User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"

    column_list = [
        User.telegram_id,
        User.username,
        User.first_name,
        User.last_name,
        User.created_at,
        User.updated_at,
    ]
    column_searchable_list = [User.username, User.first_name, User.telegram_id]
    column_sortable_list = [User.telegram_id, User.created_at, User.username]
    column_default_sort = [(User.created_at, True)]
    form_columns = [
        User.telegram_id,
        User.username,
        User.first_name,
        User.last_name,
    ]


class UserDateAdmin(ModelView, model=UserDate):
    name = "Дата поиска"
    name_plural = "Даты поиска"
    icon = "fa-solid fa-calendar"

    column_list = [
        UserDate.id,
        UserDate.telegram_id,
        UserDate.date,
        UserDate.created_at,
        UserDate.user,
    ]
    column_searchable_list = [UserDate.date, UserDate.telegram_id]
    column_sortable_list = [UserDate.date, UserDate.created_at, UserDate.telegram_id]
    column_default_sort = [(UserDate.created_at, True)]
    form_columns = [UserDate.telegram_id, UserDate.date]
    form_ajax_refs = {
        "user": {
            "fields": ["username", "first_name", "telegram_id"],
            "order_by": "telegram_id",
            "limit": 50,
        }
    }


admin.add_view(UserAdmin)
admin.add_view(UserDateAdmin)


@app.get("/")
async def root():
    return {"ok": True, "admin": "/admin"}
