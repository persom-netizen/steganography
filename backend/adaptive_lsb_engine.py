from __future__ import annotations

from typing import Iterable

import numpy as np
from PIL import Image

from backend.lsb_engine import LSBError, extraction_accuracy, validate_image
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


def build_bit_allocation_map(image_array: np.ndarray) -> np.ndarray:
    complexity = calculate_complexity_map(image_array)
    allocation = np.zeros_like(complexity, dtype=np.uint8)
    allocation[(complexity >= 0.3) & (complexity < 0.5)] = 2
    allocation[(complexity >= 0.5) & (complexity < 0.7)] = 3
    allocation[complexity >= 0.7] = 4
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


def analyze_image_capacity(input_path: str) -> dict:
    image_array = _load_rgb(input_path)
    complexity_map = calculate_complexity_map(image_array)
    allocation_map = build_bit_allocation_map(image_array)
    capacity_bits = int(np.sum(allocation_map, dtype=np.int64))
    return {
        "dimensions": list(image_array.shape[:2]),
        "capacity_bits": capacity_bits,
        "capacity_bytes": max((capacity_bits - HEADER_BITS) // 8, 0),
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


def encode_message_in_image(input_path: str, message: str, output_path: str) -> tuple[int, int]:
    image_array = _load_rgb(input_path)
    complexity_map = calculate_complexity_map(image_array)
    allocation_map = build_bit_allocation_map(image_array)
    capacity_bits = int(np.sum(allocation_map, dtype=np.int64))
    max_capacity_bytes = max((capacity_bits - HEADER_BITS) // 8, 0)

    payload = message.encode("utf-8")
    if len(payload) > max_capacity_bytes:
        raise LSBError("Payload exceeds adaptive capacity")

    bits = _to_bits(len(payload).to_bytes(HEADER_BYTES, byteorder="big") + payload)
    if len(bits) > capacity_bits:
        raise LSBError("Payload exceeds adaptive capacity")

    stego = image_array.copy()
    bit_index = 0
    for y, x, channel, plane in _iter_embedding_positions(complexity_map, allocation_map):
        if bit_index >= len(bits):
            break
        mask = 1 << plane
        stego[y, x, channel] = (stego[y, x, channel] & (~mask & 0xFF)) | (int(bits[bit_index]) << plane)
        bit_index += 1

    if bit_index != len(bits):
        raise LSBError("Adaptive embedding did not complete")

    Image.fromarray(stego, mode="RGB").save(output_path)
    return len(payload), max_capacity_bytes


def decode_message_from_image(stego_path: str, cover_path: str | None = None) -> str:
    stego_array = _load_rgb(stego_path)
    reference_array = _load_rgb(cover_path) if cover_path else stego_array
    complexity_map = calculate_complexity_map(reference_array)
    allocation_map = build_bit_allocation_map(reference_array)
    ordered_positions = _iter_embedding_positions(complexity_map, allocation_map)

    header_bits = []
    for _ in range(HEADER_BITS):
        try:
            y, x, channel, plane = next(ordered_positions)
        except StopIteration as exc:
            raise LSBError("Insufficient adaptive header capacity") from exc
        header_bits.append(str((stego_array[y, x, channel] >> plane) & 1))

    payload_length = int("".join(header_bits), 2)
    max_capacity_bytes = max((int(np.sum(allocation_map, dtype=np.int64)) - HEADER_BITS) // 8, 0)
    if payload_length < 0 or payload_length > max_capacity_bytes:
        raise LSBError("Invalid adaptive payload length")

    payload_bits = []
    for _ in range(payload_length * 8):
        try:
            y, x, channel, plane = next(ordered_positions)
        except StopIteration as exc:
            raise LSBError("Adaptive payload is truncated") from exc
        payload_bits.append(str((stego_array[y, x, channel] >> plane) & 1))

    return _from_bits("".join(payload_bits)).decode("utf-8", errors="replace")
