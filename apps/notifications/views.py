from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.legal.views import organization_required
from .models import Notification
from .services import actionable, change_state, generate_for_user, inbox_queryset, mark_all_read, present, visible_notifications


def filters(data):
    status = data.get("status", "all")
    kind = data.get("kind", "")
    return status if status in {"all", "unread", "read", "archived"} else "all", kind if kind in Notification.Kind.values else ""


@organization_required
@require_GET
def inbox(request):
    generate_for_user(request.user, request.organization)
    status, kind = filters(request.GET)
    visible = visible_notifications(request.user, request.organization)
    page = Paginator(inbox_queryset(request.user, request.organization, status=status, kind=kind), 20).get_page(request.GET.get("page"))
    return render(request, "notifications/inbox.html", {
        "page_title": "Notificações", "active_nav": "notifications",
        "notification_items": [present(note, request) for note in page], "page_obj": page,
        "notification_status": status, "notification_kind": kind,
        "notification_kinds": Notification.Kind.choices,
        "notification_unread": actionable(visible).filter(read_at__isnull=True, dismissed_at__isnull=True).count(),
        "notification_archived": visible.filter(dismissed_at__isnull=False).count(),
        "notification_filter_query": urlencode({"status": status, "kind": kind}),
    })


@organization_required
@require_POST
def state(request, pk, action):
    change_state(user=request.user, organization=request.organization, pk=pk, action=action)
    messages.success(request, {"read": "Notificação marcada como lida.", "unread": "Notificação marcada como não lida.", "archive": "Notificação arquivada.", "restore": "Notificação restaurada."}[action])
    status, kind = filters(request.POST)
    return redirect(reverse("notifications:inbox") + "?" + urlencode({"status": status, "kind": kind}))


@organization_required
@require_POST
def read_all(request):
    total = mark_all_read(user=request.user, organization=request.organization)
    messages.success(request, f"{total} notificação(ões) marcada(s) como lida(s).")
    return redirect("notifications:inbox")
