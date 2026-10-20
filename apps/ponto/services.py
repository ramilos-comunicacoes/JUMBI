import base64
import calendar
import datetime
import decimal
import hashlib
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.models import Membership
from .models import (
    WorkSchedule,
    EmployeeSchedule,
    HolidayOrDayOff,
    TimeRecord,
    TimeAdjustmentRequest,
)


def get_or_create_default_schedule(organization):
    """Garante que a organização possui uma escala padrão (44h semanais)."""
    schedule = WorkSchedule.objects.filter(organization=organization, is_default=True).first()
    if not schedule:
        schedule = WorkSchedule.objects.filter(organization=organization).first()
    if not schedule:
        schedule = WorkSchedule.objects.create(
            organization=organization,
            name="Padrão 44h Semanais",
            daily_expected_hours=8.0,
            tolerance_minutes=10,
            is_default=True,
            is_active=True,
            schedule_grid={
                "0": {"active": True, "start_1": "08:00", "end_1": "12:00", "start_2": "13:00", "end_2": "17:00", "expected_hours": 8.0},
                "1": {"active": True, "start_1": "08:00", "end_1": "12:00", "start_2": "13:00", "end_2": "17:00", "expected_hours": 8.0},
                "2": {"active": True, "start_1": "08:00", "end_1": "12:00", "start_2": "13:00", "end_2": "17:00", "expected_hours": 8.0},
                "3": {"active": True, "start_1": "08:00", "end_1": "12:00", "start_2": "13:00", "end_2": "17:00", "expected_hours": 8.0},
                "4": {"active": True, "start_1": "08:00", "end_1": "12:00", "start_2": "13:00", "end_2": "17:00", "expected_hours": 8.0},
                "5": {"active": True, "start_1": "08:00", "end_1": "12:00", "expected_hours": 4.0},
                "6": {"active": False, "is_day_off": True, "expected_hours": 0.0},
            }
        )
    return schedule


def get_employee_schedule(membership):
    """Retorna a jornada de trabalho vinculada ao colaborador, ou a padrão da empresa."""
    emp_sched = getattr(membership, "ponto_schedule", None)
    if emp_sched and emp_sched.schedule and emp_sched.schedule.is_active:
        return emp_sched.schedule
    return get_or_create_default_schedule(membership.organization)


def get_next_expected_record_type(membership, target_date=None):
    """
    Descobre inteligentemente qual é a próxima batida de ponto esperada para o colaborador hoje.
    Seq: entrada 1 -> saída 1 -> retorno 1 -> saída 2 -> extra.
    """
    if target_date is None:
        target_date = timezone.localdate()

    punches = TimeRecord.objects.filter(
        organization=membership.organization,
        membership=membership,
        recorded_date=target_date,
    ).order_by("timestamp")

    punched_types = [p.record_type for p in punches]

    if not punched_types:
        return TimeRecord.RecordType.ENTRY_1
    if TimeRecord.RecordType.ENTRY_1 in punched_types and TimeRecord.RecordType.EXIT_1 not in punched_types:
        return TimeRecord.RecordType.EXIT_1
    if TimeRecord.RecordType.EXIT_1 in punched_types and TimeRecord.RecordType.ENTRY_2 not in punched_types:
        return TimeRecord.RecordType.ENTRY_2
    if TimeRecord.RecordType.ENTRY_2 in punched_types and TimeRecord.RecordType.EXIT_2 not in punched_types:
        return TimeRecord.RecordType.EXIT_2
    # Se já bateu as 4 principais, sugere extra
    if len(punched_types) % 2 == 1:
        return TimeRecord.RecordType.EXIT_EXTRA
    return TimeRecord.RecordType.ENTRY_EXTRA


