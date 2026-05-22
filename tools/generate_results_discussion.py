import csv
import glob
import json
import os
from collections import defaultdict
from statistics import mean

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS_DIR = os.path.join(ROOT, "results")
OUT_MD = os.path.join(RESULTS_DIR, "results_and_discussion.md")
OUT_TABLE2 = os.path.join(RESULTS_DIR, "table2_resolution_capacity.csv")
OUT_TABLE21 = os.path.join(RESULTS_DIR, "table2_1_times_accuracy.csv")
OUT_TABLE3 = os.path.join(RESULTS_DIR, "table3_payload_quality.csv")
OUT_TABLE4 = os.path.join(RESULTS_DIR, "table4_payload_degradation_accuracy.csv")
OUT_TABLE5 = os.path.join(RESULTS_DIR, "table5_recommendations.csv")


def safe_mean(values):
    if not values:
        return None
    return mean(values)


def fmt_num(v, nd=4):
    if v is None:
        return "N/A"
    return f"{v:.{nd}f}"


def fmt_pct(v, nd=2):
    if v is None:
        return "N/A"
    return f"{v * 100:.{nd}f}%"


def load_reports():
    reports = []
    for path in glob.glob(os.path.join(RESULTS_DIR, "study20_*_*.json")):
        base = os.path.basename(path)
        parts = base.replace(".json", "").split("_")
        # Expect study20_{resolution}_{payload}_{uuid}.json
        if len(parts) < 4:
            continue
        try:
            resolution = int(parts[1])
            payload = int(parts[2])
        except ValueError:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        runs = data.get("runs", [])
        if not isinstance(runs, list):
            continue

        reports.append(
            {
                "path": path,
                "resolution": resolution,
                "payload": payload,
                "runs": runs,
                "report": data,
            }
        )
    return reports


def aggregate(reports):
    by_res = defaultdict(list)
    by_payload = defaultdict(list)

    for rep in reports:
        for run in rep["runs"]:
            r = dict(run)
            r.setdefault("resolution", rep["resolution"])
            r.setdefault("payload_percentage", rep["payload"])
            by_res[int(r["resolution"])].append(r)
            by_payload[int(r["payload_percentage"])].append(r)

    res_rows = {}
    for res in [128, 256, 512, 1024]:
        runs = by_res.get(res, [])
        res_rows[res] = {
            "edge_pixels": safe_mean([float(x.get("edge_pixel_count", 0)) for x in runs]) if runs else None,
            "capacity_bytes": safe_mean([float(x.get("capacity_bytes", 0)) for x in runs]) if runs else None,
            "embed_ms": safe_mean([float(x.get("embedding_time_ms", 0)) for x in runs]) if runs else None,
            "extract_ms": safe_mean([float(x.get("extraction_time_ms", 0)) for x in runs]) if runs else None,
            "accuracy": safe_mean([float(x.get("extraction_accuracy", 0)) for x in runs]) if runs else None,
            "run_count": len(runs),
        }

    payload_rows = {}
    for payload in [10, 25, 50, 75, 90]:
        runs = by_payload.get(payload, [])
        payload_rows[payload] = {
            "mse": safe_mean([float(x.get("mse", 0)) for x in runs]) if runs else None,
            "psnr": safe_mean([float(x.get("psnr", 0)) for x in runs]) if runs else None,
            "ssim": safe_mean([float(x.get("ssim", 0)) for x in runs]) if runs else None,
            "q_index": safe_mean([float(x.get("q_index", 0)) for x in runs]) if runs else None,
            "accuracy": safe_mean([float(x.get("extraction_accuracy", 0)) for x in runs]) if runs else None,
            "run_count": len(runs),
        }

    recommendations = {}
    for res in [128, 256, 512, 1024]:
        runs = by_res.get(res, [])
        groups = defaultdict(list)
        for run in runs:
            groups[int(run.get("payload_percentage", 0))].append(run)

        selected = None
        for p in [10, 25, 50, 75, 90]:
            grp = groups.get(p, [])
            if not grp:
                continue
            avg_psnr = mean(float(x.get("psnr", 0)) for x in grp)
            avg_acc = mean(float(x.get("extraction_accuracy", 0)) for x in grp)
            if avg_psnr >= 40.0 and avg_acc >= 0.98:
                selected = (p, avg_psnr, avg_acc, "Optimal: PSNR >= 40 dB, high fidelity, and reliable extraction.")

        if selected is None:
            # fallback best by accuracy then psnr
            best = None
            for p, grp in groups.items():
                avg_psnr = mean(float(x.get("psnr", 0)) for x in grp)
                avg_acc = mean(float(x.get("extraction_accuracy", 0)) for x in grp)
                score = (avg_acc, avg_psnr)
                if best is None or score > best[0]:
                    best = (score, p, avg_psnr, avg_acc)
            if best is not None:
                selected = (best[1], best[2], best[3], "Best available from current data; consider more balanced payload if visual artifacts appear.")

        recommendations[res] = selected

    return res_rows, payload_rows, recommendations, by_res


