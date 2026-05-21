import os
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

from backend.adaptive_lsb_engine import (
    LSBError,
    analyze_image_capacity,
    calculate_payload_bytes,
    decode_message_from_image,
    encode_message_in_image,
    extraction_accuracy,
    validate_image,
)
from backend.analytics import aggregate_statistics
from backend.database import export_results, get_completed_simulations, get_simulation, init_storage, list_simulations, update_simulation
from backend.metrics import compute_metrics
from backend.visualization import (
    generate_accuracy_graph,
    generate_embedding_time_graph,
    generate_histogram_comparison,
    generate_payload_metric_graph,
)
from config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    init_storage()

    @app.get("/")
    def dashboard():
        return render_template(
            "index.html",
            payload_options=Config.PAYLOAD_OPTIONS_PERCENT,
            supported_resolutions=Config.SUPPORTED_RESOLUTIONS,
        )

    @app.get("/session/new")
    @app.get("/analytics/session/<int:session_id>")
    @app.get("/testing/stats")
    def dashboard_alias(session_id: int | None = None):
        return render_template(
            "index.html",
            payload_options=Config.PAYLOAD_OPTIONS_PERCENT,
            supported_resolutions=Config.SUPPORTED_RESOLUTIONS,
        )

    @app.post("/api/upload-image")
    def upload_image():
        uploaded = request.files.get("image")
        simulation_id = request.form.get("simulation_id", type=int)

        if not uploaded:
            return jsonify({"error": "No image file uploaded"}), 400
        if simulation_id is None:
            return jsonify({"error": "simulation_id is required"}), 400

        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if sim.get("locked"):
            return jsonify({"error": "Simulation is locked"}), 409

        filename = f"upload_{uuid.uuid4().hex}.tmp"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        uploaded.save(save_path)

        try:
            width, height, fmt = validate_image(save_path)
        except LSBError:
            if os.path.exists(save_path):
                os.remove(save_path)
            return jsonify(
                {
                    "error": (
                        "Invalid image. Only PNG/BMP square images with resolutions "
                        f"{Config.SUPPORTED_RESOLUTIONS} are accepted"
                    )
                }
            ), 400
        except Exception:
            if os.path.exists(save_path):
                os.remove(save_path)
            return jsonify({"error": "Unable to process uploaded image"}), 400

        final_filename = f"sim_{simulation_id}_{uuid.uuid4().hex}.{fmt.lower()}"
        final_path = os.path.join(app.config["UPLOAD_FOLDER"], final_filename)
        os.replace(save_path, final_path)

        sim = update_simulation(
            simulation_id,
            {
                "image_path": final_path,
                "status": "image_uploaded",
                "format": fmt,
                "dimensions": [width, height],
                "capacity_bytes": analyze_image_capacity(final_path)["capacity_bytes"],
                "algorithm": "adaptive_lsb",
            },
        )
        return jsonify({"message": "Image uploaded", "simulation": sim})

    @app.post("/api/encode")
    def encode():
        data = request.get_json(silent=True) or {}
        simulation_id = data.get("simulation_id")
        payload_percentage = data.get("payload_percentage")
        message = data.get("secret_message", "")

        if simulation_id is None or payload_percentage is None:
            return jsonify({"error": "simulation_id and payload_percentage are required"}), 400

        sim = get_simulation(int(simulation_id))
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if sim.get("locked"):
            return jsonify({"error": "Simulation is locked"}), 409
        if not sim.get("image_path"):
            return jsonify({"error": "Upload an image first"}), 400
        if payload_percentage not in Config.PAYLOAD_OPTIONS_PERCENT:
            return jsonify({"error": f"payload_percentage must be one of {Config.PAYLOAD_OPTIONS_PERCENT}"}), 400

        capacity = analyze_image_capacity(sim["image_path"])
        payload_limit = calculate_payload_bytes(capacity["capacity_bytes"], int(payload_percentage))
        if len(message.encode("utf-8")) > payload_limit:
            return jsonify({"error": "Secret message exceeds the selected payload percentage"}), 400

        stego_path = os.path.join(app.config["RESULTS_FOLDER"], f"stego_sim_{simulation_id}.png")

        started = time.perf_counter()
        try:
            embedded_bytes, max_capacity_bytes = encode_message_in_image(sim["image_path"], message, stego_path)
        except LSBError:
            return jsonify({"error": "Encoding failed for the provided payload/image"}), 400
        elapsed_ms = (time.perf_counter() - started) * 1000

        metrics = compute_metrics(sim["image_path"], stego_path)

        updated = update_simulation(
            int(simulation_id),
            {
                "stego_image_path": stego_path,
                "payload_percentage": int(payload_percentage),
                "payload_target_bytes": payload_limit,
                "secret_message": message,
                "metrics": metrics,
                "status": "encoded",
                "embedding_time_ms": round(elapsed_ms, 4),
                "embedded_bytes": embedded_bytes,
                "capacity_bytes": max_capacity_bytes,
                "algorithm": "adaptive_lsb",
            },
        )
        return jsonify({"message": "Encoding completed", "simulation": updated})

    @app.post("/api/decode")
    def decode():
        data = request.get_json(silent=True) or {}
        simulation_id = data.get("simulation_id")
        if simulation_id is None:
            return jsonify({"error": "simulation_id is required"}), 400

        sim = get_simulation(int(simulation_id))
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if not sim.get("stego_image_path"):
            return jsonify({"error": "Encode first"}), 400

        started = time.perf_counter()
        try:
            extracted = decode_message_from_image(sim["stego_image_path"], sim.get("image_path"))
        except LSBError:
            return jsonify({"error": "Decoding failed for the selected stego image"}), 400
        elapsed_ms = (time.perf_counter() - started) * 1000

        accuracy = extraction_accuracy(sim.get("secret_message", ""), extracted)
        updated = update_simulation(
            int(simulation_id),
            {
                "extracted_message": extracted,
                "extraction_time_ms": round(elapsed_ms, 4),
                "extraction_accuracy": accuracy,
                "status": "decoded",
            },
        )
        return jsonify({"message": "Decoding completed", "simulation": updated})

    @app.get("/api/metrics/<int:simulation_id>")
    def get_metrics(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        return jsonify(
            {
                "simulation_id": simulation_id,
                "metrics": sim.get("metrics", {}),
                "embedding_time_ms": sim.get("embedding_time_ms"),
                "extraction_time_ms": sim.get("extraction_time_ms"),
                "extraction_accuracy": sim.get("extraction_accuracy"),
                "payload_percentage": sim.get("payload_percentage"),
                "payload_target_bytes": sim.get("payload_target_bytes"),
                "capacity_bytes": sim.get("capacity_bytes"),
            }
        )

    @app.post("/api/generate-graphs/<int:simulation_id>")
    def generate_graphs(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if not sim.get("stego_image_path"):
            return jsonify({"error": "Encode first"}), 400

        all_sims = get_completed_simulations()
        graphs_dir = app.config["RESULTS_FOLDER"]
        graphs = {
            "payload_vs_psnr": generate_payload_metric_graph(
                all_sims,
                "psnr",
                "Payload Percentage vs PSNR",
                "PSNR (dB)",
                os.path.join(graphs_dir, "payload_vs_psnr.png"),
            ),
            "payload_vs_mse": generate_payload_metric_graph(
                all_sims,
                "mse",
                "Payload Percentage vs MSE",
                "MSE",
                os.path.join(graphs_dir, "payload_vs_mse.png"),
            ),
            "payload_vs_accuracy": generate_accuracy_graph(all_sims, os.path.join(graphs_dir, "payload_vs_accuracy.png")),
            "payload_vs_embedding_time": generate_embedding_time_graph(
                all_sims, os.path.join(graphs_dir, "payload_vs_embedding_time.png")
            ),
            "histogram_comparison": generate_histogram_comparison(
                sim["image_path"],
                sim["stego_image_path"],
                os.path.join(graphs_dir, f"histogram_sim_{simulation_id}.png"),
            ),
        }

        updated = update_simulation(simulation_id, {"graphs": graphs})
        return jsonify({"message": "Graphs generated", "graphs": graphs, "simulation": updated})

    @app.get("/api/simulations")
    def simulations():
        sims = list_simulations()
        return jsonify({"simulations": sims, "statistics": aggregate_statistics(sims)})

    @app.get("/api/simulation/<int:simulation_id>")
    def simulation_detail(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        return jsonify(sim)

    @app.post("/api/lock-simulation/<int:simulation_id>")
    def lock_simulation(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        updated = update_simulation(simulation_id, {"locked": True, "status": "locked"})
        return jsonify({"message": "Simulation locked", "simulation": updated})

    @app.post("/api/export-results/<int:simulation_id>")
    def export(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        export_path = export_results(simulation_id)
        if not export_path:
            return jsonify({"error": "Failed to export simulation"}), 500
        return send_file(export_path, as_attachment=True, download_name=f"simulation_{simulation_id}_evidence.json")

    @app.post("/api/testing/blackbox/<int:simulation_id>")
    def blackbox_test(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404

        result = {
            "image_uploaded": bool(sim.get("image_path")),
            "can_encode": bool(sim.get("image_path")) and not sim.get("locked"),
            "locked_state_visible": bool(sim.get("locked")),
        }
        updated = update_simulation(simulation_id, {"test_results": {**(sim.get("test_results") or {}), "blackbox": result}})
        return jsonify({"message": "Black-box test executed", "result": result, "simulation": updated})

    @app.post("/api/testing/whitebox/<int:simulation_id>")
    def whitebox_test(simulation_id: int):
        sim = get_simulation(simulation_id)
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404

        result = {
            "extraction_accuracy": sim.get("extraction_accuracy"),
            "embedding_time_ms": sim.get("embedding_time_ms"),
            "extraction_time_ms": sim.get("extraction_time_ms"),
            "decoded_message_matches": sim.get("secret_message", "") == sim.get("extracted_message", ""),
        }
        updated = update_simulation(simulation_id, {"test_results": {**(sim.get("test_results") or {}), "whitebox": result}})
        return jsonify({"message": "White-box test executed", "result": result, "simulation": updated})

    @app.get("/results/<path:filename>")
    def serve_results_file(filename: str):
        directory = app.config["RESULTS_FOLDER"]
        root = os.path.abspath(directory)
        path = os.path.abspath(os.path.join(root, filename))
        if os.path.commonpath([root, path]) != root:
            return jsonify({"error": "Invalid file path"}), 400
        if not os.path.exists(path):
            return jsonify({"error": "File not found"}), 404
        return send_from_directory(directory, filename)

    return app


app = create_app()

if __name__ == "__main__":
    is_production = os.environ.get("FLASK_ENV", "").lower() == "production"
    app.run(
        debug=os.environ.get("FLASK_DEBUG") == "1" and not is_production,
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
