from __future__ import annotations

import uvicorn

from .config import config


def main() -> None:
    uvicorn.run("memora.app:app", host=config.host, port=config.port, reload=False)


if __name__ == "__main__":
    main()
