"""Decode and normalize uploads so content, extension and format agree."""
from io import BytesIO
from pathlib import Path
import warnings

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, ImageChops, ImageDraw, ImageOps, UnidentifiedImageError


def transparent_brand(image):
    """Remove a uniform, border-connected matte without erasing enclosed artwork.

    Already transparent artwork is preserved. Ambiguous photos/gradients fail
    explicitly instead of silently damaging a client's identity.
    """
    alpha = image.getchannel("A")
    if alpha.getextrema()[1] == 0:
        raise ValidationError("A imagem está totalmente transparente. Envie uma logo visível.")
    # A single almost-opaque pixel is not evidence of a transparent background.
    if alpha.histogram()[0] >= max(1, image.width * image.height // 100):
        return image
    rgb = image.convert("RGB")
    width, height = image.size
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    colors = [rgb.getpixel(p) for p in corners]
    distance = lambda a, b: max(abs(x - y) for x, y in zip(a, b))
    background = max(colors, key=lambda c: sum(distance(c, other) <= 24 for other in colors))
    if sum(distance(background, c) <= 24 for c in colors) < 3:
        raise ValidationError("Não foi possível separar o fundo com segurança. Envie PNG transparente ou uma logo sobre fundo de uma única cor.")
    channels = ImageChops.difference(rgb, Image.new("RGB", image.size, background)).split()
    difference = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = difference.point(lambda value: 255 if value <= 24 else 0)
    border = ([(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)])
    if sum(mask.getpixel(p) == 255 for p in border) < len(border) * .65:
        raise ValidationError("O fundo tem várias cores ou encosta demais na marca. Use uma imagem com margem e fundo uniforme, ou PNG transparente.")
    for point in border:
        if mask.getpixel(point) == 255:
            ImageDraw.floodfill(mask, point, 128)
    removed = mask.point(lambda value: 255 if value == 128 else 0)
    histogram = removed.histogram()
    if histogram[255] > width * height * .995:
        raise ValidationError("Não identifiquei um desenho separado do fundo. Envie uma logo com contraste e margem.")
    result = image.copy()
    result.putalpha(ImageChops.multiply(alpha, ImageOps.invert(removed)))
    return result


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
                normalized = ImageOps.exif_transpose(original).convert("RGBA")
                normalized.thumbnail((1024, 1024))
                normalized = transparent_brand(normalized)
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
        return SimpleUploadedFile(Path(upload.name).stem[:80] + ".png", output.getvalue(), content_type="image/png")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError("O arquivo não é uma imagem válida ou excede as dimensões permitidas.") from exc
    finally:
        upload.seek(0)
