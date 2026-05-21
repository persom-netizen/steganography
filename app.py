import os
import json
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory

from backend.adaptive_lsb_engine import (
    LSBError,
    analyze_image_capacity,
    encode_message_in_image,
    decode_message_from_image,
    save_difference_image,
    save_edge_map_image,
    validate_image,
)
from backend.database import get_simulation, init_storage, update_simulation
from backend.metrics import chi_square_lsb, compute_metrics
from config import Config


def _coerce_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_simulation_id(value) -> int:
    simulation_id = _coerce_int(value, 1)
    return simulation_id if simulation_id > 0 else 1


def _prepare_thresholds(data: dict) -> tuple[float, float, int]:
    threshold_low = _coerce_float(data.get("edge_threshold_low"), 0.30)
    threshold_high = _coerce_float(data.get("edge_threshold_high"), 0.70)
    bit_depth = _coerce_int(data.get("bit_depth"), 3)
    return threshold_low, threshold_high, bit_depth


def _simulation_paths(simulation_id: int, base_dir: str) -> dict:
    return {
        "edge_map_path": os.path.join(base_dir, f"edge_map_sim_{simulation_id}.png"),
        "stego_image_path": os.path.join(base_dir, f"stego_sim_{simulation_id}.png"),
        "difference_image_path": os.path.join(base_dir, f"difference_sim_{simulation_id}.png"),
    }


