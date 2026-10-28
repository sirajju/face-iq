from pathlib import Path
from urllib.request import urlretrieve

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

MODELS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

for filename, url in MODELS.items():
    target = MODEL_DIR / filename
    if target.exists() and target.stat().st_size > 100_000:
        print(f"Already downloaded: {target}")
        continue
    print(f"Downloading {filename} ...")
    urlretrieve(url, target)
    if target.stat().st_size < 100_000:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Download seems incomplete: {filename}")
    print(f"Saved: {target}")
print("Models ready.")
