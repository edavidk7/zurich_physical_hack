from __future__ import annotations

import io
import logging
import platform
import time
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter

try:
    from src.constants import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_JPEG_QUALITY
except ImportError:
    from constants import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_JPEG_QUALITY

_IS_LINUX = platform.system() == "Linux"

if _IS_LINUX:
    from v4l2py import Device
    from v4l2py.device import BufferType, PixelFormat
else:
    import cv2

logger = logging.getLogger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"


@dataclass
class CameraConfig:
    index: int = 0
    width: int = CAMERA_WIDTH
    height: int = CAMERA_HEIGHT
    warmup_frames: int = 15
    jpeg_quality: int = CAMERA_JPEG_QUALITY
    software_sharpen: float = 2.0   # 1.0 = off, 2.0 = noticeable, 4.0 = strong


class _BaseCameraCapture:
    """
    Capture a single JPEG frame from a camera with optional software sharpening.

    Usage::

        with CameraCapture(CameraConfig(index=0)) as cam:
            jpeg: bytes = cam.capture_jpeg()
            img:  Image = cam.capture_image()
    """

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def _capture_raw_image(self) -> Image.Image:
        raise NotImplementedError

    def capture_jpeg(self) -> bytes:
        img = self._capture_raw_image()
        img = ImageEnhance.Sharpness(img).enhance(self.config.software_sharpen)
        img = img.filter(ImageFilter.SHARPEN)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.config.jpeg_quality)
        return buf.getvalue()

    def capture_image(self) -> Image.Image:
        return Image.open(io.BytesIO(self.capture_jpeg())).convert("RGB")

    def __enter__(self) -> "_BaseCameraCapture":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()


class _V4L2CameraCapture(_BaseCameraCapture):
    """Linux V4L2 backend."""

    def __init__(self, config: CameraConfig | None = None) -> None:
        super().__init__(config)
        self._device: Device | None = None
        self._stream: iter | None = None
        self._mjpeg = False

    def open(self) -> None:
        if self._device is not None:
            return
        device = Device.from_id(self.config.index)
        device.open()
        try:
            device.set_format(
                BufferType.VIDEO_CAPTURE,
                self.config.width, self.config.height,
                PixelFormat.MJPEG,
            )
            self._mjpeg = True
        except Exception:
            self._mjpeg = False
        try:
            device.controls.sharpness.value = device.controls.sharpness.maximum
        except Exception:
            pass
        self._device = device

        self._stream = iter(device)
        for _ in range(self.config.warmup_frames):
            next(self._stream)

    def close(self) -> None:
        if self._device is not None:
            self._stream = None
            self._device.close()
            self._device = None

    def _capture_raw_image(self) -> Image.Image:
        if not self._stream:
            self.open()
        assert self._stream is not None
        raw = bytes(next(self._stream))
        return Image.open(io.BytesIO(raw)).convert("RGB")


class _OpenCVCameraCapture(_BaseCameraCapture):
    """Windows / macOS fallback using OpenCV."""

    def __init__(self, config: CameraConfig | None = None) -> None:
        super().__init__(config)
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        if self._cap is not None:
            return
        # Use DirectShow on Windows for reliable capture
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.config.index, backend)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {self.config.index}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self._cap = cap

        # Give the camera time to adjust exposure / white balance
        time.sleep(2.0)

        # Discard warmup frames so auto-exposure settles
        for _ in range(self.config.warmup_frames):
            self._cap.read()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_raw_image(self) -> Image.Image:
        if self._cap is None:
            self.open()
        assert self._cap is not None
        # Flush the internal buffer so we get the latest frame,
        # not a stale one queued by DirectShow / the driver.
        for _ in range(2):
            self._cap.grab()
        ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError("Failed to read frame from camera")
        # OpenCV returns BGR; convert to RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)


def CameraCapture(config: CameraConfig | None = None) -> _BaseCameraCapture:
    """Factory: returns V4L2 backend on Linux, OpenCV on Windows/macOS."""
    if _IS_LINUX:
        return _V4L2CameraCapture(config)
    return _OpenCVCameraCapture(config)


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width",  type=int, default=CAMERA_WIDTH)
    parser.add_argument("--height", type=int, default=CAMERA_HEIGHT)
    parser.add_argument("--sharpen", type=float, default=2.0, help="Software sharpen factor")
    parser.add_argument("--out", default="frame.jpg")
    args = parser.parse_args()

    config = CameraConfig(
        index=args.camera, width=args.width, height=args.height,
        software_sharpen=args.sharpen,
    )
    with CameraCapture(config) as cam:
        jpeg = cam.capture_jpeg()
    Path(args.out).write_bytes(jpeg)
    print(f"Saved {len(jpeg):,} bytes → {args.out}")


