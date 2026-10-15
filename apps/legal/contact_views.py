"""Views for client WhatsApp click-to-chat messaging, templates and declarations."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .contact_services import complete_client_contact, create_contact_draft, get_whatsapp_link, mark_link_opened
from .models import ClientContact, Contact, Matter, MessageTemplate
from .views import can_edit, organization_required, scoped_queryset


@organization_required
@require_GET
def contact_messages_list(request):
    """List declared client contacts and pending drafts."""
    contacts = scoped_queryset(request.user, request.organization, ClientContact).select_related("contact", "matter", "actor", "case_owner").order_by("-created_at")

    templates = MessageTemplate.objects.filter(
        organization=request.organization, is_active=True
    ).order_by("category", "title")

    return render(request, "legal/contact_messages_list.html", {
        "title": "Central de Contatos e Mensagens",
        "page_title": "Contatos com Clientes",
        "active_nav": "contact_messages",
        "contacts": contacts[:30],
        "templates": templates,
        "can_edit": can_edit(request),
    })


@organization_required
@require_GET
def contact_message_detail(request, pk):
    """View prepared message, click-to-chat link and declaration form."""
    msg = get_object_or_404(
        scoped_queryset(request.user, request.organization, ClientContact).select_related("contact", "matter", "actor", "case_owner"),
        pk=pk,
        organization=request.organization,
    )
    wa_link = get_whatsapp_link(msg.phone, msg.prepared_text)

    return render(request, "legal/contact_message_detail.html", {
        "title": f"Mensagem para {msg.contact.name}",
        "page_title": "Atendimento ao Cliente",
        "active_nav": "contact_messages",
        "msg": msg,
        "wa_link": wa_link,
        "can_edit": can_edit(request),
    })


@organization_required
@require_POST
def contact_message_open_link(request, pk):
    """User clicked to open the WhatsApp chat link."""
    if not can_edit(request):
        raise PermissionDenied("Seu perfil permite somente consulta.")
    msg = get_object_or_404(scoped_queryset(request.user, request.organization, ClientContact), pk=pk)
    mark_link_opened(msg, request.user)
    wa_link = get_whatsapp_link(msg.phone, msg.prepared_text)
    if wa_link:
        return redirect(wa_link)
    messages.error(request, "Número de telefone inválido para o contato.")
    return redirect(reverse("legal:contact_message_detail", args=[msg.pk]))


@organization_required
@require_POST
def contact_message_complete(request, pk):
    """Colaborador declara manualmente a conclusão do atendimento."""
    if not can_edit(request):
        raise PermissionDenied("Permissão negada.")

    msg = get_object_or_404(scoped_queryset(request.user, request.organization, ClientContact), pk=pk)
    sent_text = request.POST.get("sent_text", "").strip()
    result_note = request.POST.get("result_note", "").strip()
    client_reply = request.POST.get("client_reply", "").strip()

    complete_client_contact(
        contact_log=msg,
        actor=request.user,
        sent_text=sent_text,
        result_note=result_note,
        client_reply=client_reply,
    )
    messages.success(request, f"Atendimento com {msg.contact.name} concluído e registrado com sucesso no histórico.")
    if msg.matter_id:
        return redirect(reverse("legal:detail", args=[msg.matter_id]))
    return redirect(reverse("legal:contact_messages_list"))
