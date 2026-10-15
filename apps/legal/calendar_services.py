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
    from apps.core.preferences import office_preferences
    message = office_preferences(organization)["birthday_message"].replace("{cliente}", contact.name).replace("{escritorio}", organization.name)
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


def _mark_conflicts(events):
    """Only the same responsible person's visible, overlapping appointments conflict."""
    by_owner = defaultdict(list)
    for event in events:
        event["conflict"] = False
        if event.get("starts_at"):
            by_owner[event["owner"].pk].append(event)
    for owned in by_owner.values():
        active = []
        for event in sorted(owned, key=lambda item: item["starts_at"]):
            active = [other for other in active if other["ends_at"] > event["starts_at"]]
            for other in active:
                other["conflict"] = event["conflict"] = True
            active.append(event)


def _timed_segments(current, events, tz):
    """Clip multi-day events, then allocate non-overlapping visual columns."""
    start = timezone.make_aware(datetime.combine(current, time.min), tz)
    stop = timezone.make_aware(datetime.combine(current + timedelta(days=1), time.min), tz)
    segments = []
    for event in events:
        if not event.get("starts_at"):
            continue
        begins, ends = max(start, event["starts_at"]), min(stop, event["ends_at"])
        minutes = begins.hour * 60 + begins.minute
        end_minutes = 1440 if ends == stop else ends.hour * 60 + ends.minute + ends.second / 60
        # Short meetings retain a readable target; lanes also reserve that visual space.
        visual_start = minutes
        visual_end = max(end_minutes, visual_start + 36)
        segments.append({**event, "segment_start": begins, "segment_end": ends,
            "segment_time": begins.strftime("%H:%M") + "–" + ("24:00" if ends == stop else ends.strftime("%H:%M")),
            "continues_before": event["starts_at"] < start, "continues_after": event["ends_at"] > stop,
            "top": visual_start, "height": round(visual_end - visual_start, 2), "visual_end": visual_end})
    segments.sort(key=lambda item: (item["top"], -item["visual_end"], item["id"]))
    groups, group, latest = [], [], -1
    for segment in segments:
        if group and segment["top"] >= latest:
            groups.append(group)
            group = []
        group.append(segment)
        latest = max((item["visual_end"] for item in group))
    if group:
        groups.append(group)
    for group in groups:
        lanes = []
        for segment in group:
            lane = next((i for i, end in enumerate(lanes) if end <= segment["top"]), len(lanes))
            if lane == len(lanes):
                lanes.append(segment["visual_end"])
            else:
                lanes[lane] = segment["visual_end"]
            segment["lane"] = lane
        for segment in group:
            segment["left"] = round(segment["lane"] * 100 / len(lanes), 3)
            segment["width"] = round(100 / len(lanes), 3)
    return segments


