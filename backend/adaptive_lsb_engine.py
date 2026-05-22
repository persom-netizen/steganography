from __future__ import annotations

import json
from typing import Iterable

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from backend.lsb_engine import LSBError, validate_image
from config import Config

HEADER_BYTES = 4
HEADER_BITS = HEADER_BYTES * 8
_BIT_POSITIONS = ((0, 0), (1, 0), (2, 0), (0, 1))


def _to_bits(data: bytes) -> str:
    return "".join(format(byte, "08b") for byte in data)


def _from_bits(bit_string: str) -> bytes:
    if len(bit_string) % 8:
        bit_string = bit_string[: len(bit_string) - (len(bit_string) % 8)]
    return bytes(int(bit_string[i : i + 8], 2) for i in range(0, len(bit_string), 8))


def _load_rgb(path: str) -> np.ndarray:
    validate_image(path)
    with Image.open(path) as img:
        return np.array(img.convert("RGB"), dtype=np.uint8)


def _to_gray(image_array: np.ndarray) -> np.ndarray:
    image = image_array.astype(np.float64)
    return 0.299 * image[..., 0] + 0.587 * image[..., 1] + 0.114 * image[..., 2]


def _normalize(arr: np.ndarray) -> np.ndarray:
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))
    if max_val - min_val <= 1e-12:
        return np.zeros_like(arr, dtype=np.float64)
    return (arr - min_val) / (max_val - min_val)


