import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def _save_plot(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()
    return path


def generate_payload_metric_graph(simulations: list[dict], metric_key: str, title: str, ylabel: str, output_path: str) -> str:
    payloads = []
    values = []
    for sim in simulations:
        payload = sim.get("payload_percentage", sim.get("payload_size_kb"))
        metric = (sim.get("metrics") or {}).get(metric_key)
        if isinstance(payload, (int, float)) and isinstance(metric, (int, float)):
            payloads.append(payload)
            values.append(metric)

    plt.figure(figsize=(6, 4))
    plt.scatter(payloads, values, c="#3498db")
    if len(payloads) > 1:
        paired = sorted(zip(payloads, values), key=lambda p: p[0])
        plt.plot([p[0] for p in paired], [p[1] for p in paired], color="#2c3e50")
    plt.title(title)
    plt.xlabel("Payload Capacity (%)")
    plt.ylabel(ylabel)
    plt.grid(alpha=0.3)
    return _save_plot(output_path)


def generate_accuracy_graph(simulations: list[dict], output_path: str) -> str:
    payloads, accuracies = [], []
    for sim in simulations:
        payload = sim.get("payload_percentage", sim.get("payload_size_kb"))
        acc = sim.get("extraction_accuracy")
        if isinstance(payload, (int, float)) and isinstance(acc, (int, float)):
            payloads.append(payload)
            accuracies.append(acc)

    plt.figure(figsize=(6, 4))
    plt.scatter(payloads, accuracies, c="#27ae60")
    plt.title("Payload Capacity vs Extraction Accuracy")
    plt.xlabel("Payload Capacity (%)")
    plt.ylabel("Extraction Accuracy (%)")
    plt.grid(alpha=0.3)
    return _save_plot(output_path)


def generate_embedding_time_graph(simulations: list[dict], output_path: str) -> str:
    payloads, times = [], []
    for sim in simulations:
        payload = sim.get("payload_percentage", sim.get("payload_size_kb"))
        timing = sim.get("embedding_time_ms")
        if isinstance(payload, (int, float)) and isinstance(timing, (int, float)):
            payloads.append(payload)
            times.append(timing)

    plt.figure(figsize=(6, 4))
    plt.scatter(payloads, times, c="#f39c12")
    plt.title("Payload Capacity vs Embedding Time")
    plt.xlabel("Payload Capacity (%)")
    plt.ylabel("Embedding Time (ms)")
    plt.grid(alpha=0.3)
    return _save_plot(output_path)


def generate_histogram_comparison(original_path: str, stego_path: str, output_path: str) -> str:
    with Image.open(original_path) as orig:
        o = np.array(orig.convert("RGB"))
    with Image.open(stego_path) as stego:
        s = np.array(stego.convert("RGB"))

    plt.figure(figsize=(7, 4))
    for i, color in enumerate(["r", "g", "b"]):
        plt.hist(o[:, :, i].ravel(), bins=256, alpha=0.25, color=color, label=f"Original {color.upper()}")
        plt.hist(s[:, :, i].ravel(), bins=256, alpha=0.25, histtype="step", color=color, linestyle="--", label=f"Stego {color.upper()}")
    plt.title("Histogram Comparison: Original vs Stego")
    plt.xlabel("Pixel Value")
    plt.ylabel("Frequency")
    plt.legend(fontsize=7)
    return _save_plot(output_path)