def _payload_limit_bytes_from_dimensions(dimensions: list[int] | tuple[int, int], payload_percentage: int) -> int:
    if not dimensions or len(dimensions) < 2:
        return 0
    total_pixels = int(dimensions[0]) * int(dimensions[1])
    if total_pixels <= 0 or payload_percentage <= 0:
        return 0
    bit_limit = int((total_pixels * int(payload_percentage)) / 100)
    return max(1, bit_limit // 8)


def _parse_payload_percentages(raw_value: str | None) -> list[int]:
    default_values = [10, 25, 50, 75, 100]
    if not raw_value:
        return default_values
    values: list[int] = []
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            number = int(item)
        except ValueError:
            continue
        if 1 <= number <= 100:
            values.append(number)
    return values or default_values


def _recommendation_score(psnr_value, ssim_value, chi_square_value) -> float:
    psnr_score = float(psnr_value) if isinstance(psnr_value, (int, float)) else 0.0
    ssim_score = float(ssim_value) if isinstance(ssim_value, (int, float)) else 0.0
    chi_square_score = float(chi_square_value) if isinstance(chi_square_value, (int, float)) else 0.0
    return psnr_score + (ssim_score * 100.0) - (chi_square_score / 1000000.0)


def _serialize_simulation(sim: dict | None) -> dict:
    return sim or {}


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)
    init_storage()

    @flask_app.get("/")
    def dashboard():
        return render_template(
            "index.html",
            payload_options=Config.PAYLOAD_OPTIONS_PERCENT,
            supported_resolutions=Config.SUPPORTED_RESOLUTIONS,
        )

    @flask_app.post("/api/upload-image")
    def upload_image():
        uploaded = request.files.get("image")
        simulation_id = _coerce_simulation_id(request.form.get("simulation_id", 1))
        threshold_low, threshold_high, bit_depth = _prepare_thresholds(request.form.to_dict())

        if not uploaded:
            return jsonify({"error": "No image file uploaded"}), 400

        filename = f"upload_{uuid.uuid4().hex}.tmp"
        save_path = os.path.join(flask_app.config["UPLOAD_FOLDER"], filename)
        uploaded.save(save_path)

        try:
            width, height, fmt = validate_image(save_path)
        except LSBError:
            if os.path.exists(save_path):
                os.remove(save_path)
            return jsonify({"error": f"Invalid image. Use PNG/BMP square images with resolutions {Config.SUPPORTED_RESOLUTIONS}."}), 400
        except (OSError, ValueError):
            if os.path.exists(save_path):
                os.remove(save_path)
            return jsonify({"error": "Unable to process uploaded image"}), 400

        final_filename = f"sim_{simulation_id}_{uuid.uuid4().hex}.{fmt.lower()}"
        final_path = os.path.join(flask_app.config["UPLOAD_FOLDER"], final_filename)
        os.replace(save_path, final_path)

        paths = _simulation_paths(simulation_id, flask_app.config["RESULTS_FOLDER"])
        save_edge_map_image(final_path, paths["edge_map_path"], threshold_low, threshold_high)
        capacity = analyze_image_capacity(final_path, threshold_low, threshold_high, bit_depth)

        sim = update_simulation(
            simulation_id,
            {
                "image_path": final_path,
                "status": "image_uploaded",
                "format": fmt,
                "dimensions": [width, height],
                "capacity_bytes": capacity["capacity_bytes"],
                "edge_map_path": paths["edge_map_path"],
                "edge_threshold_low": threshold_low,
                "edge_threshold_high": threshold_high,
                "bit_depth": bit_depth,
                "algorithm": "adaptive_lsb",
            },
        )
        return jsonify({"message": "Image uploaded", "simulation": _serialize_simulation(sim)})

    @flask_app.post("/api/preprocess")
    def preprocess_image():
        data = request.get_json(silent=True) or {}
        simulation_id = _coerce_simulation_id(data.get("simulation_id", 1))
        threshold_low, threshold_high, bit_depth = _prepare_thresholds(data)

        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if not sim.get("image_path"):
            return jsonify({"error": "Upload an image first"}), 400

        paths = _simulation_paths(simulation_id, flask_app.config["RESULTS_FOLDER"])
        save_edge_map_image(sim["image_path"], paths["edge_map_path"], threshold_low, threshold_high)
        capacity = analyze_image_capacity(sim["image_path"], threshold_low, threshold_high, bit_depth)
        updated = update_simulation(
            simulation_id,
            {
                "edge_map_path": paths["edge_map_path"],
                "edge_threshold_low": threshold_low,
                "edge_threshold_high": threshold_high,
                "bit_depth": bit_depth,
                "capacity_bytes": capacity["capacity_bytes"],
                "edge_pixel_count": capacity["edge_pixel_count"],
                "status": "preprocessed",
            },
        )
        return jsonify({"message": "Preprocessing completed", "simulation": _serialize_simulation(updated)})

    @flask_app.post("/api/run-simulation")
    def run_simulation():
        data = request.get_json(silent=True) or {}
        simulation_id = _coerce_simulation_id(data.get("simulation_id", 1))
        payload_percentage = data.get("payload_percentage")
        secret_message = data.get("secret_message", "")
        threshold_low, threshold_high, bit_depth = _prepare_thresholds(data)

        if payload_percentage is None:
            return jsonify({"error": "payload_percentage is required"}), 400

        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if not sim.get("image_path"):
            return jsonify({"error": "Upload an image first"}), 400
        if payload_percentage not in Config.PAYLOAD_OPTIONS_PERCENT:
            return jsonify({"error": f"payload_percentage must be one of {Config.PAYLOAD_OPTIONS_PERCENT}"}), 400
        if bit_depth not in {1, 2, 3, 4}:
            return jsonify({"error": "bit_depth must be 1, 2, 3, or 4"}), 400

        paths = _simulation_paths(simulation_id, flask_app.config["RESULTS_FOLDER"])
        capacity = analyze_image_capacity(sim["image_path"], threshold_low, threshold_high, bit_depth)
        payload_limit = _payload_limit_bytes_from_dimensions(sim.get("dimensions") or [], int(payload_percentage))
        if len(secret_message.encode("utf-8")) > payload_limit:
            return jsonify({"error": "Secret message exceeds the selected payload percentage"}), 400

        started = time.perf_counter()
        try:
            embedded_bytes, max_capacity_bytes = encode_message_in_image(
                sim["image_path"],
                secret_message,
                paths["stego_image_path"],
                threshold_low,
                threshold_high,
                bit_depth,
            )
        except LSBError:
            return jsonify({"error": "Encoding failed for the provided payload/image"}), 400
        elapsed_ms = (time.perf_counter() - started) * 1000

        save_edge_map_image(sim["image_path"], paths["edge_map_path"], threshold_low, threshold_high)
        save_difference_image(sim["image_path"], paths["stego_image_path"], paths["difference_image_path"])

        metrics = compute_metrics(sim["image_path"], paths["stego_image_path"])
        chi_square = round(chi_square_lsb(paths["stego_image_path"]), 6)
        actual_embedded_words = len(secret_message.split()) if secret_message.strip() else 0

        updated = update_simulation(
            simulation_id,
            {
                "edge_map_path": paths["edge_map_path"],
                "stego_image_path": paths["stego_image_path"],
                "difference_image_path": paths["difference_image_path"],
                "payload_percentage": int(payload_percentage),
                "payload_target_bytes": payload_limit,
                "edge_threshold_low": threshold_low,
                "edge_threshold_high": threshold_high,
                "bit_depth": bit_depth,
                "secret_message": secret_message,
                "embedded_bytes": embedded_bytes,
                "adaptive_capacity_bytes": capacity["capacity_bytes"],
                "capacity_bytes": max_capacity_bytes,
                "edge_pixel_count": capacity["edge_pixel_count"],
                "max_possible_word_count": payload_limit,
                "actual_embedded_word_count": actual_embedded_words,
                "psnr": metrics["psnr"],
                "ssim": metrics["ssim"],
                "chi_square": chi_square,
                "embedded_words": actual_embedded_words,
                "embedding_time_ms": round(elapsed_ms, 4),
                "status": "encoded",
                "algorithm": "adaptive_lsb",
            },
        )
        return jsonify({"message": "Simulation completed", "simulation": _serialize_simulation(updated)})

    @flask_app.post("/api/decode-simulation")
    def decode_simulation():
        data = request.get_json(silent=True) or {}
        simulation_id = _coerce_simulation_id(data.get("simulation_id", 1))
        threshold_low, threshold_high, bit_depth = _prepare_thresholds(data)

        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if not sim.get("stego_image_path"):
            return jsonify({"error": "Run the simulation first"}), 400
        if not sim.get("image_path"):
            return jsonify({"error": "Original cover image not available"}), 400

        threshold_low = _coerce_float(sim.get("edge_threshold_low"), threshold_low)
        threshold_high = _coerce_float(sim.get("edge_threshold_high"), threshold_high)
        bit_depth = _coerce_int(sim.get("bit_depth"), bit_depth)

        try:
            extracted_message = decode_message_from_image(
                sim["stego_image_path"],
                sim["image_path"],
                threshold_low,
                threshold_high,
                bit_depth,
            )
        except LSBError:
            return jsonify({"error": "Decoding failed for the current stego image"}), 400

        updated = update_simulation(
            simulation_id,
            {
                "extracted_message": extracted_message,
                "extraction_time_ms": 0,
                "extraction_accuracy": 1.0 if extracted_message is not None else 0.0,
                "status": "decoded",
            },
        )
        return jsonify(
            {
                "message": "Decoding completed",
                "simulation": _serialize_simulation(updated),
                "extracted_message": extracted_message,
                "restored_image_path": sim["image_path"],
            }
        )

    @flask_app.post("/api/matrix-analysis")
    def matrix_analysis():
        uploaded_images = request.files.getlist("benchmarks")
        payload_text = request.form.get("payload_text", "")
        threshold_low, threshold_high, _ = _prepare_thresholds(request.form.to_dict())
        payload_percentages = _parse_payload_percentages(request.form.get("payload_options"))
        bit_depths = [1, 2, 3]

        if not uploaded_images:
            return jsonify({"error": "Upload one or more benchmark images"}), 400
        if not payload_text.strip():
            return jsonify({"error": "payload_text is required"}), 400

        runs = []
        temp_paths: list[str] = []
        try:
            for uploaded in uploaded_images:
                filename = f"benchmark_{uuid.uuid4().hex}.tmp"
                save_path = os.path.join(flask_app.config["UPLOAD_FOLDER"], filename)
                uploaded.save(save_path)
                temp_paths.append(save_path)

                try:
                    validate_image(save_path)
                except LSBError:
                    continue

                for payload_percentage in payload_percentages:
                    for bit_depth in bit_depths:
                        capacity = analyze_image_capacity(save_path, threshold_low, threshold_high, bit_depth)
                        payload_limit = _payload_limit_bytes_from_dimensions(capacity["dimensions"], payload_percentage)
                        message = payload_text
                        if len(message.encode("utf-8")) > payload_limit:
                            message = message.encode("utf-8")[:payload_limit].decode("utf-8", errors="ignore")

                        stego_path = os.path.join(flask_app.config["RESULTS_FOLDER"], f"matrix_{uuid.uuid4().hex}.png")
                        try:
                            embedded_bytes, max_capacity_bytes = encode_message_in_image(
                                save_path,
                                message,
                                stego_path,
                                threshold_low,
                                threshold_high,
                                bit_depth,
                            )
                        except LSBError:
                            continue

                        metrics = compute_metrics(save_path, stego_path)
                        chi_square = round(chi_square_lsb(stego_path), 6)
                        runs.append(
                            {
                                "image": uploaded.filename or os.path.basename(save_path),
                                "payload_percentage": payload_percentage,
                                "bit_depth": bit_depth,
                                "capacity_bits": capacity["capacity_bits"],
                                "capacity_bytes": capacity["capacity_bytes"],
                                "embedded_bytes": embedded_bytes,
                                "max_capacity_bytes": max_capacity_bytes,
                                "psnr": metrics["psnr"],
                                "ssim": metrics["ssim"],
                                "chi_square": chi_square,
                                "score": round(_recommendation_score(metrics["psnr"], metrics["ssim"], chi_square), 6),
                            }
                        )
        finally:
            for path in temp_paths:
                if os.path.exists(path):
                    os.remove(path)

        best_run = max(runs, key=lambda item: item["score"], default=None)
        summary = (
            f"Based on {len(runs)} simulated runs of the uploaded benchmark images utilizing Canny Edge thresholds of [{int(threshold_low * 100)}, {int(threshold_high * 100)}], "
            f"the optimal threshold balancing capacity and security is achieved at {best_run['payload_percentage']}% payload size using {best_run['bit_depth']} bits/channel, "
            f"yielding an average PSNR of {best_run['psnr']} dB and an SSIM of {best_run['ssim']}."
            if best_run
            else "No valid recommendation could be generated."
        )

        report = {
            "run_count": len(runs),
            "threshold_low": threshold_low,
            "threshold_high": threshold_high,
            "payload_options": payload_percentages,
            "bit_depths": bit_depths,
            "best_run": best_run,
            "runs": runs,
            "summary": summary,
        }
        report_path = os.path.join(flask_app.config["RESULTS_FOLDER"], f"matrix_report_{uuid.uuid4().hex}.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        report["report_path"] = report_path
        return jsonify(report)

    @flask_app.get("/api/simulation/<int:simulation_id>")
    def simulation_detail(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        return jsonify(sim)

    @flask_app.get("/results/<path:filename>")
    def serve_results_file(filename: str):
        directory = flask_app.config["RESULTS_FOLDER"]
        root = os.path.abspath(directory)
        path = os.path.abspath(os.path.join(root, filename))
        if os.path.commonpath([root, path]) != root:
            return jsonify({"error": "Invalid file path"}), 400
        if not os.path.exists(path):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(directory, filename)

    @flask_app.get("/uploads/<path:filename>")
    def serve_uploads_file(filename: str):
        directory = flask_app.config["UPLOAD_FOLDER"]
        root = os.path.abspath(directory)
        path = os.path.abspath(os.path.join(root, filename))
        if os.path.commonpath([root, path]) != root:
            return jsonify({"error": "Invalid file path"}), 400
        if not os.path.exists(path):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(directory, filename)

    return flask_app


app = create_app()

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1",
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
