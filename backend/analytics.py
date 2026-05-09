def aggregate_statistics(simulations: list[dict]) -> dict:
    metric_keys = ["mse", "psnr", "ssim", "q_index", "embedding_time_ms", "extraction_accuracy"]
    aggregates = {}

    for key in metric_keys:
        values = []
        for sim in simulations:
            if key in ("embedding_time_ms", "extraction_accuracy"):
                value = sim.get(key)
            else:
                value = (sim.get("metrics") or {}).get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        aggregates[key] = {
            "count": len(values),
            "average": (sum(values) / len(values)) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }

    return aggregates
