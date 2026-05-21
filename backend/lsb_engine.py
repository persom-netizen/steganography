import os
from typing import Tuple

import numpy as np
from PIL import Image

from config import Config


class LSBError(Exception):
    pass


def _resolve_safe_path(path: str) -> str:
    candidate = os.path.abspath(path)
    allowed_roots = [os.path.abspath(Config.UPLOAD_FOLDER), os.path.abspath(Config.RESULTS_FOLDER)]
    try:
        is_allowed = any(os.path.commonpath([root, candidate]) == root for root in allowed_roots)
    except ValueError:
        is_allowed = False
    if not is_allowed:
        raise LSBError("Invalid image path")
    return candidate


def validate_image(path: str) -> Tuple[int, int, str]:
    safe_path = _resolve_safe_path(path)
    if not os.path.exists(safe_path):
        raise LSBError("Image file does not exist")
    with Image.open(safe_path) as img:
        fmt = (img.format or "").upper()
        if fmt not in Config.ALLOWED_FORMATS:
            raise LSBError("Invalid image format. Only PNG and BMP are allowed")
        width, height = img.size
        if width < Config.MIN_DIMENSION or height < Config.MIN_DIMENSION:
            raise LSBError("Image dimensions are too small")
        if width > Config.MAX_DIMENSION or height > Config.MAX_DIMENSION:
            raise LSBError("Image dimensions are too large")
        if width != height or width not in Config.SUPPORTED_RESOLUTIONS:
            raise LSBError(f"Unsupported image resolution. Use square images with one of {Config.SUPPORTED_RESOLUTIONS}")
        return width, height, fmt


def get_capacity_bits(image_array: np.ndarray) -> int:
    return int(image_array.size)


def _to_bits(data: bytes) -> str:
    return "".join(format(byte, "08b") for byte in data)


def _from_bits(bit_string: str) -> bytes:
    if len(bit_string) % 8:
        bit_string = bit_string[: len(bit_string) - (len(bit_string) % 8)]
    return bytes(int(bit_string[i : i + 8], 2) for i in range(0, len(bit_string), 8))


def encode_message_in_image(input_path: str, message: str, output_path: str) -> Tuple[int, int]:
    with Image.open(input_path) as img:
        rgb = img.convert("RGB")
        arr = np.array(rgb)

    payload = message.encode("utf-8")
    header = len(payload).to_bytes(4, byteorder="big")
    bits = _to_bits(header + payload)

    flat = arr.reshape(-1).copy()
    capacity = get_capacity_bits(flat)
    if len(bits) > capacity:
        raise LSBError("Payload exceeds image capacity")

    for i, bit in enumerate(bits):
        flat[i] = (flat[i] & 0xFE) | int(bit)

    stego = flat.reshape(arr.shape)
    Image.fromarray(stego.astype(np.uint8), mode="RGB").save(output_path)
    return len(payload), capacity // 8


def decode_message_from_image(stego_path: str) -> str:
    with Image.open(stego_path) as img:
        arr = np.array(img.convert("RGB")).reshape(-1)

    header_bits = "".join(str(arr[i] & 1) for i in range(32))
    payload_len = int(header_bits, 2)
    max_payload_len = (len(arr) - 32) // 8
    if payload_len < 0 or payload_len > max_payload_len:
        raise LSBError("Invalid payload length in stego image")
    payload_bits_len = payload_len * 8

    if 32 + payload_bits_len > len(arr):
        raise LSBError("Invalid stego image or corrupted payload")

    payload_bits = "".join(str(arr[i] & 1) for i in range(32, 32 + payload_bits_len))
    payload = _from_bits(payload_bits)
    return payload.decode("utf-8", errors="replace")


def extraction_accuracy(original_message: str, extracted_message: str) -> float:
    original = original_message.encode("utf-8")
    extracted = extracted_message.encode("utf-8")
    max_len = max(len(original), len(extracted))
    if max_len == 0:
        return 100.0

    original_bits = _to_bits(original)
    extracted_bits = _to_bits(extracted)
    max_bits = max(len(original_bits), len(extracted_bits))
    original_bits = original_bits.ljust(max_bits, "0")
    extracted_bits = extracted_bits.ljust(max_bits, "0")
    matches = sum(1 for i in range(max_bits) if original_bits[i] == extracted_bits[i])
    return round((matches / max_bits) * 100, 4)