@transaction.atomic
def register_punch(
    membership,
    record_type=None,
    photo_snapshot="",
    photo_base64=None,
    face_detected=True,
    face_confidence=1.0,
    face_landmarks_count=0,
    latitude=None,
    longitude=None,
    location_accuracy=None,
    location_address="",
    ip_address=None,
    user_agent="",
    source=TimeRecord.Source.FACIAL_WEBCAM,
    timestamp=None,
    target_date=None,
    custom_datetime=None,
):
    """
    Grava a batida de ponto com carimbo inviolável de data/hora do servidor,
    foto comprovatória capturada pelo Google MediaPipe e geolocalização.
    """
    if custom_datetime is not None:
        timestamp = custom_datetime
    elif timestamp is None:
        if target_date is not None:
            now_time = timezone.localtime().time()
            dt = datetime.datetime.combine(target_date, now_time)
            timestamp = timezone.make_aware(dt, timezone.get_current_timezone())
        else:
            timestamp = timezone.now()

    recorded_date = timestamp.date()

    if not record_type:
        record_type = get_next_expected_record_type(membership, recorded_date)

    photo_data = photo_snapshot or photo_base64 or ""

    record = TimeRecord(
        organization=membership.organization,
        membership=membership,
        timestamp=timestamp,
        recorded_date=recorded_date,
        record_type=record_type,
        source=source,
        photo_snapshot=photo_data,
        face_detected=bool(face_detected),
        face_confidence=float(face_confidence or 0.0),
        face_landmarks_count=int(face_landmarks_count or 0),
        latitude=latitude,
        longitude=longitude,
        location_accuracy=location_accuracy,
        location_address=location_address or "",
        ip_address=ip_address,
        user_agent=user_agent or "",
    )
    record.hash_sha256 = record.calculate_hash()
    record.save()
    return record


def format_minutes_to_hours(minutes):
    """Converte minutos inteiros em string formatada (ex: 8h 15m ou -0h 30m)."""
    is_negative = minutes < 0
    abs_mins = abs(minutes)
    h = abs_mins // 60
    m = abs_mins % 60
    prefix = "-" if is_negative else ""
    return f"{prefix}{h:02d}:{m:02d}"


