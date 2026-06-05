import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from defender_acr_dashboard.static_dashboard import create_app


app = create_app()


def _env(name: str, legacy_name: str, default: str) -> str:
    return os.getenv(name, os.getenv(legacy_name, default))


if __name__ == "__main__":
    app.run(
        host=_env("APP_HOST", "DASH_HOST", "127.0.0.1"),
        port=int(_env("APP_PORT", "DASH_PORT", "8050")),
        debug=_env("APP_DEBUG", "DASH_DEBUG", "false").lower() == "true",
    )
