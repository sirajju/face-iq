from pathlib import Path
import cv2
import numpy as np

BASE = Path(__file__).resolve().parents[1]
DETECTOR_PATH = BASE / "models" / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_PATH = BASE / "models" / "face_recognition_sface_2021dec.onnx"

class Vision:
    def __init__(self):
        if not DETECTOR_PATH.exists() or not RECOGNIZER_PATH.exists():
            raise RuntimeError("Face models missing. Run: python download_models.py")
        # Lower score threshold (0.55) so faces that are turned away or at an
        # angle — i.e. not looking straight at the camera — are still detected
        # and tracked, instead of being dropped by the stricter 0.75 default.
        self.detector = cv2.FaceDetectorYN.create(
            str(DETECTOR_PATH), "", (320, 320), 0.55, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_PATH), "")

    def analyze(self, image_bytes):
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Invalid image frame")
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)
        results = []
        if faces is None:
            return image, results
        for face in faces:
            x, y, fw, fh = [int(v) for v in face[:4]]
            x, y = max(0, x), max(0, y)
            fw, fh = min(fw, w - x), min(fh, h - y)
            aligned = self.recognizer.alignCrop(image, face)
            feature = self.recognizer.feature(aligned).flatten().astype(np.float32)
            feature /= (np.linalg.norm(feature) + 1e-12)
            # Approximate expression signal from face geometry; not a mood detector.
            # YuNet layout: bbox [0:4], right eye [4:6], left eye [6:8],
            # nose tip [8:10], right mouth corner [10:12], left mouth corner [12:14], score [14].
            rx, ry = face[10], face[11]
            lx, ly = face[12], face[13]
            mouth_width = float(np.hypot(lx-rx, ly-ry))
            mouth_y = (ry + ly) / 2
            nose_y = float(face[9])
            vertical = max(1.0, mouth_y - nose_y)
            ratio = mouth_width / vertical
            expression = "Possible smile" if ratio > 1.45 else "Neutral / unclear"
            # Head-orientation estimate from eye/nose geometry (yaw only).
            # right eye [4:6], left eye [6:8], nose tip [8:10].
            reye_x, leye_x = float(face[4]), float(face[6])
            nose_x = float(face[8])
            eye_center_x = (reye_x + leye_x) / 2.0
            eye_span = abs(leye_x - reye_x)
            # Normalised sideways offset of the nose relative to the eye midpoint.
            yaw = (nose_x - eye_center_x) / (eye_span + 1e-6)
            if abs(yaw) <= 0.18:
                facing = "Looking at camera"
            elif abs(yaw) <= 0.45:
                facing = "Turned to the side"
            else:
                facing = "Looking away"
            results.append({
                "box": {"x": x, "y": y, "width": fw, "height": fh},
                "embedding": feature.tolist(),
                "expression": expression,
                "expression_note": "Rough geometry estimate only; not a reliable mood assessment.",
                "facing": facing,
                "detection_score": round(float(face[14]), 3),
            })
        return image, results
