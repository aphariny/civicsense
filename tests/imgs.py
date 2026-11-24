"""Real tiny images for tests (the photo checks now open files for real, so fake bytes no longer pass)."""
import io

from PIL import Image


def png(size=(8, 8), color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def jpg(size=(8, 8), color=(30, 30, 200), tagged=False):
    """A JPEG; with tagged=True it carries camera tags and a GPS position, like a phone photo."""
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    if tagged:
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"
        exif[0x0110] = "SecretPhoneModel"
        try:
            exif[0x8825] = {1: "N", 2: (13.0, 1.0, 2.0), 3: "E", 4: (80.0, 12.0, 3.0)}
        except Exception:
            pass
        img.save(out, "JPEG", exif=exif)
    else:
        img.save(out, "JPEG")
    return out.getvalue()
