import os


class Config:
    _env = os.environ.get("FLASK_ENV", "").lower()
    _secret = os.environ.get("SECRET_KEY")
    if _env == "production" and not _secret:
        raise RuntimeError("SECRET_KEY must be set when FLASK_ENV=production")
    SECRET_KEY = _secret or "xect-dev-key"
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    RESULTS_FOLDER = os.path.join(BASE_DIR, "results")
    DATABASE_FILE = os.path.join(RESULTS_FOLDER, "simulations.json")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
    ALLOWED_FORMATS = {"PNG", "BMP"}
    MIN_DIMENSION = 64
    MAX_DIMENSION = 4096
    DEFAULT_SIMULATION_COUNT = int(os.environ.get("SIMULATION_COUNT", 6))
    PAYLOAD_OPTIONS_KB = [1, 25, 50, 100]
