import io
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings, Client
from django.urls import reverse
from PIL import Image, ImageDraw

from .image_validation import transparent_brand, validated_brand_image
from .models import Organization, Membership, User
from .test_platform import TEST_SETTINGS


def artwork(background="white", foreground="black", mode="RGB"):
    image = Image.new(mode, (100, 80), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 80, 65), fill=foreground)
    draw.rectangle((35, 30, 65, 50), fill="white")
    return image


def upload(image=None):
    out = io.BytesIO()
    (image or artwork()).save(out, "PNG")
    return SimpleUploadedFile("logo.png", out.getvalue(), content_type="image/png")


class BrandImageTests(SimpleTestCase):
    def test_white_black_and_colored_background_removed_artwork_preserved(self):
        for background in ("white", "black", "#16384a"):
            with self.subTest(background=background):
                result = Image.open(validated_brand_image(upload(artwork(background, "#f5a000"))))
                self.assertEqual(result.getpixel((0,0))[3], 0)
                self.assertEqual(result.getpixel((20,15)), (245,160,0,255))
                self.assertEqual(result.getpixel((40,40)), (255,255,255,255))

    def test_existing_transparency_and_soft_edges_preserved(self):
        image = artwork((0,0,0,0), "#f5a000", "RGBA")
        image.putpixel((19,15), (245,160,0,128))
        self.assertEqual(transparent_brand(image).tobytes(), image.tobytes())

    def test_ambiguous_or_empty_image_rejected(self):
        photo = Image.new("RGB", (50,50))
        for x in range(50):
            for y in range(50): photo.putpixel((x,y),(x*5,y*5,20))
        for image in (photo, Image.new("RGB", (50,50), "white"), Image.new("RGBA", (50,50), (0,0,0,0))):
            with self.assertRaises(ValidationError): validated_brand_image(upload(image))

    def test_normalization_is_idempotent_and_removes_metadata(self):
        first = validated_brand_image(upload(artwork("#eeeeee", "blue")))
        second = validated_brand_image(first)
        self.assertEqual(Image.open(first).tobytes(), Image.open(second).tobytes())
        self.assertFalse(Image.open(second).getexif())


@override_settings(**TEST_SETTINGS)
class BrandPreviewTests(TestCase):
    def setUp(self):
        self.org=Organization.objects.create(name="Marca", slug="marca-preview", business_type="office")
        self.user=User.objects.create_user("marca@example.test", "TestBranding!4839")
        self.member=Membership.objects.create(organization=self.org,user=self.user,role="owner")
        self.client.force_login(self.user)

    def test_preview_does_not_save_brand_or_files(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response=self.client.post(reverse("core:brand_preview"), {"image":upload()})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Type'],'image/png')
            self.assertIn('no-store',response['Cache-Control'])
            self.assertEqual(Image.open(io.BytesIO(response.content)).getpixel((0,0))[3],0)
            self.org.refresh_from_db(); self.assertFalse(self.org.brand_logo)
            from pathlib import Path
            self.assertEqual(list(Path(media).rglob('*')),[])

    def test_permission_invalid_upload_and_csrf_enforced(self):
        self.assertEqual(self.client.get(reverse("core:brand_preview")).status_code,405)
        self.assertEqual(self.client.post(reverse("core:brand_preview"),{"image":SimpleUploadedFile('bad.png',b'<script>bad</script>')}).status_code,400)
        guarded=Client(enforce_csrf_checks=True); guarded.force_login(self.user)
        self.assertEqual(guarded.post(reverse("core:brand_preview"),{"image":upload()}).status_code,403)
        self.member.role='operator'; self.member.save()
        self.assertEqual(self.client.post(reverse("core:brand_preview"),{"image":upload()}).status_code,403)