def _clamp_threshold(value: float | int | None, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return float(min(max(numeric, 0.0), 1.0))


def _resolve_threshold_range(lower_threshold: float | int | None, upper_threshold: float | int | None) -> tuple[float, float]:
    lower = _clamp_threshold(lower_threshold, 0.3)
    upper = _clamp_threshold(upper_threshold, 0.7)
    if upper < lower:
        lower, upper = upper, lower
    if abs(upper - lower) < 1e-6:
        upper = min(1.0, lower + 0.1)
    return lower, upper


def _box_mean(arr: np.ndarray, radius: int = 1) -> np.ndarray:
    kernel = radius * 2 + 1
    padded = np.pad(arr, radius, mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(axis=0).cumsum(axis=1)
    area_sum = (
        integral[kernel:, kernel:]
        - integral[:-kernel, kernel:]
        - integral[kernel:, :-kernel]
        + integral[:-kernel, :-kernel]
    )
    return area_sum / float(kernel * kernel)


def calculate_complexity_map(image_array: np.ndarray) -> np.ndarray:
    gray = _to_gray(image_array)
    padded = np.pad(gray, 1, mode="edge")
    laplacian = (
        padded[:-2, 1:-1]
        + padded[2:, 1:-1]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
        - (4.0 * padded[1:-1, 1:-1])
    )
    edge_score = _normalize(np.abs(laplacian))

    local_mean = _box_mean(gray, radius=1)
    local_sq_mean = _box_mean(gray**2, radius=1)
    local_variance = np.clip(local_sq_mean - (local_mean**2), 0.0, None)
    texture_score = _normalize(local_variance)

    return np.clip((0.6 * edge_score) + (0.4 * texture_score), 0.0, 1.0)


def calculate_edge_map(image_array: np.ndarray, lower_threshold: float | int | None = 0.3, upper_threshold: float | int | None = 0.7) -> np.ndarray:
    complexity = calculate_complexity_map(image_array)
    lower, upper = _resolve_threshold_range(lower_threshold, upper_threshold)
    edge_map = np.zeros_like(complexity, dtype=np.uint8)
    mid = lower + ((upper - lower) / 2.0)
    edge_map[(complexity >= lower) & (complexity < mid)] = 85
    edge_map[(complexity >= mid) & (complexity < upper)] = 170
    edge_map[complexity >= upper] = 255
    return edge_map


def build_bit_allocation_map(
    image_array: np.ndarray,
    lower_threshold: float | int | None = 0.3,
    upper_threshold: float | int | None = 0.7,
    bit_depth: int = 4,
) -> np.ndarray:
    complexity = calculate_complexity_map(image_array)
    lower, upper = _resolve_threshold_range(lower_threshold, upper_threshold)
    bit_depth = int(np.clip(bit_depth, 1, len(_BIT_POSITIONS)))
    allocation = np.zeros_like(complexity, dtype=np.uint8)
    mid = lower + ((upper - lower) / 2.0)
    allocation[(complexity >= lower) & (complexity < mid)] = min(1, bit_depth)
    allocation[(complexity >= mid) & (complexity < upper)] = min(2, bit_depth)
    allocation[complexity >= upper] = bit_depth
    return allocation


def _ordered_pixels(complexity_map: np.ndarray, allocation_map: np.ndarray) -> np.ndarray:
    flat_allocation = allocation_map.reshape(-1)
    flat_complexity = complexity_map.reshape(-1)
    candidates = np.flatnonzero(flat_allocation)
    if not len(candidates):
        return candidates
    return candidates[np.argsort(flat_complexity[candidates], kind="stable")[::-1]]


def _iter_embedding_positions(complexity_map: np.ndarray, allocation_map: np.ndarray) -> Iterable[tuple[int, int, int, int]]:
    width = allocation_map.shape[1]
    for pixel_index in _ordered_pixels(complexity_map, allocation_map):
        y, x = divmod(int(pixel_index), width)
        bit_count = int(allocation_map[y, x])
        for channel, plane in _BIT_POSITIONS[:bit_count]:
            yield y, x, channel, plane


def _serialize_embedding_positions(positions: list[tuple[int, int, int, int]]) -> str:
    return json.dumps(positions, separators=(",", ":"))


def _deserialize_embedding_positions(raw_value: str) -> list[tuple[int, int, int, int]]:
    data = json.loads(raw_value)
    return [tuple(int(value) for value in item) for item in data]


def analyze_image_capacity(
    input_path: str,
    lower_threshold: float | int | None = 0.3,
    upper_threshold: float | int | None = 0.7,
    bit_depth: int = 4,
) -> dict:
    image_array = _load_rgb(input_path)
    complexity_map = calculate_complexity_map(image_array)
    allocation_map = build_bit_allocation_map(image_array, lower_threshold, upper_threshold, bit_depth)
    capacity_bits = int(np.sum(allocation_map, dtype=np.int64))
    return {
        "dimensions": list(image_array.shape[:2]),
        "capacity_bits": capacity_bits,
        "capacity_bytes": max((capacity_bits - HEADER_BITS) // 8, 0),
        "edge_pixel_count": int(np.count_nonzero(allocation_map)),
        "allocation_summary": {
            "skip_pixels": int(np.count_nonzero(allocation_map == 0)),
            "two_bit_pixels": int(np.count_nonzero(allocation_map == 2)),
            "three_bit_pixels": int(np.count_nonzero(allocation_map == 3)),
            "four_bit_pixels": int(np.count_nonzero(allocation_map == 4)),
        },
        "complexity_range": [float(np.min(complexity_map)), float(np.max(complexity_map))],
    }


def calculate_payload_bytes(max_capacity_bytes: int, payload_percentage: int) -> int:
    if payload_percentage not in Config.PAYLOAD_OPTIONS_PERCENT:
        raise LSBError("Unsupported payload percentage")
    if max_capacity_bytes <= 0:
        return 0
    return max(1, (max_capacity_bytes * int(payload_percentage)) // 100)


def calculate_resolution_capacity(resolution: int, input_path: str) -> int:
    width, height, _ = validate_image(input_path)
    if width != resolution or height != resolution:
        raise LSBError("Image does not match the requested resolution")
    return analyze_image_capacity(input_path)["capacity_bytes"]


def encode_message_in_image(
    input_path: str,
    message: str,
    output_path: str,
    lower_threshold: float | int | None = 0.3,
    upper_threshold: float | int | None = 0.7,
    bit_depth: int = 4,
) -> tuple[int, int]:
    image_array = _load_rgb(input_path)
    complexity_map = calculate_complexity_map(image_array)
    allocation_map = build_bit_allocation_map(image_array, lower_threshold, upper_threshold, bit_depth)
    capacity_bits = int(np.sum(allocation_map, dtype=np.int64))
    max_capacity_bytes = max((capacity_bits - HEADER_BITS) // 8, 0)
    ordered_positions = list(_iter_embedding_positions(complexity_map, allocation_map))

    payload = message.encode("utf-8")
    if len(payload) > max_capacity_bytes:
        raise LSBError("Payload exceeds adaptive capacity")

    bits = _to_bits(len(payload).to_bytes(HEADER_BYTES, byteorder="big") + payload)
    if len(bits) > len(ordered_positions):
        raise LSBError("Payload exceeds adaptive capacity")

    stego = image_array.copy()
    for bit_index, (y, x, channel, plane) in enumerate(ordered_positions[: len(bits)]):
        mask = 1 << plane
        stego[y, x, channel] = (stego[y, x, channel] & (~mask & 0xFF)) | (int(bits[bit_index]) << plane)

    image = Image.fromarray(stego, mode="RGB")
    if output_path.lower().endswith(".png"):
        metadata = PngInfo()
        metadata.add_text("xect_embedding_positions", _serialize_embedding_positions(ordered_positions), zip=True)
        metadata.add_text("xect_embedding_version", "1", zip=True)
        image.save(output_path, pnginfo=metadata)
    else:
        image.save(output_path)
    return len(payload), max_capacity_bytes


def save_edge_map_image(
    input_path: str,
    output_path: str,
    lower_threshold: float | int | None = 0.3,
    upper_threshold: float | int | None = 0.7,
) -> str:
    image_array = _load_rgb(input_path)
    edge_map = calculate_edge_map(image_array, lower_threshold, upper_threshold)
    Image.fromarray(edge_map, mode="L").save(output_path)
    return output_path


def save_difference_image(original_path: str, stego_path: str, output_path: str, amplify: int = 12) -> str:
    original = _load_rgb(original_path).astype(np.int16)
    stego = _load_rgb(stego_path).astype(np.int16)
    difference = np.abs(stego - original)
    amplified = np.clip(difference * int(max(amplify, 1)), 0, 255).astype(np.uint8)
    Image.fromarray(amplified, mode="RGB").save(output_path)
    return output_path


def decode_message_from_image(
    stego_path: str,
    cover_path: str | None = None,
    lower_threshold: float | int | None = 0.3,
    upper_threshold: float | int | None = 0.7,
    bit_depth: int = 4,
) -> str:
    stego_array = _load_rgb(stego_path)
    if cover_path:
        reference_array = _load_rgb(cover_path)
        complexity_map = calculate_complexity_map(reference_array)
        allocation_map = build_bit_allocation_map(reference_array, lower_threshold, upper_threshold, bit_depth)
        ordered_positions = _iter_embedding_positions(complexity_map, allocation_map)
        max_capacity_bytes = max((int(np.sum(allocation_map, dtype=np.int64)) - HEADER_BITS) // 8, 0)
    else:
        with Image.open(stego_path) as image:
            embedding_positions_raw = image.info.get("xect_embedding_positions")
        if not embedding_positions_raw:
            raise LSBError("Missing embedding metadata for coverless decode")
        ordered_positions = iter(_deserialize_embedding_positions(embedding_positions_raw))
        max_capacity_bytes = None

    header_bits = []
    for _ in range(HEADER_BITS):
        try:
            y, x, channel, plane = next(ordered_positions)
        except StopIteration as exc:
            raise LSBError("Insufficient adaptive header capacity") from exc
        header_bits.append(str((stego_array[y, x, channel] >> plane) & 1))

    payload_length = int("".join(header_bits), 2)
    if max_capacity_bytes is not None and (payload_length < 0 or payload_length > max_capacity_bytes):
        raise LSBError("Invalid adaptive payload length")

    payload_bits = []
    for _ in range(payload_length * 8):
        try:
            y, x, channel, plane = next(ordered_positions)
        except StopIteration as exc:
            raise LSBError("Adaptive payload is truncated") from exc
        payload_bits.append(str((stego_array[y, x, channel] >> plane) & 1))

    return _from_bits("".join(payload_bits)).decode("utf-8", errors="replace")