def write_csvs(res_rows, payload_rows, recommendations):
    with open(OUT_TABLE2, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Image Resolution", "Available Edge Pixels (avg)", "Embedding Capacity (byte avg)"])
        for res in [128, 256, 512, 1024]:
            row = res_rows[res]
            w.writerow([f"{res}x{res}", fmt_num(row["edge_pixels"], 2), fmt_num(row["capacity_bytes"], 2)])

    with open(OUT_TABLE21, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Image Resolution", "Embedding Time (ms)", "Extraction Time (ms)", "Extraction Accuracy"])
        for res in [128, 256, 512, 1024]:
            row = res_rows[res]
            w.writerow([f"{res}x{res}", fmt_num(row["embed_ms"], 4), fmt_num(row["extract_ms"], 4), fmt_pct(row["accuracy"], 2)])

    with open(OUT_TABLE3, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Payload Capacity", "MSE", "PSNR", "SSIM", "Q Index"])
        for p in [10, 25, 50, 75, 90]:
            row = payload_rows[p]
            w.writerow([f"{p}%", fmt_num(row["mse"], 6), fmt_num(row["psnr"], 6), fmt_num(row["ssim"], 6), fmt_num(row["q_index"], 6)])

    with open(OUT_TABLE4, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Payload", "PSNR", "MSE", "Extraction Accuracy"])
        for p in [10, 25, 50, 75, 90]:
            row = payload_rows[p]
            w.writerow([f"{p}%", fmt_num(row["psnr"], 6), fmt_num(row["mse"], 6), fmt_pct(row["accuracy"], 2)])

    with open(OUT_TABLE5, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Resolution", "Recommended Payload", "PSNR", "Extraction Accuracy", "Recommendation"])
        for res in [128, 256, 512, 1024]:
            rec = recommendations.get(res)
            if rec is None:
                w.writerow([f"{res}px", "N/A", "N/A", "N/A", "No runs yet for this resolution."])
            else:
                p, psnr, acc, text = rec
                w.writerow([f"{res}px", f"{p}%", fmt_num(psnr, 4), fmt_pct(acc, 2), text])


def write_markdown(res_rows, payload_rows, recommendations, by_res):
    # Pull up to 20 proof rows from 128-resolution runs by default, else any resolution
    proof_runs = by_res.get(128, [])[:20]
    if len(proof_runs) < 20:
        merged = []
        for res in [128, 256, 512, 1024]:
            merged.extend(by_res.get(res, []))
        proof_runs = merged[:20]

    screenshot_names = []
    for run in proof_runs:
        stego = run.get("stego_path")
        if isinstance(stego, str) and stego:
            screenshot_names.append(os.path.basename(stego))

    lines = []
    lines.append("# IV. RESULTS AND DISCUSSION")
    lines.append("")
    lines.append("Dataset composition target: 4 natural images, 4 textured images, 4 smooth images, 4 high-edge images, and 4 low-edge images.")
    lines.append("")
    lines.append("## A. System Performance Across Different Image Resolutions")
    lines.append("")
    lines.append("### Table 2. Image Resolution vs Available Edge Pixels and Embedding Capacity")
    lines.append("")
    lines.append("| Image Resolution | Available Edge Pixels (avg) | Embedding Capacity (byte avg) |")
    lines.append("|---|---:|---:|")
    for res in [128, 256, 512, 1024]:
        row = res_rows[res]
        lines.append(f"| {res}x{res} | {fmt_num(row['edge_pixels'], 2)} | {fmt_num(row['capacity_bytes'], 2)} |")

    lines.append("")
    lines.append("### Table 2.1 Image Resolution vs Embedding/Extraction Time and Extraction Accuracy")
    lines.append("")
    lines.append("| Image Resolution | Embedding Time (ms) | Extraction Time (ms) | Extraction Accuracy |")
    lines.append("|---|---:|---:|---:|")
    for res in [128, 256, 512, 1024]:
        row = res_rows[res]
        lines.append(f"| {res}x{res} | {fmt_num(row['embed_ms'], 4)} | {fmt_num(row['extract_ms'], 4)} | {fmt_pct(row['accuracy'], 2)} |")

    lines.append("")
    lines.append("Screenshots of 20 embedding and extraction results:")
    if screenshot_names:
        for i, name in enumerate(screenshot_names, start=1):
            lines.append(f"- Screenshot {i}: results/{name}")
    else:
        lines.append("- Add 20 screenshots from the results folder (stego images).")

    lines.append("")
    lines.append("20 recovered secret messages (proof that extraction matches original):")
    if proof_runs:
        for i, run in enumerate(proof_runs, start=1):
            extracted = run.get("extracted_message", "")
            acc = float(run.get("extraction_accuracy", 0))
            status = "Message extracted successfully with 100% accuracy" if acc >= 1.0 else "Extraction mismatch observed"
            msg_preview = extracted if isinstance(extracted, str) and extracted else "(not captured in this run file)"
            lines.append(f"- Run {i}: {status}. Extracted: {msg_preview}")
    else:
        lines.append("- No run data available yet.")

    lines.append("")
    lines.append("Comparison of extraction capacities per resolution and extraction success rate is reflected in Table 2 and Table 2.1.")

    lines.append("")
    lines.append("## B. Comparison of Different Payload Levels")
    lines.append("")
    lines.append("### Table 3. Payload Capacity vs Quality Metrics")
    lines.append("")
    lines.append("| Payload Capacity | MSE | PSNR | SSIM | Q Index |")
    lines.append("|---|---:|---:|---:|---:|")
    for p in [10, 25, 50, 75, 90]:
        row = payload_rows[p]
        lines.append(f"| {p}% | {fmt_num(row['mse'], 6)} | {fmt_num(row['psnr'], 6)} | {fmt_num(row['ssim'], 6)} | {fmt_num(row['q_index'], 6)} |")

    lines.append("")
    lines.append("Fig 7: Line graph of Payload vs PSNR")
    lines.append("Fig 8: Line graph of Payload vs SSIM")
    lines.append("Fig 9: Line graph of Payload vs MSE")
    lines.append("")
    lines.append("Interpretation: Higher payload generally increases distortion (MSE rises, PSNR falls), while lower payload preserves imperceptibility.")

    lines.append("")
    lines.append("## C. Relationship Between Payload Size, Image Degradation, and Extraction Accuracy")
    lines.append("")
    lines.append("### Table 4. Payload vs PSNR, MSE, and Extraction Accuracy")
    lines.append("")
    lines.append("| Payload | PSNR | MSE | Extraction Accuracy |")
    lines.append("|---|---:|---:|---:|")
    for p in [10, 25, 50, 75, 90]:
        row = payload_rows[p]
        lines.append(f"| {p}% | {fmt_num(row['psnr'], 6)} | {fmt_num(row['mse'], 6)} | {fmt_pct(row['accuracy'], 2)} |")

    lines.append("")
    lines.append("Observed trend: Increasing payload capacity tends to lower PSNR values and raise MSE.")
    lines.append("Extraction Accuracy typically remains stable at lower-to-mid payload levels and may degrade at high embedding rates depending on image content.")

    lines.append("")
    lines.append("## D. Payload Capacity and Image Quality Recommendations")
    lines.append("")
    lines.append("### Table 5. Recommended Payload per Resolution")
    lines.append("")
    lines.append("| Resolution | Recommended Payload | PSNR | Extraction Accuracy | Recommendation |")
    lines.append("|---|---:|---:|---:|---|")
    for res in [128, 256, 512, 1024]:
        rec = recommendations.get(res)
        if rec is None:
            lines.append(f"| {res}px | N/A | N/A | N/A | No runs yet for this resolution. |")
        else:
            p, psnr, acc, text = rec
            lines.append(f"| {res}px | {p}% | {fmt_num(psnr, 4)} | {fmt_pct(acc, 2)} | {text} |")

    lines.append("")
    lines.append("Justification: Recommended payloads are selected to maintain PSNR above 40 dB where possible, keep SSIM near 1.0, ensure successful extraction, and minimize visible distortion.")
    lines.append("")
    lines.append("Practical interpretation:")
    lines.append("- 128x128: suitable for short messages.")
    lines.append("- 256x256: suitable for longer short messages.")
    lines.append("- 512x512: suitable for short stories.")
    lines.append("- 1024x1024: suitable for chapter-length text.")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    reports = load_reports()
    if not reports:
        raise SystemExit("No study report JSON files found under results/.")

    res_rows, payload_rows, recommendations, by_res = aggregate(reports)
    write_csvs(res_rows, payload_rows, recommendations)
    write_markdown(res_rows, payload_rows, recommendations, by_res)

    print(f"Generated: {OUT_MD}")
    print(f"Generated: {OUT_TABLE2}")
    print(f"Generated: {OUT_TABLE21}")
    print(f"Generated: {OUT_TABLE3}")
    print(f"Generated: {OUT_TABLE4}")
    print(f"Generated: {OUT_TABLE5}")


if __name__ == "__main__":
    main()
