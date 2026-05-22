import os
import json
import time
import uuid

import numpy as np
from PIL import Image
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

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


def _decode_stego_best_effort(stego_path: str, cover_path: str | None, threshold_low: float, threshold_high: float, bit_depth: int) -> str:
    candidate_thresholds: list[tuple[float, float]] = [
        (threshold_low, threshold_high),
        (0.30, 0.70),
        (0.25, 0.65),
        (0.20, 0.60),
        (0.35, 0.75),
    ]
    candidate_bit_depths = [bit_depth, 3, 2, 4, 1]
    seen: set[tuple[float, float, int]] = set()

    last_error: LSBError | None = None
    for candidate_low, candidate_high in candidate_thresholds:
        for candidate_depth in candidate_bit_depths:
            key = (round(candidate_low, 4), round(candidate_high, 4), int(candidate_depth))
            if key in seen:
                continue
            seen.add(key)
            try:
                return decode_message_from_image(
                    stego_path,
                    cover_path,
                    candidate_low,
                    candidate_high,
                    int(candidate_depth),
                )
            except LSBError as error:
                last_error = error

    if last_error is not None:
        raise last_error
    raise LSBError("Decoding failed for the uploaded image")


def _save_uploaded_file(uploaded, folder: str, prefix: str) -> str:
    filename = uploaded.filename or "file"
    _, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ".png"
    final_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    final_path = os.path.join(folder, final_name)
    uploaded.save(final_path)
    return final_path


def _load_rgb_flat_uint8(path: str) -> np.ndarray:
    with Image.open(path) as image:
        return np.array(image.convert("RGB"), dtype=np.uint8).reshape(-1)


