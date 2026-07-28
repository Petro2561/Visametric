"""Запуск админки: python -m admin"""

from __future__ import annotations

import uvicorn

from admin.config import load_admin_config


def main() -> None:
    cfg = load_admin_config()
    uvicorn.run(
        "admin.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