def calculate_daily_timesheet(membership, day_date, schedule, punches=None, holidays_dict=None, approved_requests=None):
    """
    Calcula os totais e ocorrências do dia para a folha de ponto.
    Retorna dicionário pronto para renderização no espelho de ponto.
    """
    if schedule is None:
        schedule = get_employee_schedule(membership)

    if holidays_dict is None:
        holidays_qs = HolidayOrDayOff.objects.filter(
            organization=membership.organization,
            date=day_date
        )
        holidays_dict = {h.date: h.name for h in holidays_qs}

    if punches is None:
        punches = list(TimeRecord.objects.filter(
            organization=membership.organization,
            membership=membership,
            recorded_date=day_date
        ).order_by("timestamp"))

    weekday_idx = str(day_date.weekday())
    day_grid = schedule.schedule_grid.get(weekday_idx, {}) if schedule.schedule_grid else {}
    is_workday = day_grid.get("active", True) and not day_grid.get("is_day_off", False)
    expected_hours = Decimal(str(day_grid.get("expected_hours", schedule.daily_expected_hours if is_workday else 0)))

    # Verifica feriado
    holiday_name = holidays_dict.get(day_date)
    is_holiday = bool(holiday_name)

    # Batidas do dia ordenadas
    day_punches = [p for p in punches if p.recorded_date == day_date]
    day_punches.sort(key=lambda x: x.timestamp)

    # Identificar batidas específicas ou ordens
    p_entry_1 = next((p for p in day_punches if p.record_type == TimeRecord.RecordType.ENTRY_1), None)
    p_exit_1 = next((p for p in day_punches if p.record_type == TimeRecord.RecordType.EXIT_1), None)
    p_entry_2 = next((p for p in day_punches if p.record_type == TimeRecord.RecordType.ENTRY_2), None)
    p_exit_2 = next((p for p in day_punches if p.record_type == TimeRecord.RecordType.EXIT_2), None)
    extras = [p for p in day_punches if p.record_type in {TimeRecord.RecordType.ENTRY_EXTRA, TimeRecord.RecordType.EXIT_EXTRA}]

    # Se não foram usadas as chaves nominais, agrupa sequencialmente
    if not p_entry_1 and day_punches:
        p_entry_1 = day_punches[0] if len(day_punches) >= 1 else None
        p_exit_1 = day_punches[1] if len(day_punches) >= 2 else None
        p_entry_2 = day_punches[2] if len(day_punches) >= 3 else None
        p_exit_2 = day_punches[3] if len(day_punches) >= 4 else None

    # Cálculo dos minutos trabalhados (pares)
    worked_minutes = 0
    pairs = []
    # Turno 1
    if p_entry_1 and p_exit_1 and p_exit_1.timestamp > p_entry_1.timestamp:
        diff = int((p_exit_1.timestamp - p_entry_1.timestamp).total_seconds() / 60)
        worked_minutes += diff
        pairs.append((p_entry_1, p_exit_1, diff))
    # Turno 2
    if p_entry_2 and p_exit_2 and p_exit_2.timestamp > p_entry_2.timestamp:
        diff = int((p_exit_2.timestamp - p_entry_2.timestamp).total_seconds() / 60)
        worked_minutes += diff
        pairs.append((p_entry_2, p_exit_2, diff))

    # Extras
    for i in range(0, len(extras) - 1, 2):
        e1, e2 = extras[i], extras[i + 1]
        if e2.timestamp > e1.timestamp:
            diff = int((e2.timestamp - e1.timestamp).total_seconds() / 60)
            worked_minutes += diff

    expected_minutes = int(expected_hours * 60)

    # Verifica atestado ou justificativa aprovada
    has_medical_leave = False
    justification_note = ""
    if approved_requests:
        for req in approved_requests:
            if req.date == day_date:
                if req.request_type == TimeAdjustmentRequest.RequestType.MEDICAL_LEAVE:
                    has_medical_leave = True
                    justification_note = "Atestado Médico / Licença"
                else:
                    justification_note = req.get_request_type_display()

    # Determinar status e saldo
    balance_minutes = 0
    status_label = "Normal"
    status_class = "ponto-status-working"
    status_key = "normal"

    today = timezone.localdate()

    if is_holiday:
        status_label = f"Feriado ({holiday_name})"
        status_class = "ponto-status-dayoff"
        status_key = "holiday"
        expected_minutes = 0
        balance_minutes = worked_minutes
    elif not is_workday:
        status_label = "Folga / DSR"
        status_class = "ponto-status-dayoff"
        status_key = "day_off"
        expected_minutes = 0
        balance_minutes = worked_minutes
    elif has_medical_leave:
        status_label = "Atestado Médico"
        status_class = "ponto-status-finished"
        status_key = "medical_leave"
        balance_minutes = 0
    elif day_date > today:
        status_label = "A Realizar"
        status_class = "ponto-status-dayoff"
        status_key = "future"
        balance_minutes = 0
    elif not day_punches:
        status_label = "Falta / Não Registrado"
        status_class = "ponto-status-absent"
        status_key = "absence"
        balance_minutes = -expected_minutes
    elif len(day_punches) % 2 != 0:
        status_label = "Em curso"
        status_class = "ponto-status-working"
        status_key = "working"
        balance_minutes = worked_minutes - expected_minutes
    else:
        diff_mins = worked_minutes - expected_minutes
        tolerance = schedule.tolerance_minutes
        if abs(diff_mins) <= tolerance:
            balance_minutes = 0
            status_label = "Jornada Cumprida"
            status_class = "ponto-status-working"
            status_key = "finished"
        elif diff_mins > 0:
            balance_minutes = diff_mins
            status_label = "Hora Extra"
            status_class = "ponto-status-working"
            status_key = "overtime"
        else:
            balance_minutes = diff_mins
            status_label = "Atraso / Débito"
            status_class = "ponto-status-absent"
            status_key = "delay"

    e1_time = p_entry_1.timestamp.strftime("%H:%M") if p_entry_1 else ""
    s1_time = p_exit_1.timestamp.strftime("%H:%M") if p_exit_1 else ""
    e2_time = p_entry_2.timestamp.strftime("%H:%M") if p_entry_2 else ""
    s2_time = p_exit_2.timestamp.strftime("%H:%M") if p_exit_2 else ""

    worked_formatted = format_minutes_to_hours(worked_minutes) if (worked_minutes or day_punches) else "00:00"
    expected_formatted = format_minutes_to_hours(expected_minutes) if expected_minutes else "Folga"
    balance_prefix = "+" if balance_minutes > 0 else ""
    balance_formatted = f"{balance_prefix}{format_minutes_to_hours(balance_minutes)}" if (day_punches or balance_minutes != 0) else "00:00"

    return {
        "date": day_date,
        "is_today": day_date == today,
        "is_weekend": day_date.weekday() in (5, 6),
        "weekday_name": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][day_date.weekday()],
        "entry_1": e1_time,
        "exit_1": s1_time,
        "entry_2": e2_time,
        "exit_2": s2_time,
        "entry_1_record": p_entry_1,
        "exit_1_record": p_exit_1,
        "entry_2_record": p_entry_2,
        "exit_2_record": p_exit_2,
        "punches": day_punches,
        "punches_count": len(day_punches),
        "worked_minutes": worked_minutes,
        "worked_formatted": worked_formatted,
        "worked_str": worked_formatted,
        "expected_minutes": expected_minutes,
        "expected_formatted": expected_formatted,
        "expected_str": expected_formatted,
        "balance_minutes": balance_minutes,
        "balance_formatted": balance_formatted,
        "balance_str": balance_formatted,
        "balance_is_positive": balance_minutes > 0,
        "balance_is_negative": balance_minutes < 0,
        "status_label": status_label,
        "status_class": status_class,
        "status_badge_class": status_class,
        "status_key": status_key,
        "is_workday": is_workday,
        "is_holiday": is_holiday,
        "holiday_name": holiday_name,
        "justification_note": justification_note,
    }


