"""Calendar projections of existing records; no duplicate event storage."""

import calendar
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership
from .models import Appointment, Contact, Deadline, Task
from .niches import filter_niche, niche_selection
from .services import visible_matters


MONTH_NAMES = ("", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
EVENT_LABELS = {"deadline": "Prazo", "task": "Tarefa", "appointment": "Compromisso", "important": "Data importante"}
BRAZIL_AREA_CODES = {str(n) for n in [11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,41,42,43,44,45,46,47,48,49,51,53,54,55,61,62,63,64,65,66,67,68,69,71,73,74,75,77,79,81,82,83,84,85,86,87,88,89,91,92,93,94,95,96,97,98,99]}


def normalize_whatsapp_phone(value):
    """Conservative E.164 normalization; never guess a missing Brazilian DDD."""
    raw = (value or "").strip()
    if not raw or not re.fullmatch(r"\+?[\d\s().-]+", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    explicit_international = raw.startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
    if not explicit_international and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 8 or len(digits) > 15 or digits.startswith("0") or len(set(digits)) == 1:
        return None
    if digits.startswith("55"):
        national = digits[2:]
        if len(national) not in (10, 11) or national[:2] not in BRAZIL_AREA_CODES:
            return None
        subscriber = national[2:]
        if len(subscriber) == 9 and not subscriber.startswith("9"):
            return None
        if len(subscriber) == 8 and subscriber[0] not in "2345":
            return None
    elif not explicit_international:
        return None
    return digits


def birthday_link(contact, organization):
    phone = normalize_whatsapp_phone(contact.phone)
    if not phone:
        return None
    message = f"Olá, {contact.name}! A equipe do {organization.name} deseja um feliz aniversário, com muita saúde, alegria e realizações. Parabéns pelo seu dia!"
    return "https://wa.me/" + phone + "?" + urlencode({"text": message})


def birthday_date(born, year):
    # February 29 is explicitly observed on February 28 in non-leap years.
    return date(year, born.month, min(born.day, calendar.monthrange(year, born.month)[1]))


def birthday_context(request, month=None, today=None):
    today = today or timezone.localdate()
    month = month or today.replace(day=1)
    if not Membership.objects.filter(user=request.user, organization=request.organization, is_active=True, user__is_active=True).exists():
        return {"birthdays": [], "birthday_today_count": 0}
    niche, choices = niche_selection(request)
    client_ids = filter_niche(visible_matters(request.user, request.organization), niche, choices).exclude(client_id=None).values("client_id")
    contacts = Contact.objects.filter(
        organization=request.organization, pk__in=client_ids, kind=Contact.Kind.PERSON,
        birth_date__isnull=False, birth_date__month=month.month,
    )
    birthdays = []
    for contact in contacts:
        occurs = birthday_date(contact.birth_date, month.year)
        birthdays.append({
            "contact": contact, "date": occurs, "is_today": occurs == today,
            "whatsapp_url": birthday_link(contact, request.organization),
            "leap_adjusted": contact.birth_date.day != occurs.day,
        })
    birthdays.sort(key=lambda item: (not item["is_today"], item["date"], item["contact"].name.casefold()))
    return {"birthdays": birthdays, "birthday_today_count": sum(item["is_today"] for item in birthdays)}


def _event_url(obj, module, editable):
    if editable:
        return reverse("legal:edit", args=[module, obj.pk])
    if obj.matter_id:
        return reverse("legal:detail", args=[obj.matter_id])
    return reverse("legal:list", args=[module])


def calendar_context(request, month=None, selected_day=None, kind="", today=None):
    """Shared context for full calendar and dashboard's compact calendar."""
    from .calendar_forms import CalendarFilterForm
    from .views import can_edit, scoped_queryset

    today = today or timezone.localdate()
    # Shared dashboard include also supports month/day/category navigation.
    if month is None:
        filters = CalendarFilterForm(request.GET)
        if filters.is_valid():
            month = filters.cleaned_data.get("month")
            selected_day = selected_day or filters.cleaned_data.get("day")
            kind = kind or filters.cleaned_data.get("kind", "")
    month = (month or today).replace(day=1)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous_month = (month - timedelta(days=1)).replace(day=1)
    dates = list(calendar.Calendar(firstweekday=6).itermonthdates(month.year, month.month))
    first, last = dates[0], dates[-1]
    if selected_day is None or not first <= selected_day <= last:
        selected_day = today if today.year == month.year and today.month == month.month else month
    editable = can_edit(request)
    niche, choices = niche_selection(request)
    def records(model):
        return filter_niche(scoped_queryset(request.user, request.organization, model), niche, choices, relation="matter__")

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(first, time.min), tz)
    stop = timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min), tz)
    events = []

    for obj in records(Deadline).filter(due_date__range=(first, last)).select_related("matter", "owner"):
        events.append({"id": f"deadline-{obj.pk}", "kind": "deadline", "title": obj.title, "date": obj.due_date, "time": "", "end_date": obj.due_date, "label": "Prazo jurídico", "status": obj.get_status_display(), "done": obj.status == Deadline.Status.FULFILLED, "matter": obj.matter, "owner": obj.owner, "url": _event_url(obj, "deadlines", editable), "sort": "00:00"})
    for obj in records(Task).filter(due_date__range=(first, last)).select_related("matter", "owner"):
        events.append({"id": f"task-{obj.pk}", "kind": "task", "title": obj.title, "date": obj.due_date, "time": "", "end_date": obj.due_date, "label": "Entrega de tarefa", "status": obj.get_status_display(), "done": obj.status == Task.Status.DONE, "matter": obj.matter, "owner": obj.owner, "url": _event_url(obj, "tasks", editable), "sort": "00:00"})
    for obj in records(Appointment).filter(starts_at__lt=stop, ends_at__gt=start).select_related("matter", "owner"):
        local_start, local_end = timezone.localtime(obj.starts_at, tz), timezone.localtime(obj.ends_at, tz)
        # End is exclusive: an appointment ending at midnight does not occupy the following day.
        final_date = timezone.localtime(obj.ends_at - timedelta(microseconds=1), tz).date()
        events.append({"id": f"appointment-{obj.pk}", "kind": "important" if obj.kind == Appointment.Kind.IMPORTANT_DATE else "appointment", "title": obj.title, "date": local_start.date(), "end_date": final_date, "time": local_start.strftime("%H:%M"), "end_time": local_end.strftime("%H:%M"), "ends_at": local_end, "starts_at": local_start, "label": obj.get_kind_display(), "status": "", "done": False, "matter": obj.matter, "owner": obj.owner, "location": obj.location, "url": _event_url(obj, "appointments", editable), "sort": local_start.strftime("%H:%M")})
    month_events = [e for e in events if e["date"] < next_month and e["end_date"] >= month]
    counts = Counter(e["kind"] for e in month_events)
    if kind in EVENT_LABELS:
        events = [event for event in events if event["kind"] == kind]
    else:
        kind = ""
    events.sort(key=lambda event: (event["date"], event["sort"], event["title"].casefold(), event["id"]))
    per_day = defaultdict(list)
    for event in events:
        cursor = max(first, event["date"])
        while cursor <= min(last, event["end_date"]):
            per_day[cursor].append(event)
            cursor += timedelta(days=1)
    cells = []
    for current in dates:
        day_events = per_day[current]
        cells.append({"date": current, "current_month": current.month == month.month, "today": current == today, "selected": current == selected_day, "events": day_events, "preview": day_events[:3], "extra": max(0, len(day_events) - 3), "kinds": sorted(set(e["kind"] for e in day_events)), "url": "?" + urlencode({"month": month.strftime("%Y-%m"), "day": current.isoformat(), "kind": kind, "niche": niche}) + "#calendar-detail"})
    result = {
        "calendar_month": month, "calendar_month_label": f"{MONTH_NAMES[month.month]} {month.year}",
        "calendar_previous": previous_month.strftime("%Y-%m") if month.year > 1901 or month.month > 1 else "",
        "calendar_next": next_month.strftime("%Y-%m") if month.year < 2099 or month.month < 12 else "",
        "calendar_today_month": today.strftime("%Y-%m"), "calendar_today": today,
        "calendar_days": cells, "calendar_selected_day": selected_day,
        "calendar_day_events": per_day[selected_day], "calendar_counts": dict(counts),
        "calendar_event_count": len(month_events), "calendar_kind": kind,
        "calendar_filters": [{"key": key, "label": label, "count": counts[key]} for key, label in EVENT_LABELS.items()],
        "calendar_agenda": [{"date": current, "events": per_day[current]} for current in dates if current.month == month.month and per_day[current]],
        "can_edit": editable,
        "niche": niche, "niche_choices": choices,
    }
    result.update(birthday_context(request, month=month, today=today))
    return result
