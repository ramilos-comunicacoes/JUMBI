"""Decode and normalize uploads so content, extension and format agree."""
from io import BytesIO
from pathlib import Path
import warnings

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, UnidentifiedImageError


def validated_brand_image(upload):
    if not isinstance(upload, UploadedFile):
        return upload
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError("Envie uma imagem de até 2 MB.")
    if Path(upload.name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".ico"}:
        raise ValidationError("Use PNG, JPG, WebP ou ICO. Exporte arquivos SVG como PNG.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as original:
                if original.format not in {"PNG", "JPEG", "WEBP", "ICO"} or original.width * original.height > 20_000_000:
                    raise ValueError("unsupported image")
                original.verify()
            upload.seek(0)
            with Image.open(upload) as original:
                original.load()
                normalized = original.convert("RGBA")
                normalized.thumbnail((2048, 2048))
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
        return SimpleUploadedFile(Path(upload.name).stem[:80] + ".png", output.getvalue(), content_type="image/png")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError("O arquivo não é uma imagem válida ou excede as dimensões permitidas.") from exc
    finally:
        upload.seek(0)
