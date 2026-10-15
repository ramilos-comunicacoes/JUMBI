"""Client communication services with click-to-chat links, contextual templates and declarations."""

import re
import urllib.parse
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ClientContact, Deadline, FinanceEntry, Matter, MessageTemplate
from .services import audit


def sanitize_phone(phone):
    """Normalize phone to numeric digits suitable for WhatsApp click-to-chat."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def get_whatsapp_link(phone, text):
    """Return click-to-chat link. Does not imply delivery or automatic sending."""
    digits = sanitize_phone(phone)
    encoded = urllib.parse.quote(text)
    return f"https://wa.me/{digits}?text={encoded}" if digits else ""


def render_message_template(*, template, contact, matter=None, actor, case_owner=None, extra_vars=None):
    """Interpolate variables into template text with signature and validation guardrails."""
    extra_vars = extra_vars or {}
    org = contact.organization

    client_name = contact.name.split()[0] if contact.name else "Cliente"
    actor_name = actor.get_full_name() or actor.email
    owner = case_owner or (matter.owner if matter else actor)
    owner_name = owner.get_full_name() or owner.email
    office_name = org.name

    # Check for deadline guardrail: if unconfirmed deadline exists, do not claim definitive date
    unconfirmed_deadline = False
    deadline_text = extra_vars.get("prazo_conferido", "")
    if matter and not deadline_text:
        next_deadline = matter.deadlines.exclude(status=Deadline.Status.FULFILLED).order_by("due_date").first()
        if next_deadline:
            if next_deadline.status == Deadline.Status.PENDING:
                unconfirmed_deadline = True
                deadline_text = "em conferência pela equipe jurídica"
            else:
                deadline_text = next_deadline.due_date.strftime("%d/%m/%Y")

    # Financial balance if matter has finance entries
    balance_text = extra_vars.get("valor_em_aberto", "")
    due_finance_text = extra_vars.get("vencimento_financeiro", "")
    from .services import can_manage_finance
    from apps.billing.services import has_advanced
    if matter and not balance_text and can_manage_finance(actor, org) and has_advanced(org):
        pending_entry = matter.finance_entries.filter(kind=FinanceEntry.Kind.INCOME).order_by("due_date").first()
        if pending_entry and pending_entry.balance > Decimal("0.00"):
            balance_text = f"R$ {pending_entry.balance:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            due_finance_text = pending_entry.due_date.strftime("%d/%m/%Y")

    vars_dict = {
        "nome_cliente": client_name,
        "nome_atendente": actor_name,
        "nome_responsavel": owner_name,
        "nome_escritorio": office_name,
        "assunto": matter.title if matter else "seu atendimento",
        "resumo_validado": extra_vars.get("resumo_validado", matter.title if matter else ""),
        "documentos_pendentes": extra_vars.get("documentos_pendentes", "documentos solicitados"),
        "data_limite_cliente": extra_vars.get("data_limite_cliente", "a combinar"),
        "prazo_conferido": deadline_text or "em acompanhamento",
        "valor_em_aberto": balance_text or "R$ 0,00",
        "vencimento_financeiro": due_finance_text or "a confirmar",
    }
    vars_dict.update(extra_vars)

    body = template.body if isinstance(template, MessageTemplate) else str(template)
    
    # If unconfirmed deadline is present in text assertively, raise validation
    if unconfirmed_deadline and "{prazo_conferido}" in body and "conferência" not in deadline_text:
        raise ValidationError("O prazo do caso ainda está 'A conferir'. Valide o prazo antes de comunicar ao cliente.")

    for k, v in vars_dict.items():
        body = body.replace(f"{{{k}}}", str(v))

    # Signature convention: transparently identify attendant and case responsible
    signature = f"\n\nAtenciosamente,\n{actor_name}"
    if owner != actor:
        signature += f"\nResponsável pelo caso: {owner_name}"
    signature += f"\n{office_name}"

    if office_name not in body:
        body += signature

    return body


@transaction.atomic
def create_contact_draft(*, organization, contact, actor, template=None, matter=None, case_owner=None, extra_vars=None):
    """Prepare draft message and record initial client contact state."""
    from .services import _authorize_write
    _authorize_write(actor=actor, obj=matter or contact)
    if contact.organization_id != organization.pk or (matter and matter.organization_id != organization.pk):
        raise ValidationError("O atendimento deve pertencer ao mesmo escritório.")
    owner = case_owner or (matter.owner if matter else actor)
    phone = contact.phone or ""
    prepared = render_message_template(
        template=template,
        contact=contact,
        matter=matter,
        actor=actor,
        case_owner=owner,
        extra_vars=extra_vars,
    ) if template else (extra_vars.get("text", "") if extra_vars else "")

    contact_log = ClientContact.objects.create(
        organization=organization,
        matter=matter,
        contact=contact,
        template=template if isinstance(template, MessageTemplate) else None,
        phone=phone,
        prepared_text=prepared,
        status=ClientContact.Status.DRAFT,
        actor=actor,
        case_owner=owner,
    )
    return contact_log


def mark_link_opened(contact_log, actor):
    """Mark that user clicked the link. Does NOT confirm sending or completion."""
    from .services import _authorize_write
    _authorize_write(actor=actor, obj=contact_log)
    if contact_log.status == ClientContact.Status.DRAFT:
        contact_log.status = ClientContact.Status.LINK_OPENED
        contact_log.save(update_fields=["status"])
    return contact_log


@transaction.atomic
def complete_client_contact(*, contact_log, actor, sent_text="", result_note="", client_reply=""):
    """Manually declare completion of contact with timestamp, effective text and declared result."""
    from .services import _authorize_write
    contact_log = ClientContact.objects.select_for_update().get(pk=contact_log.pk)
    _authorize_write(actor=actor, obj=contact_log)
    if contact_log.status == ClientContact.Status.COMPLETED_MANUAL:
        return contact_log
    contact_log.status = ClientContact.Status.COMPLETED_MANUAL
    contact_log.completed_at = timezone.now()
    contact_log.sent_text = sent_text.strip() or contact_log.prepared_text
    contact_log.result_note = result_note.strip()
    contact_log.client_reply = client_reply.strip()
    contact_log.save(update_fields=["status", "completed_at", "sent_text", "result_note", "client_reply"])

    if contact_log.matter:
        audit(
            organization=contact_log.organization,
            actor=actor,
            action="client_contact.completed",
            obj=contact_log.matter,
            description=f"Contato WhatsApp registrado por {actor.get_full_name() or actor.email} com {contact_log.contact.name}. Resultado: {contact_log.result_note or 'Concluído'}",
        )
    return contact_log
