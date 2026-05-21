import json
import os
from datetime import datetime, timezone
from threading import Lock

from config import Config

_db_lock = Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_file() -> None:
    os.makedirs(Config.RESULTS_FOLDER, exist_ok=True)
    if not os.path.exists(Config.DATABASE_FILE):
        data = {
            "simulations": [
                {
                    "id": sim_id,
                    "status": "pending",
                    "locked": False,
                    "image_path": None,
                    "stego_image_path": None,
                    "payload_percentage": None,
                    "payload_target_bytes": None,
                    "edge_threshold_low": None,
                    "edge_threshold_high": None,
                    "bit_depth": None,
                    "secret_message": "",
                    "extracted_message": "",
                    "metrics": {},
                    "graphs": {},
                    "edge_map_path": None,
                    "difference_image_path": None,
                    "edge_pixel_count": None,
                    "max_possible_word_count": None,
                    "actual_embedded_word_count": None,
                    "psnr": None,
                    "ssim": None,
                    "chi_square": None,
                    "test_results": {},
                    "embedding_time_ms": None,
                    "extraction_time_ms": None,
                    "extraction_accuracy": None,
                    "capacity_bytes": None,
                    "algorithm": "adaptive_lsb",
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                }
                for sim_id in range(1, Config.DEFAULT_SIMULATION_COUNT + 1)
            ]
        }
        with open(Config.DATABASE_FILE, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2)


def _read() -> dict:
    _ensure_file()
    with open(Config.DATABASE_FILE, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _write(data: dict) -> None:
    with open(Config.DATABASE_FILE, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)


def init_storage() -> None:
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.RESULTS_FOLDER, exist_ok=True)
    _ensure_file()


def list_simulations() -> list[dict]:
    with _db_lock:
        return _read()["simulations"]


def get_simulation(sim_id: int) -> dict | None:
    with _db_lock:
        for sim in _read()["simulations"]:
            if sim["id"] == sim_id:
                return sim
    return None


def update_simulation(sim_id: int, updates: dict) -> dict | None:
    with _db_lock:
        data = _read()
        for sim in data["simulations"]:
            if sim["id"] == sim_id:
                sim.update(updates)
                sim["updated_at"] = _utc_now()
                _write(data)
                return sim
    return None


def get_completed_simulations() -> list[dict]:
    return [s for s in list_simulations() if s.get("metrics")]


def export_results(sim_id: int) -> str | None:
    sim = get_simulation(sim_id)
    if not sim:
        return None
    export_path = os.path.join(Config.RESULTS_FOLDER, f"export_simulation_{sim_id}.json")
    with open(export_path, "w", encoding="utf-8") as fp:
        json.dump(sim, fp, indent=2)
    return export_path
