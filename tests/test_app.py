import io
import unittest

from PIL import Image

from app import create_app


class XectApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def _sample_png(self):
        image = Image.new("RGB", (128, 128), color=(120, 80, 200))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        return buf

    def test_simulations_endpoint(self):
        response = self.client.get("/api/simulations")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("simulations", payload)
        self.assertGreaterEqual(len(payload["simulations"]), 1)

    def test_encode_decode_flow(self):
        upload = self.client.post(
            "/api/upload-image",
            data={"simulation_id": "1", "image": (self._sample_png(), "test.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)

        encode = self.client.post(
            "/api/encode",
            json={"simulation_id": 1, "payload_size_kb": 1, "secret_message": "hello xect"},
        )
        self.assertEqual(encode.status_code, 200)

        decode = self.client.post("/api/decode", json={"simulation_id": 1})
        self.assertEqual(decode.status_code, 200)
        sim = decode.get_json()["simulation"]
        self.assertEqual(sim["extracted_message"], "hello xect")
        self.assertIsInstance(sim["extraction_accuracy"], float)

    def test_lock_blocks_rerun(self):
        upload = self.client.post(
            "/api/upload-image",
            data={"simulation_id": "2", "image": (self._sample_png(), "test.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)
        lock = self.client.post("/api/lock-simulation/2")
        self.assertEqual(lock.status_code, 200)

        encode = self.client.post(
            "/api/encode",
            json={"simulation_id": 2, "payload_size_kb": 1, "secret_message": "blocked"},
        )
        self.assertEqual(encode.status_code, 409)


if __name__ == "__main__":
    unittest.main()
