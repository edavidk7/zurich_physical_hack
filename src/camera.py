from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter
from v4l2py import Device
from v4l2py.device import BufferType, PixelFormat

logger = logging.getLogger(__name__)

_JPEG_MAGIC = b"\xff\xd8\xff"


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 1280
    height: int = 720
    warmup_frames: int = 3
    jpeg_quality: int = 85
    software_sharpen: float = 2.0   # 1.0 = off, 2.0 = noticeable, 4.0 = strong


class CameraCapture:
    """
    Capture a single JPEG frame from a V4L2 camera with max hardware sharpness
    and optional Pillow software sharpening.

    Usage::

        with CameraCapture(CameraConfig(index=0)) as cam:
            jpeg: bytes = cam.capture_jpeg()
            img:  Image = cam.capture_image()
    """

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()
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

        # Start the stream and discard warmup frames once at open time
        self._stream = iter(device)
        for _ in range(self.config.warmup_frames):
            next(self._stream)

    def close(self) -> None:
        if self._device is not None:
            self._stream = None
            self._device.close()
            self._device = None

    def capture_jpeg(self) -> bytes:
        if not self._stream:
            self.open()
        assert self._stream is not None

        raw = bytes(next(self._stream))

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img = ImageEnhance.Sharpness(img).enhance(self.config.software_sharpen)
        img = img.filter(ImageFilter.SHARPEN)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self.config.jpeg_quality)
        return buf.getvalue()

    def capture_image(self) -> Image.Image:
        return Image.open(io.BytesIO(self.capture_jpeg())).convert("RGB")

    def __enter__(self) -> "CameraCapture":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width",  type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
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