def calendar_context(request, month=None, selected_day=None, kind="", today=None, view="month", responsible=None, status="all", valid_filters=True):
    """Shared context for full calendar and dashboard's compact calendar."""
    from .calendar_forms import CalendarFilterForm
    from .views import can_edit, scoped_queryset

    today = today or timezone.localdate()
    # Shared dashboard include also supports month/day/category navigation.
    filters = CalendarFilterForm(request.GET, request=request)
    if filters.is_valid():
        responsible = responsible or filters.cleaned_data.get("responsible")
        status = filters.cleaned_data.get("status", "all") if status == "all" else status
        if month is None:
            month = filters.cleaned_data.get("month")
            selected_day = selected_day or filters.cleaned_data.get("day")
            kind = kind or filters.cleaned_data.get("kind", "")
    else:
        valid_filters = False
    # Dashboard always defaults to its compact month, regardless of a view query string.
    view = view if view in ("week", "day") else "month"
    month = (month or selected_day or today).replace(day=1)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous_month = (month - timedelta(days=1)).replace(day=1)
    month_dates = list(calendar.Calendar(firstweekday=6).itermonthdates(month.year, month.month))
    if selected_day is None or (view == "month" and not month_dates[0] <= selected_day <= month_dates[-1]):
        selected_day = today if today.year == month.year and today.month == month.month else month
    if view == "week":
        first = selected_day - timedelta(days=selected_day.weekday())
        last = first + timedelta(days=6)
        first, last = max(first, date(1901, 1, 1)), min(last, date(2099, 12, 31))
        dates = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
    elif view == "day":
        first = last = selected_day
        dates = [selected_day]
    else:
        dates = month_dates
        first, last = dates[0], dates[-1]
    editable = can_edit(request)
    niche, choices = niche_selection(request)
    def records(model):
        queryset = filter_niche(scoped_queryset(request.user, request.organization, model), niche, choices, relation="matter__")
        if not valid_filters:
            return queryset.none()
        return queryset.filter(owner=responsible) if responsible else queryset

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
    now = timezone.now()
    for event in events:
        event["overdue"] = not event["done"] and not event.get("starts_at") and event["date"] < today
        event["ended"] = bool(event.get("ends_at") and event["ends_at"] <= now)
        event["state"] = "completed" if event["done"] else "overdue" if event["overdue"] else "ended" if event["ended"] else "pending"
        if event.get("starts_at"):
            event["status"] = "Encerrado" if event["ended"] else "Em andamento" if event["starts_at"] <= now else "Agendado"
    def matches_status(event):
        if status == "pending":
            return event["state"] in ("pending", "overdue")
        return status == "all" or event["state"] == status
    events = [event for event in events if matches_status(event)]
    period_events = [e for e in events if e["date"] < next_month and e["end_date"] >= month] if view == "month" else events[:]
    _mark_conflicts(events)
    counts = Counter(e["kind"] for e in period_events)
    conflict_count = sum(event["conflict"] for event in period_events)
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
    def url_for(*, target_day=None, target_month=None, target_view=None, target_kind=None):
        target_day = target_day or selected_day
        return "?" + urlencode({"month": (target_month or target_day).strftime("%Y-%m"), "day": target_day.isoformat(), "view": target_view or view, "kind": kind if target_kind is None else target_kind, "niche": niche, "responsible": responsible.pk if responsible else "", "status": status})

    cells = []
    for current in dates:
        day_events = per_day[current]
        segments = _timed_segments(current, day_events, tz) if view != "month" else []
        cells.append({"date": current, "valid_date": 1901 <= current.year <= 2099, "current_month": current.month == month.month, "today": current == today, "selected": current == selected_day, "events": day_events, "timed": segments, "all_day": [event for event in day_events if not event.get("starts_at")], "preview": day_events[:3], "extra": max(0, len(day_events) - 3), "kinds": sorted(set(e["kind"] for e in day_events)), "url": url_for(target_day=current, target_month=month) + "#calendar-detail", "day_url": url_for(target_day=current, target_view="day")})
    previous_day = previous_month if view == "month" else selected_day - timedelta(days=7 if view == "week" else 1)
    next_day = next_month if view == "month" else selected_day + timedelta(days=7 if view == "week" else 1)
    if view == "month":
        period_label = f"{MONTH_NAMES[month.month]} {month.year}"
    elif view == "week":
        period_label = f"{first:%d/%m} – {last:%d/%m/%Y}"
    else:
        period_label = f"{selected_day.day} de {MONTH_NAMES[selected_day.month].lower()} de {selected_day.year}"
    timed_hours = [segment["segment_start"].hour for cell in cells for segment in cell["timed"] if not segment["continues_before"]]
    result = {
        "calendar_month": month, "calendar_month_label": f"{MONTH_NAMES[month.month]} {month.year}",
        "calendar_previous": previous_month.strftime("%Y-%m") if month.year > 1901 or month.month > 1 else "",
        "calendar_next": next_month.strftime("%Y-%m") if month.year < 2099 or month.month < 12 else "",
        "calendar_today_month": today.strftime("%Y-%m"), "calendar_today": today,
        "calendar_days": cells, "calendar_selected_day": selected_day,
        "calendar_day_events": per_day[selected_day], "calendar_counts": dict(counts),
        "calendar_event_count": len(period_events), "calendar_kind": kind,
        "calendar_filters": [{"key": key, "label": label, "count": counts[key], "url": url_for(target_month=month, target_kind=key)} for key, label in EVENT_LABELS.items()],
        "calendar_agenda": [{"date": current, "events": per_day[current]} for current in dates if current.month == month.month and per_day[current]],
        "calendar_view": view, "calendar_period_label": period_label,
        "calendar_period_name": {"month": "no mês", "week": "na semana", "day": "no dia"}[view],
        "calendar_period_unit": {"month": "Mês", "week": "Semana", "day": "Dia"}[view],
        "calendar_previous_url": url_for(target_day=previous_day) if previous_day.year >= 1901 else "",
        "calendar_next_url": url_for(target_day=next_day) if next_day.year <= 2099 else "",
        "calendar_today_url": url_for(target_day=today), "calendar_all_url": url_for(target_month=month, target_kind=""),
        "calendar_views": [{"key": key, "label": label, "url": url_for(target_view=key)} for key, label in [("month", "Mês"), ("week", "Semana"), ("day", "Dia")]],
        "calendar_hours": [{"label": f"{hour:02d}:00", "top": hour * 60} for hour in range(24)],
        "calendar_scroll_start": max(0, min(timed_hours, default=8) - 1) * 60,
        "calendar_conflict_count": conflict_count,
        "calendar_responsible": responsible,
        "calendar_status": status,
        "calendar_filters_active": bool(responsible or status != "all" or niche or kind),
        "calendar_reset_url": "?" + urlencode({"month": month.strftime("%Y-%m"), "day": selected_day.isoformat(), "view": view}),
        "calendar_filter_form": filters,
        "can_edit": editable,
        "niche": niche, "niche_choices": choices,
    }
    if not valid_filters:
        result.update({"birthdays": [], "birthday_today_count": 0})
    elif view == "month":
        result.update(birthday_context(request, month=month, today=today))
    else:
        birthday_months = {current.replace(day=1) for current in dates}
        birthdays = [item for birthday_month in sorted(birthday_months) for item in birthday_context(request, month=birthday_month, today=today)["birthdays"] if first <= item["date"] <= last]
        result.update({"birthdays": birthdays, "birthday_today_count": sum(item["is_today"] for item in birthdays)})
    return result
