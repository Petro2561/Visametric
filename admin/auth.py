from fastapi import Request
from sqladmin.authentication import AuthenticationBackend

from admin.config import load_admin_config

config = load_admin_config()


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        if username == config.login and password == config.password:
            request.session.update({"token": config.secret_key})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        return bool(token) and token == config.secret_key
