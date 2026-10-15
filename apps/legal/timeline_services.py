"""Unified, typed timeline for legal matters.

Distinguishes official procedural movements, internal notes, declared client
contacts, financial events, tasks, and deadlines so an internal note never looks
like a court notification.
"""

from django.db.models import CharField, Q
from django.db.models.functions import Cast
from django.utils import timezone

from .models import (
    AdministrativeDemand, Appointment, AuditEvent, ClientContact, CourtCase,
    Deadline, DeadlineRevision, DJENCommunication, Document, DocumentVersion,
    FinanceEntry, Matter, Payment, PaymentReceipt, Task,
)


def get_matter_unified_timeline(matter, user, organization):
    """Return a unified, chronological list of all matter activities with explicit types."""
    events = []
    from .services import visible_matters
    from apps.core.models import Membership
    from apps.billing.services import has_advanced
    if not visible_matters(user, organization).filter(pk=matter.pk).exists():
        return events
    finance_allowed = has_advanced(organization) and Membership.objects.filter(user=user, organization=organization,
        is_active=True, role__in=["owner", "manager"]).exists()

    # 1. Audit events for base actions
    audit_queryset = AuditEvent.objects.filter(
        organization=organization,
        object_type=Matter._meta.label_lower,
        object_id=str(matter.pk),
    ).select_related("actor")
    for a in audit_queryset:
        events.append({
            "type": "internal_note",
            "type_label": "Anotação interna",
            "badge_class": "badge-slate",
            "title": a.description or a.action,
            "description": "",
            "actor": a.actor,
            "created_at": a.created_at,
        })

    # 2. Official movements (DJEN communications linked to this matter)
    djen_comms = DJENCommunication.objects.filter(
        organization=organization, matter=matter,
    ).select_related("search_run")
    for comm in djen_comms:
        events.append({
            "type": "official_movement",
            "type_label": "Publicação importada · conferir origem",
            "badge_class": "badge-blue",
            "title": f"Publicação DJEN · {comm.court} ({comm.case_number})",
            "description": comm.content_summary or comm.full_text[:300],
            "actor": None,
            "created_at": comm.created_at,
            "is_official": False,
        })

    # 3. Administrative Demands (INSS / Previdia)
    admin_demands = AdministrativeDemand.objects.filter(
        organization=organization, matter=matter,
    ).select_related("assigned_to")
    for dem in admin_demands:
        events.append({
            "type": "official_movement",
            "type_label": f"{'Cadastro manual' if dem.is_manual_entry else 'Registro importado'} / {dem.source_agency}",
            "badge_class": "badge-cyan",
            "title": f"Requerimento {dem.protocol_number} · {dem.service_name}",
            "description": f"Situação na fonte: {dem.original_status}. {dem.demands_summary}",
            "actor": dem.assigned_to,
            "created_at": dem.created_at,
            "is_official": not dem.is_manual_entry,
        })

    # 4. Tasks (created, moved, completed)
    tasks = Task.objects.filter(organization=organization, matter=matter).select_related("owner", "delegated_by")
    for t in tasks:
        events.append({
            "type": "task_event",
            "type_label": "Tarefa",
            "badge_class": "badge-amber",
            "title": f"Tarefa: {t.title} ({t.get_status_display()})",
            "description": t.description or (f"Conclusão: {t.completion_note}" if t.completion_note else ""),
            "actor": t.owner,
            "created_at": t.completed_at or t.created_at,
        })

    # 5. Deadlines (conferência, cumprimento)
    deadlines = Deadline.objects.filter(organization=organization, matter=matter).select_related("owner", "confirmed_by")
    for d in deadlines:
        events.append({
            "type": "deadline_event",
            "type_label": "Prazo / Obrigação",
            "badge_class": "badge-red" if d.urgency_level == "urgent" else "badge-purple",
            "title": f"{d.get_kind_display()}: {d.title} (Vencimento: {d.due_date.strftime('%d/%m/%Y')})",
            "description": f"Origem: {d.source}. Situação: {d.get_status_display()} ({d.urgency_label}). {d.evidence}",
            "actor": d.confirmed_by or d.owner,
            "created_at": d.confirmed_at or d.created_at,
        })

    # 6. Declared Client Contacts (WhatsApp / Atendimento)
    contacts = ClientContact.objects.filter(organization=organization, matter=matter).select_related("actor", "case_owner")
    for c in contacts:
        events.append({
            "type": "client_contact",
            "type_label": "Contato declarado pelo colaborador",
            "badge_class": "badge-green",
            "title": f"Atendimento via {c.channel.title()} ({c.get_status_display()})",
            "description": f"Enviado: {c.sent_text or c.prepared_text}\nResultado: {c.result_note}",
            "actor": c.actor,
            "created_at": c.completed_at or c.created_at,
            "is_declared_contact": True,
        })

    # 7. Financial Events & Receipts
    entries = FinanceEntry.objects.filter(organization=organization, matter=matter).prefetch_related("payments")
    if not finance_allowed:
        entries = entries.none()
    for f in entries:
        events.append({
            "type": "financial_event",
            "type_label": "Evento financeiro",
            "badge_class": "badge-gold",
            "title": f"Lançamento {f.get_kind_display()}: {f.description} (R$ {f.amount})",
            "description": f"Saldo em aberto: R$ {f.balance}",
            "actor": None,
            "created_at": f.created_at,
        })
        for p in f.payments.all():
            events.append({
                "type": "financial_event",
                "type_label": "Baixa financeira",
                "badge_class": "badge-gold",
                "title": f"Baixa de R$ {p.amount} ({'Estorno' if p.reversal_of_id else 'Recebimento'})",
                "description": p.note or "",
                "actor": p.created_by,
                "created_at": p.created_at,
            })

    receipts = PaymentReceipt.objects.filter(organization=organization, matter=matter).select_related("issued_by")
    if not finance_allowed:
        receipts = receipts.none()
    for r in receipts:
        events.append({
            "type": "financial_event",
            "type_label": "Recibo emitido",
            "badge_class": "badge-gold",
            "title": f"Recibo #{r.receipt_number} · R$ {r.amount} ({r.payer_name})",
            "description": f"Referência: {r.reference_description}. Saldo restante: R$ {r.remaining_balance}",
            "actor": r.issued_by,
            "created_at": r.created_at,
        })

    # Sort all events chronologically (newest first)
    events.sort(key=lambda x: x["created_at"], reverse=True)
    return events
