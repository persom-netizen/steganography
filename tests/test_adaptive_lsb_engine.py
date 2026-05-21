import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from backend.adaptive_lsb_engine import (
    analyze_image_capacity,
    calculate_payload_bytes,
    decode_message_from_image,
    encode_message_in_image,
)
from backend.metrics import compute_metrics
from config import Config


class AdaptiveLsbEngineTestCase(unittest.TestCase):
    def setUp(self):
        self._temp_paths = []

    def tearDown(self):
        for path in self._temp_paths:
            if os.path.exists(path):
                os.remove(path)

    def _image_path(self, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, dir=Config.UPLOAD_FOLDER)
        os.close(fd)
        self._temp_paths.append(path)
        return path

    def _result_path(self, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, dir=Config.RESULTS_FOLDER)
        os.close(fd)
        self._temp_paths.append(path)
        return path

    def _create_cover_image(self, resolution: int) -> str:
        grid_y, grid_x = np.indices((resolution, resolution))
        image = np.zeros((resolution, resolution, 3), dtype=np.uint8)
        image[..., 0] = (grid_x * 7 + grid_y * 5) % 256
        image[..., 1] = ((grid_x ^ grid_y) * 13) % 256
        image[..., 2] = ((grid_x * grid_y) + (grid_x * 3) + (grid_y * 11)) % 256
        path = self._image_path(".png")
        Image.fromarray(image, mode="RGB").save(path)
        return path

    def _payload_message(self, size: int) -> str:
        payload = (b"AdaptiveLSB:" * ((size // 12) + 1))[:size]
        return payload.decode("utf-8", errors="ignore")

    def test_all_resolution_payload_combinations_round_trip(self):
        for resolution in Config.SUPPORTED_RESOLUTIONS:
            cover_path = self._create_cover_image(resolution)
            capacity = analyze_image_capacity(cover_path)
            self.assertGreater(capacity["capacity_bytes"], 0)

            for percentage in Config.PAYLOAD_OPTIONS_PERCENT:
                with self.subTest(resolution=resolution, percentage=percentage):
                    stego_path = self._result_path(".png")
                    payload_bytes = calculate_payload_bytes(capacity["capacity_bytes"], percentage)
                    message = self._payload_message(payload_bytes)

                    embedded_bytes, max_capacity_bytes = encode_message_in_image(cover_path, message, stego_path)
                    extracted = decode_message_from_image(stego_path, cover_path)
                    metrics = compute_metrics(cover_path, stego_path)

                    self.assertEqual(embedded_bytes, len(message.encode("utf-8")))
                    self.assertEqual(max_capacity_bytes, capacity["capacity_bytes"])
                    self.assertEqual(extracted, message)
                    self.assertEqual(set(metrics.keys()), {"mse", "psnr", "ssim", "q_index"})
                    self.assertGreaterEqual(metrics["mse"], 0.0)
                    self.assertGreaterEqual(metrics["ssim"], 0.0)
                    self.assertGreaterEqual(metrics["q_index"], 0.0)
