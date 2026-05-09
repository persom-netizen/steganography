import os
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from backend.analytics import aggregate_statistics
from backend.database import export_results, get_completed_simulations, get_simulation, init_storage, list_simulations, update_simulation
from backend.lsb_engine import LSBError, decode_message_from_image, encode_message_in_image, extraction_accuracy, validate_image
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
        return render_template("index.html", payload_options=Config.PAYLOAD_OPTIONS_KB)

    @app.get("/session/new")
    @app.get("/analytics/session/<int:session_id>")
    @app.get("/testing/stats")
    def dashboard_alias(session_id: int | None = None):
        return render_template("index.html", payload_options=Config.PAYLOAD_OPTIONS_KB)

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

        extension = Path(uploaded.filename or "").suffix.lower()
        filename = f"sim_{simulation_id}_{uuid.uuid4().hex}{extension}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        uploaded.save(save_path)

        try:
            width, height, fmt = validate_image(save_path)
        except LSBError as exc:
            if os.path.exists(save_path):
                os.remove(save_path)
            return jsonify({"error": str(exc)}), 400

        sim = update_simulation(
            simulation_id,
            {
                "image_path": save_path,
                "status": "image_uploaded",
                "format": fmt,
                "dimensions": [width, height],
            },
        )
        return jsonify({"message": "Image uploaded", "simulation": sim})

    @app.post("/api/encode")
    def encode():
        data = request.get_json(silent=True) or {}
        simulation_id = data.get("simulation_id")
        payload_size_kb = data.get("payload_size_kb")
        message = data.get("secret_message", "")

        if simulation_id is None or payload_size_kb is None:
            return jsonify({"error": "simulation_id and payload_size_kb are required"}), 400

        sim = get_simulation(int(simulation_id))
        if not sim:
            return jsonify({"error": "Simulation not found"}), 404
        if sim.get("locked"):
            return jsonify({"error": "Simulation is locked"}), 409
        if not sim.get("image_path"):
            return jsonify({"error": "Upload an image first"}), 400
        if payload_size_kb not in Config.PAYLOAD_OPTIONS_KB:
            return jsonify({"error": f"payload_size_kb must be one of {Config.PAYLOAD_OPTIONS_KB}"}), 400

        payload_limit = int(payload_size_kb) * 1024
        if len(message.encode("utf-8")) > payload_limit:
            return jsonify({"error": "Secret message exceeds selected payload size"}), 400

        stego_path = os.path.join(app.config["RESULTS_FOLDER"], f"stego_sim_{simulation_id}.png")

        started = time.perf_counter()
        try:
            embedded_bytes, max_capacity_bytes = encode_message_in_image(sim["image_path"], message, stego_path)
        except LSBError as exc:
            return jsonify({"error": str(exc)}), 400
        elapsed_ms = (time.perf_counter() - started) * 1000

        metrics = compute_metrics(sim["image_path"], stego_path)

        updated = update_simulation(
            int(simulation_id),
            {
                "stego_image_path": stego_path,
                "payload_size_kb": int(payload_size_kb),
                "secret_message": message,
                "metrics": metrics,
                "status": "encoded",
                "embedding_time_ms": round(elapsed_ms, 4),
                "embedded_bytes": embedded_bytes,
                "capacity_bytes": max_capacity_bytes,
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
            extracted = decode_message_from_image(sim["stego_image_path"])
        except LSBError as exc:
            return jsonify({"error": str(exc)}), 400
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
                "payload_size_kb": sim.get("payload_size_kb"),
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
                "Payload Size vs PSNR",
                "PSNR (dB)",
                os.path.join(graphs_dir, "payload_vs_psnr.png"),
            ),
            "payload_vs_mse": generate_payload_metric_graph(
                all_sims,
                "mse",
                "Payload Size vs MSE",
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
        path = os.path.join(app.config["RESULTS_FOLDER"], filename)
        if not os.path.exists(path):
            return jsonify({"error": "File not found"}), 404
        return send_file(path)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