def get_monthly_timesheet(membership, year=None, month=None):
    """
    Calcula a folha de ponto completa de um colaborador para o mês e ano fornecidos.
    Retorna dias calculados, totais consolidados e banco de horas acumulado.
    """
    today = timezone.localdate()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    schedule = get_employee_schedule(membership)
    num_days = calendar.monthrange(year, month)[1]
    start_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, num_days)

    # Batidas do mês
    punches = list(TimeRecord.objects.filter(
        organization=membership.organization,
        membership=membership,
        recorded_date__gte=start_date,
        recorded_date__lte=end_date,
    ).select_related("membership__user").order_by("timestamp"))

    # Feriados do mês
    holidays = HolidayOrDayOff.objects.filter(
        organization=membership.organization,
        date__gte=start_date,
        date__lte=end_date,
    )
    holidays_dict = {h.date: h.name for h in holidays}

    # Atestados e ajustes aprovados
    approved_requests = list(TimeAdjustmentRequest.objects.filter(
        organization=membership.organization,
        membership=membership,
        date__gte=start_date,
        date__lte=end_date,
        status=TimeAdjustmentRequest.Status.APPROVED,
    ))

    days = []
    total_worked_mins = 0
    total_expected_mins = 0
    total_balance_mins = 0
    days_worked_count = 0
    absences_count = 0
    delays_count = 0
    overtime_count = 0

    for day_num in range(1, num_days + 1):
        day_date = datetime.date(year, month, day_num)
        day_data = calculate_daily_timesheet(
            membership=membership,
            day_date=day_date,
            schedule=schedule,
            punches=punches,
            holidays_dict=holidays_dict,
            approved_requests=approved_requests,
        )
        days.append(day_data)

        if day_data["date"] <= today:
            total_worked_mins += day_data["worked_minutes"]
            total_expected_mins += day_data["expected_minutes"]
            total_balance_mins += day_data["balance_minutes"]
            if day_data["punches_count"] > 0:
                days_worked_count += 1
            if day_data["status_key"] == "delay":
                delays_count += 1
            elif day_data["status_key"] == "overtime":
                overtime_count += 1
            elif day_data["status_key"] == "absence":
                absences_count += 1

    # Próximo e anterior mês para navegação
    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    month_names = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    total_worked_formatted = format_minutes_to_hours(total_worked_mins)
    total_expected_formatted = format_minutes_to_hours(total_expected_mins)
    balance_prefix = "+" if total_balance_mins > 0 else ""
    total_balance_formatted = f"{balance_prefix}{format_minutes_to_hours(total_balance_mins)}"

    return {
        "membership": membership,
        "employee_name": membership.user.get_full_name() or membership.user.email,
        "employee_email": membership.user.email,
        "employee_role": membership.position.name if getattr(membership, "position", None) else membership.get_role_display(),
        "schedule": schedule,
        "year": year,
        "month": month,
        "month_label": f"{month_names[month]} de {year}",
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "days": days,
        "total_worked_mins": total_worked_mins,
        "total_worked_formatted": total_worked_formatted,
        "total_worked_str": total_worked_formatted,
        "total_expected_mins": total_expected_mins,
        "total_expected_formatted": total_expected_formatted,
        "total_expected_str": total_expected_formatted,
        "total_balance_mins": total_balance_mins,
        "total_balance_minutes": total_balance_mins,
        "total_balance_formatted": total_balance_formatted,
        "total_balance_str": total_balance_formatted,
        "balance_is_positive": total_balance_mins > 0,
        "balance_is_negative": total_balance_mins < 0,
        "days_worked_count": days_worked_count,
        "absences_count": absences_count,
        "delays_count": delays_count,
        "overtime_count": overtime_count,
    }


