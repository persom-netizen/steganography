# Xect - Image Steganography Pipeline

A compact web-based laboratory pipeline for adaptive LSB steganography experiments.

## Pipeline

1. Upload a standard RGB cover image.
2. Adjust edge thresholds to regenerate the edge map.
3. Enter uncompressed text or load a `.txt` payload, then choose payload percentage and bit depth.
4. Run the simulation to generate the stego image and amplified difference image.

## What the system shows

- Original cover image
- Generated edge map
- Final stego image
- Amplified difference image
- Capacity summary based on image size and payload percentage

## Run

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`
