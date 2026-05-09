import os

from app import app


def _debug_enabled() -> bool:
    is_production = os.environ.get("FLASK_ENV", "").lower() == "production"
    return os.environ.get("FLASK_DEBUG") == "1" and not is_production


if __name__ == "__main__":
    app.run(
        debug=_debug_enabled(),
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
