from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .image_validation import validated_brand_image


@login_required
@require_POST
def preview(request):
    member = getattr(request, "membership", None)
    if not member or member.role not in {"owner", "manager"}:
        raise PermissionDenied("Somente a direção e a gestão podem personalizar a marca.")
    upload = request.FILES.get("image")
    if upload is None:
        return JsonResponse({"error": "Selecione uma imagem para visualizar."}, status=400)
    try:
        result = validated_brand_image(upload)
    except ValidationError as exc:
        response = JsonResponse({"error": " ".join(exc.messages)}, status=400)
    else:
        response = HttpResponse(result.read(), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response