def _binary_text_from_image(image_path: str, compare_path: str | None = None, mark_changes: bool = False) -> str:
    values = _load_rgb_flat_uint8(image_path)
    compare_values = None
    if compare_path:
        compare_values = _load_rgb_flat_uint8(compare_path)
        if compare_values.shape != values.shape:
            raise LSBError("Original and stego image dimensions do not match")

    lines: list[str] = []
    for idx, value in enumerate(values):
        bits = format(int(value), "08b")
        if mark_changes and compare_values is not None and int(value) != int(compare_values[idx]):
            lines.append(f"{idx}\tC{bits}")
        else:
            lines.append(f"{idx}\t{bits}")
    return "\n".join(lines)


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

    @flask_app.get("/study/20-simulations")
    def study_20_simulations():
        return render_template(
            "study_20_simulations.html",
            payload_options=[10, 25, 50, 75, 90],
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
        adaptive_limit = max(1, int(capacity["capacity_bytes"]))
        effective_limit = min(payload_limit, adaptive_limit)
        if len(secret_message.encode("utf-8")) > payload_limit:
            return jsonify({"error": "Secret message exceeds the selected payload percentage"}), 400
        if len(secret_message.encode("utf-8")) > adaptive_limit:
            return jsonify({"error": "Secret message exceeds the adaptive image capacity"}), 400

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
        mse_value = metrics.get("mse")
        q_index_value = metrics.get("q_index")
        actual_embedded_words = len(secret_message.split()) if secret_message.strip() else 0

        updated = update_simulation(
            simulation_id,
            {
                "edge_map_path": paths["edge_map_path"],
                "stego_image_path": paths["stego_image_path"],
                "difference_image_path": paths["difference_image_path"],
                "payload_percentage": int(payload_percentage),
                "payload_target_bytes": effective_limit,
                "edge_threshold_low": threshold_low,
                "edge_threshold_high": threshold_high,
                "bit_depth": bit_depth,
                "secret_message": secret_message,
                "extracted_message": "",
                "extraction_time_ms": None,
                "extraction_accuracy": None,
                "embedded_bytes": embedded_bytes,
                "adaptive_capacity_bytes": capacity["capacity_bytes"],
                "capacity_bytes": max_capacity_bytes,
                "edge_pixel_count": capacity["edge_pixel_count"],
                "max_possible_word_count": effective_limit,
                "actual_embedded_word_count": actual_embedded_words,
                "psnr": metrics["psnr"],
                "ssim": metrics["ssim"],
                "q_index": q_index_value,
                "mse": mse_value,
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

    @flask_app.post("/api/decode-uploaded-image")
    def decode_uploaded_image():
        stego_upload = request.files.get("stego_image")
        cover_upload = request.files.get("cover_image")
        threshold_low, threshold_high, bit_depth = _prepare_thresholds(request.form.to_dict())

        if not stego_upload:
            return jsonify({"error": "Upload a stego image to decode"}), 400

        stego_path = _save_uploaded_file(stego_upload, flask_app.config["UPLOAD_FOLDER"], "uploaded_stego")
        cover_path = None
        try:
            validate_image(stego_path)
        except LSBError:
            if os.path.exists(stego_path):
                os.remove(stego_path)
            return jsonify({"error": "Invalid stego image"}), 400

        if cover_upload and cover_upload.filename:
            cover_path = _save_uploaded_file(cover_upload, flask_app.config["UPLOAD_FOLDER"], "uploaded_cover")
            try:
                validate_image(cover_path)
            except LSBError:
                if os.path.exists(cover_path):
                    os.remove(cover_path)
                if os.path.exists(stego_path):
                    os.remove(stego_path)
                return jsonify({"error": "Invalid cover reference image"}), 400

        try:
            extracted_message = _decode_stego_best_effort(stego_path, cover_path, threshold_low, threshold_high, bit_depth)
        except LSBError:
            extracted_message = None

        if not extracted_message:
            if cover_path and os.path.exists(cover_path):
                os.remove(cover_path)
            if os.path.exists(stego_path):
                os.remove(stego_path)
            return jsonify({"error": "Decoding failed for the uploaded image"}), 400

        response = {
            "message": "Uploaded image decoded",
            "extracted_message": extracted_message,
            "restored_image_path": cover_path,
            "source_image_path": stego_path,
        }
        return jsonify(response)

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

    @flask_app.get('/api/study/report')
    def study_report_aggregate():
        # Scan results folder for study20 reports and aggregate metrics
        results_dir = flask_app.config['RESULTS_FOLDER']
        reports = []
        for name in os.listdir(results_dir):
            if name.startswith('study20_') and name.endswith('.json'):
                path = os.path.join(results_dir, name)
                try:
                    with open(path, 'r', encoding='utf-8') as fh:
                        try:
                            data = json.load(fh)
                        except json.JSONDecodeError:
                            continue
                        reports.append(data)
                except OSError:
                    continue

        # Aggregate per resolution and per payload
        per_resolution = {}
        per_payload = {}
        all_runs = []
        for rep in reports:
            runs = rep.get('runs', [])
            for run in runs:
                all_runs.append(run)
                res = int(run.get('resolution', 0))
                payload = int(run.get('payload_percentage', 0))
                per_resolution.setdefault(res, []).append(run)
                per_payload.setdefault(payload, []).append(run)

        summary_res = {}
        for res, runs in per_resolution.items():
            count = len(runs)
            avg_edge = sum(float(r.get('edge_pixel_count', 0)) for r in runs) / count if count else 0
            avg_capacity = sum(float(r.get('capacity_bytes', 0)) for r in runs) / count if count else 0
            avg_embed_time = sum(float(r.get('embedding_time_ms', 0)) for r in runs) / count if count else 0
            avg_extract_time = sum(float(r.get('extraction_time_ms', 0)) for r in runs) / count if count else 0
            avg_accuracy = sum(float(r.get('extraction_accuracy', 0)) for r in runs) / count if count else 0
            summary_res[res] = {
                'resolution': res,
                'run_count': count,
                'avg_edge_pixels': round(avg_edge, 2),
                'avg_capacity_bytes': round(avg_capacity, 2),
                'avg_embedding_time_ms': round(avg_embed_time, 4),
                'avg_extraction_time_ms': round(avg_extract_time, 4),
                'avg_extraction_accuracy': round(avg_accuracy, 4),
            }

        summary_payload = {}
        for payload, runs in per_payload.items():
            count = len(runs)
            avg_mse = sum(float(r.get('mse', 0)) for r in runs) / count if count else 0
            avg_psnr = sum(float(r.get('psnr', 0)) for r in runs) / count if count else 0
            avg_ssim = sum(float(r.get('ssim', 0)) for r in runs) / count if count else 0
            avg_q = sum(float(r.get('q_index', 0)) for r in runs) / count if count else 0
            summary_payload[payload] = {
                'payload_percentage': payload,
                'run_count': count,
                'avg_mse': round(avg_mse, 6),
                'avg_psnr': round(avg_psnr, 6),
                'avg_ssim': round(avg_ssim, 6),
                'avg_q_index': round(avg_q, 6),
            }

        # Recommendations per resolution: choose highest payload with avg_psnr >=40 and avg_accuracy >=0.98
        recommendations = {}
        for res, runs in per_resolution.items():
            best = None
            payload_groups = {}
            for r in runs:
                p = int(r.get('payload_percentage', 0))
                payload_groups.setdefault(p, []).append(r)
            for p, grp in sorted(payload_groups.items()):
                count = len(grp)
                avg_psnr = sum(float(x.get('psnr', 0)) for x in grp) / count if count else 0
                avg_acc = sum(float(x.get('extraction_accuracy', 0)) for x in grp) / count if count else 0
                if avg_psnr >= 40 and avg_acc >= 0.98:
                    best = {'recommended_payload': p, 'psnr': round(avg_psnr, 4), 'extraction_accuracy': round(avg_acc, 4)}
            if not best:
                # fallback: pick payload with highest extraction accuracy then higher psnr
                best_choice = (None, -1.0, -1.0)  # (payload, avg_acc, avg_psnr)
                for p, grp in payload_groups.items():
                    count = len(grp)
                    avg_psnr = sum(float(x.get('psnr', 0)) for x in grp) / count if count else 0
                    avg_acc = sum(float(x.get('extraction_accuracy', 0)) for x in grp) / count if count else 0
                    if (avg_acc > best_choice[1]) or (avg_acc == best_choice[1] and avg_psnr > best_choice[2]):
                        best_choice = (int(p), avg_acc, avg_psnr)
                if best_choice[0] is not None:
                    best = {'recommended_payload': int(best_choice[0]), 'psnr': round(best_choice[2], 4), 'extraction_accuracy': round(best_choice[1], 4)}
            recommendations[res] = best

        return jsonify({
            'by_resolution': summary_res,
            'by_payload': summary_payload,
            'recommendations': recommendations,
            'reports_count': len(reports),
            'total_runs': len(all_runs),
        })

    @flask_app.post("/api/study-20-simulations")
    def study_20_simulations_api():
        resolution = _coerce_int(request.form.get("resolution"), 128)
        payload_percentage = _coerce_int(request.form.get("payload_percentage"), 10)
        bit_depth = _coerce_int(request.form.get("bit_depth"), 3)
        threshold_low, threshold_high, _ = _prepare_thresholds(request.form.to_dict())
        uploaded_images = request.files.getlist("images")
        messages = request.form.getlist("messages")

        if resolution not in Config.SUPPORTED_RESOLUTIONS:
            return jsonify({"error": f"resolution must be one of {Config.SUPPORTED_RESOLUTIONS}"}), 400
        if payload_percentage not in Config.PAYLOAD_OPTIONS_PERCENT:
            return jsonify({"error": f"payload_percentage must be one of {Config.PAYLOAD_OPTIONS_PERCENT}"}), 400
        if bit_depth not in {1, 2, 3, 4}:
            return jsonify({"error": "bit_depth must be 1, 2, 3, or 4"}), 400
        if not uploaded_images:
            return jsonify({"error": "Upload one or more images"}), 400

        runs: list[dict] = []
        temp_paths: list[str] = []
        try:
            for index, uploaded in enumerate(uploaded_images, start=1):
                filename = f"study20_{resolution}_{uuid.uuid4().hex}.tmp"
                save_path = os.path.join(flask_app.config["UPLOAD_FOLDER"], filename)
                uploaded.save(save_path)
                temp_paths.append(save_path)

                try:
                    width, height, _ = validate_image(save_path)
                except LSBError:
                    continue

                if width != resolution or height != resolution:
                    continue

                capacity = analyze_image_capacity(save_path, threshold_low, threshold_high, bit_depth)
                payload_limit = _payload_limit_bytes_from_dimensions(capacity["dimensions"], payload_percentage)
                message = messages[index - 1] if index - 1 < len(messages) else ""
                message_bytes = message.encode("utf-8")
                if len(message_bytes) > payload_limit:
                    message = message_bytes[:payload_limit].decode("utf-8", errors="ignore")

                stego_path = os.path.join(flask_app.config["RESULTS_FOLDER"], f"study20_{resolution}_{uuid.uuid4().hex}.png")
                started = time.perf_counter()
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
                embedding_time_ms = (time.perf_counter() - started) * 1000

                decode_started = time.perf_counter()
                try:
                    extracted_message = decode_message_from_image(
                        stego_path,
                        save_path,
                        threshold_low,
                        threshold_high,
                        bit_depth,
                    )
                except LSBError:
                    extracted_message = ""
                extraction_time_ms = (time.perf_counter() - decode_started) * 1000

                metrics = compute_metrics(save_path, stego_path)
                chi_square = round(chi_square_lsb(stego_path), 6)
                extraction_accuracy = 1.0 if extracted_message == message else 0.0

                runs.append({
                    "image_index": index,
                    "resolution": resolution,
                    "payload_percentage": payload_percentage,
                    "bit_depth": bit_depth,
                    "capacity_bytes": capacity["capacity_bytes"],
                    "edge_pixel_count": capacity.get("edge_pixel_count", 0),
                    "payload_limit_bytes": payload_limit,
                    "embedded_bytes": embedded_bytes,
                    "max_capacity_bytes": max_capacity_bytes,
                    "psnr": metrics["psnr"],
                    "ssim": metrics["ssim"],
                    "mse": metrics["mse"],
                    "q_index": metrics["q_index"],
                    "chi_square": chi_square,
                    "extraction_accuracy": extraction_accuracy,
                    "embedding_time_ms": round(embedding_time_ms, 4),
                    "extraction_time_ms": round(extraction_time_ms, 4),
                    "message_length": len(message),
                    "extracted_message": extracted_message,
                    "stego_path": stego_path,
                })
        finally:
            for path in temp_paths:
                if os.path.exists(path):
                    os.remove(path)

        if runs:
            avg_psnr = round(sum(float(run["psnr"]) for run in runs) / len(runs), 6)
            avg_ssim = round(sum(float(run["ssim"]) for run in runs) / len(runs), 6)
            avg_mse = round(sum(float(run["mse"]) for run in runs) / len(runs), 6)
            avg_q = round(sum(float(run["q_index"]) for run in runs) / len(runs), 6)
            avg_accuracy = round(sum(float(run["extraction_accuracy"]) for run in runs) / len(runs), 6)
            avg_embed_time = round(sum(float(run["embedding_time_ms"]) for run in runs) / len(runs), 4)
            avg_extract_time = round(sum(float(run["extraction_time_ms"]) for run in runs) / len(runs), 4)
        else:
            avg_psnr = avg_ssim = avg_mse = avg_q = avg_accuracy = 0.0
            avg_embed_time = avg_extract_time = 0.0

        discussion = (
            f"The {resolution}px batch produced {len(runs)} valid simulations at {payload_percentage}% payload. "
            f"Average PSNR was {avg_psnr} dB, SSIM was {avg_ssim}, MSE was {avg_mse}, Q Index was {avg_q}, and extraction accuracy was {avg_accuracy}. "
            f"Embedding and extraction times averaged {avg_embed_time} ms and {avg_extract_time} ms respectively."
        )

        report = {
            "resolution": resolution,
            "payload_percentage": payload_percentage,
            "bit_depth": bit_depth,
            "run_count": len(runs),
            "average_metrics": {
                "psnr": avg_psnr,
                "ssim": avg_ssim,
                "mse": avg_mse,
                "q_index": avg_q,
                "extraction_accuracy": avg_accuracy,
                "embedding_time_ms": avg_embed_time,
                "extraction_time_ms": avg_extract_time,
            },
            "discussion": discussion,
            "runs": runs,
        }
        report_path = os.path.join(flask_app.config["RESULTS_FOLDER"], f"study20_{resolution}_{payload_percentage}_{uuid.uuid4().hex}.json")
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

    @flask_app.get("/api/simulation/<int:simulation_id>/binary-export")
    def binary_export(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404

        target = (request.args.get("target") or "").strip().lower()
        if target not in {"original", "stego"}:
            return jsonify({"error": "target must be 'original' or 'stego'"}), 400

        original_path = sim.get("image_path")
        stego_path = sim.get("stego_image_path")
        if not original_path:
            return jsonify({"error": "Original image not available"}), 400
        if target == "stego" and not stego_path:
            return jsonify({"error": "Stego image not available. Run the simulation first."}), 400

        export_path = original_path if target == "original" else stego_path
        if not export_path or not os.path.exists(export_path):
            return jsonify({"error": "Requested image file not found"}), 404

        compare_path = original_path if target == "stego" else None
        mark_changes = target == "stego"

        try:
            binary_text = _binary_text_from_image(export_path, compare_path=compare_path, mark_changes=mark_changes)
        except (OSError, ValueError, LSBError) as error:
            return jsonify({"error": f"Unable to generate binary export: {error}"}), 400

        filename = f"{target}_binary_sim_{simulation_id}.txt"
        return Response(
            binary_text,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

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
