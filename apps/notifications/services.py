"""Reminders store only references; titles, links and access are always current."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.db.models.functions import ExtractDay, ExtractMonth, ExtractYear, Mod
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from apps.billing.services import require_access
from apps.core.models import Membership
from apps.legal.calendar_services import birthday_date, birthday_link
from apps.legal.models import Contact, Deadline, Task
from apps.legal.services import visible_matters
from apps.legal.views import scoped_queryset

from .models import Notification


OFFICE_ROLES = ("owner", "manager", "operator", "viewer")
LOOKAHEAD_DAYS = 3


def active_membership(user, organization):
    if not user or not user.is_authenticated or not user.is_active or not organization:
        return None
    membership = Membership.objects.filter(
        user=user, organization=organization, is_active=True, role__in=OFFICE_ROLES,
        organization__status="active", organization__business_type="office",
    ).first()
    if membership:
        try:
            require_access(organization)
        except PermissionDenied:
            return None
    return membership


def visible_notifications(user, organization):
    """Do not trust membership or subject permissions captured at generation time."""
    if not active_membership(user, organization):
        return Notification.objects.none()
    # These three subjects share legal's explicit matter scope. Build it once
    # for the topbar counter instead of repeating the role lookup per model.
    matters = visible_matters(user, organization)
    deadlines = Deadline.objects.filter(organization=organization, matter__in=matters)
    tasks = Task.objects.filter(organization=organization).filter(Q(matter__in=matters) | Q(matter__isnull=True))
    clients = matters.exclude(client_id=None).values("client_id")
    same_birthday = Q(contact__birth_date__month=ExtractMonth("source_date"), contact__birth_date__day=ExtractDay("source_date"))
    # A February 29 birthday is observed on February 28 only in a non-leap
    # occurrence year. A later correction of the contact date hides stale rows.
    adjusted_birthday = Q(contact__birth_date__month=2, contact__birth_date__day=29, source_date__month=2, source_date__day=28) & (
        ~Q(source_mod4=0) | (Q(source_mod100=0) & ~Q(source_mod400=0))
    )
    return Notification.objects.filter(organization=organization, recipient=user).alias(
        source_mod4=Mod(ExtractYear("source_date"), 4),
        source_mod100=Mod(ExtractYear("source_date"), 100),
        source_mod400=Mod(ExtractYear("source_date"), 400),
    ).filter(
        Q(kind="deadline", deadline__in=deadlines, deadline__due_date=F("source_date"))
        | Q(kind="task", task__in=tasks, task__due_date=F("source_date"))
        | (Q(kind="birthday", contact_id__in=clients, contact__organization=organization, contact__kind="person", contact__birth_date__isnull=False) & (same_birthday | adjusted_birthday))
    )


def actionable(queryset):
    return queryset.exclude(deadline__status=Deadline.Status.FULFILLED).exclude(task__status=Task.Status.DONE)


def unread_count(request):
    if not getattr(request, "organization", None):
        return 0
    return actionable(visible_notifications(request.user, request.organization)).filter(read_at__isnull=True, dismissed_at__isnull=True).count()


def generate_for_user(user, organization, *, today=None):
    """One persistent occurrence per date; retries preserve read/archive choices."""
    if not active_membership(user, organization):
        return 0
    today = today or timezone.localdate()
    stop = today + timedelta(days=LOOKAHEAD_DAYS)
    candidates = []
    for model, kind, field, done in [
        (Deadline, Notification.Kind.DEADLINE, "deadline_id", Deadline.Status.FULFILLED),
        (Task, Notification.Kind.TASK, "task_id", Task.Status.DONE),
    ]:
        records = scoped_queryset(user, organization, model).filter(due_date__lte=stop).exclude(status=done)
        for pk, due_date in records.values_list("pk", "due_date").iterator(chunk_size=500):
            candidates.append(Notification(organization=organization, recipient=user, kind=kind, source_date=due_date, **{field: pk}))
    clients = visible_matters(user, organization).exclude(client_id=None).values("client_id")
    contacts = Contact.objects.filter(
        organization=organization, pk__in=clients, kind=Contact.Kind.PERSON,
        birth_date__isnull=False, birth_date__month=today.month,
    )
    for pk, birth_date in contacts.values_list("pk", "birth_date"):
        occurs = birthday_date(birth_date, today.year)
        if occurs == today:
            candidates.append(Notification(organization=organization, recipient=user, kind=Notification.Kind.BIRTHDAY, contact_id=pk, source_date=occurs))
    # Only trusted references built from the live scope reach this batch insert.
    # Partial unique constraints make concurrent timer/browser retries harmless.
    with transaction.atomic():
        before = Notification.objects.filter(organization=organization, recipient=user).count()
        Notification.objects.bulk_create(candidates, ignore_conflicts=True, batch_size=500)
        after = Notification.objects.filter(organization=organization, recipient=user).count()
    return max(0, after - before)


def inbox_queryset(user, organization, *, status="all", kind=""):
    qs = visible_notifications(user, organization)
    if status == "archived":
        qs = qs.filter(dismissed_at__isnull=False)
    else:
        qs = qs.filter(dismissed_at__isnull=True)
        if status == "unread":
            qs = actionable(qs).filter(read_at__isnull=True)
        elif status == "read":
            qs = qs.filter(read_at__isnull=False)
    if kind in Notification.Kind.values:
        qs = qs.filter(kind=kind)
    return qs.select_related("deadline__matter", "task__matter", "contact").annotate(
        read_order=Case(When(read_at__isnull=True, then=Value(0)), default=Value(1), output_field=IntegerField())
    ).order_by("read_order", "-created_at", "-pk")


def present(notification, request, *, today=None):
    today = today or timezone.localdate()
    editable = request.membership.role in {"owner", "manager", "operator"}
    item = {"record": notification, "date": notification.source_date, "kind": notification.kind, "label": notification.get_kind_display(), "whatsapp_url": None, "resolved": False}
    if notification.kind == Notification.Kind.BIRTHDAY:
        contact = notification.contact
        item.update(title=contact.name, detail="Aniversário de cliente", urgency="birthday", status="Hoje" if notification.source_date == today else "Aniversário registrado", url=reverse("legal:calendar") + "?month=" + notification.source_date.strftime("%Y-%m") + "&day=" + notification.source_date.isoformat() + "#birthday-panel", action_label="Ver no calendário", birthday_is_today=notification.source_date == today, whatsapp_url=birthday_link(contact, request.organization) if notification.source_date == today else None)
    else:
        subject = notification.deadline if notification.kind == Notification.Kind.DEADLINE else notification.task
        module = "deadlines" if notification.kind == Notification.Kind.DEADLINE else "tasks"
        resolved = subject.status in {Deadline.Status.FULFILLED, Task.Status.DONE}
        days = (subject.due_date - today).days
        label = "Concluído" if resolved else ("Vencido" if days < 0 else "Vence hoje" if days == 0 else "Vence amanhã" if days == 1 else f"Em {days} dias")
        url = reverse("legal:edit", args=[module, subject.pk]) if editable else reverse("legal:detail", args=[subject.matter_id]) if subject.matter_id else reverse("legal:list", args=[module])
        item.update(title=subject.title, detail=subject.matter.title if subject.matter_id else "Sem pasta vinculada", urgency="resolved" if resolved else "overdue" if days < 0 else "today" if days == 0 else "upcoming", status=label, url=url, action_label="Consultar registro", resolved=resolved)
    item["is_unread"] = notification.read_at is None and not item["resolved"]
    return item


@transaction.atomic
def change_state(*, user, organization, pk, action):
    if action not in {"read", "unread", "archive", "restore"}:
        raise Http404("Ação não encontrada.")
    # Lock only Notification: nullable subject joins cannot be locked in PostgreSQL.
    note = visible_notifications(user, organization).select_for_update(of=("self",)).filter(pk=pk).first()
    if not note:
        raise Http404("Notificação não encontrada.")
    now = timezone.now()
    updates = {"read_at": now} if action == "read" else {"read_at": None} if action == "unread" else {"dismissed_at": now} if action == "archive" else {"dismissed_at": None}
    Notification.objects.filter(pk=note.pk, organization=organization, recipient=user).update(**updates)


def mark_all_read(*, user, organization):
    return actionable(visible_notifications(user, organization)).filter(read_at__isnull=True, dismissed_at__isnull=True).update(read_at=timezone.now())