def get_team_presence_summary(organization, target_date=None):
    """
    Retorna o status de presença de toda a equipe em tempo real para a data (hoje).
    """
    if target_date is None:
        target_date = timezone.localdate()

    members = list(Membership.objects.filter(
        organization=organization, is_active=True
    ).exclude(role=Membership.Role.CLIENT).select_related("user").order_by("user__first_name", "user__email"))

    punches = list(TimeRecord.objects.filter(
        organization=organization,
        recorded_date=target_date,
    ).order_by("timestamp"))

    team_status = []

    for m in members:
        user_punches = [p for p in punches if p.membership_id == m.pk]
        user_punches.sort(key=lambda x: x.timestamp)

        first_in = user_punches[0].timestamp if user_punches else None
        last_punch = user_punches[-1] if user_punches else None

        current_status = "not_started"
        current_status_label = "Não iniciou"
        current_status_badge = "ponto-status-absent"

        if not user_punches:
            current_status = "not_started"
            current_status_label = "Não bateu ponto"
            current_status_badge = "ponto-status-absent"
        else:
            last_type = last_punch.record_type
            if last_type in {TimeRecord.RecordType.ENTRY_1, TimeRecord.RecordType.ENTRY_2, TimeRecord.RecordType.ENTRY_EXTRA}:
                current_status = "working"
                current_status_label = "Trabalhando agora"
                current_status_badge = "ponto-status-working"
            elif last_type == TimeRecord.RecordType.EXIT_1:
                current_status = "lunch"
                current_status_label = "Em intervalo / almoço"
                current_status_badge = "ponto-status-lunch"
            elif last_type in {TimeRecord.RecordType.EXIT_2, TimeRecord.RecordType.EXIT_EXTRA}:
                current_status = "finished"
                current_status_label = "Expediente encerrado"
                current_status_badge = "ponto-status-finished"

        team_status.append({
            "membership": m,
            "name": m.user.get_full_name() or m.user.email,
            "email": m.user.email,
            "role": m.position.name if getattr(m, "position", None) else m.get_role_display(),
            "first_in": first_in,
            "last_punch": last_punch,
            "last_punch_time": last_punch.timestamp.strftime("%H:%M") if last_punch else "-",
            "punches_count": len(user_punches),
            "status": current_status,
            "status_label": current_status_label,
            "status_badge": current_status_badge,
            "status_class": current_status_badge,
            "punches": user_punches,
        })

    working_list = [t for t in team_status if t["status"] == "working"]
    lunch_list = [t for t in team_status if t["status"] == "lunch"]
    finished_list = [t for t in team_status if t["status"] == "finished"]
    not_started_list = [t for t in team_status if t["status"] == "not_started"]

    return {
        "date": target_date,
        "total_members": len(members),
        "working_count": len(working_list),
        "lunch_count": len(lunch_list),
        "finished_count": len(finished_list),
        "not_started_count": len(not_started_list),
        "working": working_list,
        "lunch": lunch_list,
        "finished": finished_list,
        "not_started": not_started_list,
        "members": team_status,
        "team": team_status,
    }
