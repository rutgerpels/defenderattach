import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from defender_acr_dashboard.static_dashboard import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("DASH_HOST", "127.0.0.1"),
        port=int(os.getenv("DASH_PORT", "8050")),
        debug=os.getenv("DASH_DEBUG", "false").lower() == "true",
    )
