import base64
import calendar
import csv
import datetime
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import Membership, Organization
from apps.core.services import member_has_module
from .models import (
    WorkSchedule,
    EmployeeSchedule,
    HolidayOrDayOff,
    TimeRecord,
    TimeAdjustmentRequest,
)
from .forms import (
    ManualTimeRecordForm,
    WorkScheduleForm,
    HolidayForm,
    TimeAdjustmentRequestForm,
)
from .services import (
    get_or_create_default_schedule,
    get_employee_schedule,
    get_next_expected_record_type,
    register_punch,
    get_monthly_timesheet,
    get_team_presence_summary,
    format_minutes_to_hours,
)


def _get_membership(request):
    """Obtém o vínculo de membro ativo do usuário no escritório atual."""
    membership = getattr(request, "membership", None)
    if not membership and request.user.is_authenticated:
        organization = getattr(request, "organization", None)
        if organization:
            membership = Membership.objects.filter(
                user=request.user, organization=organization, is_active=True
            ).first()
        if not membership:
            membership = Membership.objects.filter(
                user=request.user, is_active=True
            ).select_related("organization").first()
    return membership


def _get_context_membership_and_org(request):
    membership = _get_membership(request)
    if not membership:
        return None, None
    organization = getattr(request, "organization", None) or membership.organization
    return membership, organization


def _can_manage_ponto(membership):
    """Verifica se o usuário tem privilégio de gestão de ponto (Admin/Gerente/Owner)."""
    if not membership:
        return False
    if membership.role in {"owner", "manager"}:
        return True
    perms = getattr(membership, "permissions", None) or []
    return "ponto_admin" in perms or "team" in perms or "*" in perms


@login_required
def dashboard(request):
    """
    Painel Central do Ponto Eletrônico JUMBI.
    - Se for Colaborador: Tela rápida de Bater Ponto com Google MediaPipe + Resumo de Hoje + Meu Espelho.
    - Se for Gestor / Admin: Painel completo com abas de Presença da Equipe, Folha de Ponto Geral, Atestados e Escalas.
    """
    membership, organization = _get_context_membership_and_org(request)
    if not membership or not organization:
        messages.error(request, "Você não possui vínculo ativo com este escritório.")
        return redirect("core:home")

    can_manage = _can_manage_ponto(membership)
    active_tab = request.GET.get("tab", "clock" if not can_manage else "team")

    today = timezone.localdate()
    now_time = timezone.localtime().strftime("%H:%M")

    # Próxima batida esperada para o usuário logado
    next_record_type = get_next_expected_record_type(membership, today)

    # Batidas de hoje do usuário logado
    my_today_punches = list(TimeRecord.objects.filter(
        organization=organization,
        membership=membership,
        recorded_date=today,
    ).order_by("timestamp"))

    # Dados da equipe em tempo real (para gestor)
    team_data = get_team_presence_summary(organization, today) if can_manage else None

    # Solicitações pendentes (para gestor ou próprio)
    pending_requests_count = TimeAdjustmentRequest.objects.filter(
        organization=organization, status=TimeAdjustmentRequest.Status.PENDING
    ).count() if can_manage else TimeAdjustmentRequest.objects.filter(
        organization=organization, membership=membership, status=TimeAdjustmentRequest.Status.PENDING
    ).count()

    recent_adjustments = list(TimeAdjustmentRequest.objects.filter(
        organization=organization
    ).select_related("membership__user").order_by("-created_at")[:5]) if can_manage else list(TimeAdjustmentRequest.objects.filter(
        organization=organization, membership=membership
    ).select_related("membership__user").order_by("-created_at")[:5])

    # Próximos feriados cadastrados
    upcoming_holidays = list(HolidayOrDayOff.objects.filter(
        organization=organization, date__gte=today
    ).order_by("date")[:5])

    # Lista de colaboradores para o seletor da folha (se gestor)
    staff_members = list(Membership.objects.filter(
        organization=organization, is_active=True
    ).exclude(role=Membership.Role.CLIENT).select_related("user").order_by("user__first_name", "user__email")) if can_manage else []

    # Selected employee for team sheet
    selected_member_id = request.GET.get("member_id")
    target_member = membership
    if can_manage and selected_member_id:
        target_member = get_object_or_404(Membership, pk=selected_member_id, organization=organization)

    # Ano e mês selecionados
    try:
        req_year = int(request.GET.get("year", today.year))
        req_month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        req_year, req_month = today.year, today.month

    # Espelho de ponto do membro selecionado
    timesheet = get_monthly_timesheet(target_member, req_year, req_month)

    # Resumo do dia de hoje
    user_schedule = get_employee_schedule(membership)
    today_summary = next((d for d in timesheet["days"] if d["date"] == today), {})

    context = {
        "page_title": "Ponto Eletrônico & Jornada",
        "active_nav": "ponto",
        "active_tab": active_tab,
        "can_manage": can_manage,
        "can_manage_ponto": can_manage,
        "membership": membership,
        "target_member": target_member,
        "today": today,
        "now_time": now_time,
        "next_record_type": next_record_type,
        "today_punches": my_today_punches,
        "my_today_punches": my_today_punches,
        "today_summary": today_summary,
        "user_schedule": user_schedule,
        "team_data": team_data,
        "team_summary": team_data,
        "timesheet": timesheet,
        "staff_members": staff_members,
        "pending_requests_count": pending_requests_count,
        "pending_adjustments_count": pending_requests_count,
        "recent_adjustments": recent_adjustments,
        "upcoming_holidays": upcoming_holidays,
        "holidays_upcoming": upcoming_holidays,
        "record_type_choices": TimeRecord.RecordType.choices,
    }
    return render(request, "ponto/dashboard.html", context)


@login_required
def clock_in_kiosk(request):
    """Página dedicada com câmera facial ampliada para bater ponto."""
    membership, organization = _get_context_membership_and_org(request)
    if not membership or not organization:
        return redirect("core:home")

    today = timezone.localdate()
    next_record_type = get_next_expected_record_type(membership, today)
    today_punches = list(TimeRecord.objects.filter(
        organization=organization, membership=membership, recorded_date=today
    ).order_by("timestamp"))

    schedule = get_employee_schedule(membership)
    month_sheet = get_monthly_timesheet(membership, today.year, today.month)
    today_summary = next((d for d in month_sheet["days"] if d["date"] == today), {})

    context = {
        "page_title": "Bater Ponto Facial",
        "active_nav": "ponto",
        "can_manage_ponto": _can_manage_ponto(membership),
        "membership": membership,
        "schedule": schedule,
        "today": today,
        "next_record_type": next_record_type,
        "today_punches": today_punches,
        "today_summary": today_summary,
        "record_type_choices": TimeRecord.RecordType.choices,
    }
    return render(request, "ponto/clock_in.html", context)


@login_required
@require_POST
def register_punch_api(request):
    """
    API endpoint chamado via POST (fetch/AJAX) pelo scanner facial do Google MediaPipe.
    Recebe os dados biométricos, snapshot fotográfico e coordenadas de GPS.
    """
    membership, organization = _get_context_membership_and_org(request)
    if not membership or not organization:
        return JsonResponse({"status": "error", "message": "Vínculo de colaborador não encontrado."}, status=403)

    if request.content_type == "application/json":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            data = {}
    else:
        data = request.POST

    record_type = data.get("record_type")
    photo_snapshot = data.get("photo_snapshot") or data.get("photo_base64") or ""
    face_detected = data.get("face_detected") in {True, "true", "1", 1}
    face_confidence = float(data.get("face_confidence") or 0.0)
    face_landmarks_count = int(data.get("face_landmarks_count") or 0)

    # GPS
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    location_accuracy = data.get("location_accuracy")
    location_address = data.get("location_address", "")

    try:
        lat_val = float(latitude) if latitude else None
        lng_val = float(longitude) if longitude else None
        acc_val = float(location_accuracy) if location_accuracy else None
    except (ValueError, TypeError):
        lat_val, lng_val, acc_val = None, None, None

    # IP & User Agent
    ip_address = request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR")
    if ip_address and "," in ip_address:
        ip_address = ip_address.split(",")[0].strip()
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:250]

    record = register_punch(
        membership=membership,
        record_type=record_type,
        photo_snapshot=photo_snapshot,
        face_detected=face_detected,
        face_confidence=face_confidence,
        face_landmarks_count=face_landmarks_count,
        latitude=lat_val,
        longitude=lng_val,
        location_accuracy=acc_val,
        location_address=location_address,
        ip_address=ip_address,
        user_agent=user_agent,
        source=TimeRecord.Source.FACIAL_WEBCAM,
    )

    local_dt = timezone.localtime(record.timestamp)
    time_str = local_dt.strftime("%H:%M:%S")
    date_str = local_dt.strftime("%d/%m/%Y")

    return JsonResponse({
        "status": "success",
        "message": f"{record.get_record_type_display()} registrada com sucesso às {time_str}!",
        "record_id": record.pk,
        "record_type_display": record.get_record_type_display(),
        "time": time_str,
        "date": date_str,
        "hash_sha256": record.hash_sha256,
        "face_confidence_percent": f"{int(record.face_confidence * 100)}%",
        "receipt": {
            "employee_name": record.membership.user.get_full_name() or record.membership.user.email,
            "record_type": record.record_type,
            "record_type_label": record.get_record_type_display(),
            "time": time_str,
            "date": date_str,
            "hash_sha256": record.hash_sha256,
            "face_detected": record.face_detected,
            "face_confidence": record.face_confidence,
            "photo_snapshot": record.photo_snapshot,
        }
    })


@login_required
def my_timesheet(request):
    """Espelho de ponto do colaborador logado."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership:
        return redirect("core:home")

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    timesheet = get_monthly_timesheet(membership, year, month)
    
    month_names = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    month_name = month_names[month]

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    prev_month_url = reverse("ponto:my_timesheet") + f"?year={prev_year}&month={prev_month}"
    next_month_url = reverse("ponto:my_timesheet") + f"?year={next_year}&month={next_month}"

    context = {
        "page_title": "Meu Espelho de Ponto",
        "active_nav": "ponto",
        "can_manage_ponto": _can_manage_ponto(membership),
        "membership": membership,
        "timesheet": timesheet,
        "year": year,
        "month": month,
        "month_name": month_name,
        "prev_month_url": prev_month_url,
        "next_month_url": next_month_url,
        "can_manage": _can_manage_ponto(membership),
    }
    return render(request, "ponto/timesheet.html", context)


@login_required
def team_timesheet(request, membership_id=None):
    """Folha de ponto de qualquer colaborador visualizada pelo Gestor ou Admin."""
    current_member, organization = _get_context_membership_and_org(request)
    if not organization or not current_member or not _can_manage_ponto(current_member):
        messages.error(request, "Acesso restrito a gestores e administradores.")
        return redirect("ponto:dashboard")

    if not membership_id:
        membership_id = request.GET.get("member_id")

    target_member = get_object_or_404(
        Membership, pk=membership_id, organization=organization, is_active=True
    ) if membership_id else current_member

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    timesheet = get_monthly_timesheet(target_member, year, month)
    staff_members = list(Membership.objects.filter(
        organization=organization, is_active=True
    ).exclude(role=Membership.Role.CLIENT).select_related("user").order_by("user__first_name"))

    month_names = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    context = {
        "page_title": f"Folha de Ponto · {target_member.user.get_full_name() or target_member.user.email}",
        "active_nav": "ponto",
        "can_manage_ponto": True,
        "membership": current_member,
        "selected_member": target_member,
        "target_member": target_member,
        "timesheet": timesheet,
        "team_members": staff_members,
        "staff_members": staff_members,
        "year": year,
        "month": month,
        "month_name": month_names[month],
        "can_manage": True,
    }
    return render(request, "ponto/team_timesheet.html", context)


@login_required
def manual_punch_create(request):
    """Inclusão manual de batida de ponto com justificativa obrigatória."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        messages.error(request, "Apenas administradores e gestores podem incluir batidas manuais.")
        return redirect("ponto:dashboard")

    if request.method == "POST":
        form = ManualTimeRecordForm(request.POST, organization=organization)
        if form.is_valid():
            record = form.save(commit=False)
            record.organization = organization
            record.source = TimeRecord.Source.MANUAL_ADMIN
            record.is_manually_adjusted = True
            record.adjusted_by = membership

            time_val = form.cleaned_data.get("punch_time") or form.cleaned_data.get("time_str")
            rec_date = form.cleaned_data["recorded_date"]
            dt = datetime.datetime.combine(rec_date, time_val)
            dt_aware = timezone.make_aware(dt, timezone.get_current_timezone())
            record.timestamp = dt_aware
            record.hash_sha256 = record.calculate_hash()
            record.save()

            messages.success(request, f"Batida manual de {record.get_record_type_display()} incluída para {record.membership.user.get_full_name() or record.membership.user.email}.")
            return redirect(reverse("ponto:team_timesheet") + f"?member_id={record.membership.pk}&year={rec_date.year}&month={rec_date.month}")
    else:
        initial = {
            "recorded_date": timezone.localdate(),
            "punch_time": timezone.localtime().strftime("%H:%M"),
        }
        member_id = request.GET.get("member_id")
        if member_id:
            initial["membership"] = member_id
        date_param = request.GET.get("date")
        if date_param:
            try:
                initial["recorded_date"] = datetime.date.fromisoformat(date_param)
            except ValueError:
                pass
        form = ManualTimeRecordForm(initial=initial, organization=organization)

    context = {
        "page_title": "Inserir Batida Manual",
        "active_nav": "ponto",
        "can_manage_ponto": True,
        "form": form,
    }
    return render(request, "ponto/manual_punch_form.html", context)


@login_required
def manual_punch_delete(request, pk):
    """Exclusão de batida com auditoria."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        messages.error(request, "Permissão negada.")
        return redirect("ponto:dashboard")

    record = get_object_or_404(TimeRecord, pk=pk, organization=organization)
    rec_date = record.recorded_date
    target_member_id = record.membership_id
    user_name = record.membership.user.get_full_name() or record.membership.user.email

    if request.method == "POST":
        record.delete()
        messages.success(request, f"Batida de {user_name} excluída com sucesso. Motivo registrado em auditoria.")
        return redirect(reverse("ponto:team_timesheet") + f"?member_id={target_member_id}&year={rec_date.year}&month={rec_date.month}")

    return render(request, "ponto/confirm_delete_punch.html", {"record": record, "punch": record, "can_manage_ponto": True})


@login_required
def adjustment_request_create(request):
    """Colaborador envia justificativa, atestado médico ou pedido de ajuste de batida."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership:
        return redirect("core:home")

    if request.method == "POST":
        form = TimeAdjustmentRequestForm(request.POST, request.FILES)
        if form.is_valid():
            req = form.save(commit=False)
            req.organization = organization
            req.membership = membership
            req.status = TimeAdjustmentRequest.Status.PENDING

            # Converte anexo para base64 se enviado
            if req.attachment:
                try:
                    req.attachment.seek(0)
                    content = req.attachment.read()
                    encoded = base64.b64encode(content).decode("ascii")
                    mime = getattr(req.attachment, "content_type", "application/octet-stream")
                    req.attachment_base64 = f"data:{mime};base64,{encoded}"
                except Exception:
                    pass

            req.save()
            messages.success(request, "Sua solicitação de ajuste / atestado foi enviada ao gestor com sucesso!")
            return redirect("ponto:adjustments_list")
    else:
        initial = {"date": timezone.localdate()}
        date_param = request.GET.get("date")
        if date_param:
            try:
                initial["date"] = datetime.date.fromisoformat(date_param)
            except ValueError:
                pass
        form = TimeAdjustmentRequestForm(initial=initial)

    context = {
        "page_title": "Solicitar Ajuste ou Enviar Atestado",
        "active_nav": "ponto",
        "can_manage_ponto": _can_manage_ponto(membership),
        "form": form,
    }
    return render(request, "ponto/adjustment_request_form.html", context)


@login_required
def adjustment_requests_list(request):
    """Lista de solicitações pendentes e histórico para o Gestor e Colaborador."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership:
        return redirect("core:home")

    can_manage = _can_manage_ponto(membership)
    status_filter = request.GET.get("status", "all" if not can_manage else "pending")
    qs = TimeAdjustmentRequest.objects.filter(organization=organization).select_related("membership__user")

    if not can_manage:
        qs = qs.filter(membership=membership)

    if status_filter != "all":
        qs = qs.filter(status=status_filter)

    qs = qs.order_by("-created_at")

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    context = {
        "page_title": "Solicitações de Ajuste & Atestados",
        "active_nav": "ponto",
        "can_manage_ponto": can_manage,
        "requests": page_obj,
        "status_filter": status_filter,
    }
    return render(request, "ponto/adjustment_requests_list.html", context)


@login_required
@require_POST
def adjustment_request_decide(request, pk):
    """Gestor aprova ou rejeita solicitação de ajuste."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        return JsonResponse({"status": "error", "message": "Sem permissão."}, status=403)

    adj_request = get_object_or_404(TimeAdjustmentRequest, pk=pk, organization=organization)
    decision = request.POST.get("decision") or request.POST.get("action")  # 'approve' ou 'reject'
    review_notes = request.POST.get("review_notes", "").strip()

    if decision == "approve":
        adj_request.status = TimeAdjustmentRequest.Status.APPROVED
        adj_request.reviewed_by = membership
        adj_request.reviewed_at = timezone.now()
        adj_request.review_notes = review_notes
        adj_request.save()

        # Se tiver horário e tipo de batida especificados, cria a batida automaticamente
        if adj_request.suggested_time and adj_request.suggested_record_type:
            dt = datetime.datetime.combine(adj_request.date, adj_request.suggested_time)
            dt_aware = timezone.make_aware(dt, timezone.get_current_timezone())
            TimeRecord.objects.create(
                organization=organization,
                membership=adj_request.membership,
                timestamp=dt_aware,
                recorded_date=adj_request.date,
                record_type=adj_request.suggested_record_type,
                source=TimeRecord.Source.SYSTEM_ADJUSTED,
                is_manually_adjusted=True,
                adjustment_reason=f"Ajuste aprovado: {adj_request.reason}",
                adjusted_by=membership,
                hash_sha256=TimeRecord(
                    organization=organization,
                    membership=adj_request.membership,
                    timestamp=dt_aware,
                    recorded_date=adj_request.date,
                    record_type=adj_request.suggested_record_type,
                    source=TimeRecord.Source.SYSTEM_ADJUSTED,
                ).calculate_hash(),
            )

        messages.success(request, f"Solicitação de {adj_request.membership.user.get_full_name() or adj_request.membership.user.email} APROVADA!")
    elif decision == "reject":
        adj_request.status = TimeAdjustmentRequest.Status.REJECTED
        adj_request.reviewed_by = membership
        adj_request.reviewed_at = timezone.now()
        adj_request.review_notes = review_notes
        adj_request.save()
        messages.info(request, "Solicitação rejeitada.")

    return redirect(request.META.get("HTTP_REFERER", reverse("ponto:adjustments_list")))


@login_required
def schedules_manage(request):
    """Gestão de Jornadas de Trabalho e Horários da Empresa."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        messages.error(request, "Acesso restrito.")
        return redirect("ponto:dashboard")

    schedules = WorkSchedule.objects.filter(organization=organization)
    if not schedules.exists():
        get_or_create_default_schedule(organization)
        schedules = WorkSchedule.objects.filter(organization=organization)

    context = {
        "page_title": "Jornadas & Escalas de Trabalho",
        "active_nav": "ponto",
        "can_manage_ponto": True,
        "schedules": schedules,
    }
    return render(request, "ponto/schedules_manage.html", context)


@login_required
def schedule_edit(request, pk=None):
    """Criação ou edição de jornada de trabalho."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        return redirect("ponto:dashboard")

    schedule = get_object_or_404(WorkSchedule, pk=pk, organization=organization) if pk else None

    if request.method == "POST":
        form = WorkScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            sched = form.save(commit=False)
            sched.organization = organization
            sched.save()
            messages.success(request, f"Jornada '{sched.name}' salva com sucesso!")
            return redirect("ponto:schedules_manage")
    else:
        form = WorkScheduleForm(instance=schedule)

    context = {
        "page_title": f"{'Editar' if schedule else 'Nova'} Jornada de Trabalho",
        "active_nav": "ponto",
        "can_manage_ponto": True,
        "form": form,
        "schedule": schedule,
    }
    return render(request, "ponto/schedule_form.html", context)


@login_required
def holidays_manage(request):
    """Gestão de Feriados e Folgas Coletivas da Empresa."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        return redirect("ponto:dashboard")

    if request.method == "POST":
        form = HolidayForm(request.POST)
        if form.is_valid():
            hol = form.save(commit=False)
            hol.organization = organization
            hol.save()
            messages.success(request, f"Feriado / folga '{hol.name}' cadastrado com sucesso!")
            return redirect("ponto:holidays_manage")
    else:
        form = HolidayForm()

    holidays = HolidayOrDayOff.objects.filter(organization=organization).order_by("-date")
    context = {
        "page_title": "Calendário de Feriados & Folgas",
        "active_nav": "ponto",
        "can_manage_ponto": True,
        "form": form,
        "holidays": holidays,
    }
    return render(request, "ponto/holidays_manage.html", context)


@login_required
def holiday_delete(request, pk):
    """Exclusão de feriado cadastrado."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership or not _can_manage_ponto(membership):
        return redirect("ponto:dashboard")

    hol = get_object_or_404(HolidayOrDayOff, pk=pk, organization=organization)
    hol.delete()
    messages.success(request, "Feriado removido do calendário.")
    return redirect("ponto:holidays_manage")


@login_required
def export_timesheet_print(request, membership_id=None):
    """Emissão de espelho de ponto oficial para conferência e assinatura do colaborador."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership:
        return redirect("core:home")

    can_manage = _can_manage_ponto(membership)
    if membership_id and can_manage:
        target_member = get_object_or_404(Membership, pk=membership_id, organization=organization)
    else:
        target_member = membership

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    timesheet = get_monthly_timesheet(target_member, year, month)
    month_names = [
        "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    context = {
        "organization": organization,
        "membership": target_member,
        "timesheet": timesheet,
        "year": year,
        "month": month,
        "month_name": month_names[month],
        "emission_date": timezone.now(),
    }
    return render(request, "ponto/timesheet_print.html", context)


@login_required
def export_timesheet_csv(request, membership_id=None):
    """Exportação da folha de ponto em formato CSV para departamento pessoal / contabilidade."""
    membership, organization = _get_context_membership_and_org(request)
    if not organization or not membership:
        return redirect("core:home")

    can_manage = _can_manage_ponto(membership)
    if membership_id and can_manage:
        target_member = get_object_or_404(Membership, pk=membership_id, organization=organization)
    else:
        target_member = membership

    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (ValueError, TypeError):
        year, month = today.year, today.month

    timesheet = get_monthly_timesheet(target_member, year, month)

    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    user_slug = (target_member.user.get_full_name() or target_member.user.email).replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="folha_ponto_{user_slug}_{year}_{month:02d}.csv"'

    writer = csv.writer(response, delimiter=";")
    writer.writerow(["EMPRESA", organization.name])
    writer.writerow(["COLABORADOR", target_member.user.get_full_name() or target_member.user.email])
    writer.writerow(["CARGO", target_member.position.name if getattr(target_member, "position", None) else target_member.get_role_display()])
    writer.writerow(["PERÍODO", f"{timesheet['month_label']}"])
    writer.writerow([])
    writer.writerow(["DATA", "DIA", "ENTRADA 1", "SAÍDA 1", "ENTRADA 2", "SAÍDA 2", "TRABALHADO", "PREVISTO", "SALDO", "SITUAÇÃO", "HASH / PROTOCOLO"])

    for d in timesheet["days"]:
        e1 = d["entry_1"]
        s1 = d["exit_1"]
        e2 = d["entry_2"]
        s2 = d["exit_2"]
        first_hash = d["punches"][0].hash_sha256[:16] if d["punches"] else ""

        writer.writerow([
            d["date"].strftime("%d/%m/%Y"),
            d["weekday_name"],
            e1,
            s1,
            e2,
            s2,
            d["worked_formatted"],
            d["expected_formatted"],
            d["balance_formatted"],
            d["status_label"],
            first_hash,
        ])

    writer.writerow([])
    writer.writerow(["RESUMO", "TOTAL TRABALHADO", timesheet["total_worked_formatted"], "PREVISTO", timesheet["total_expected_formatted"], "SALDO ACUMULADO", timesheet["total_balance_formatted"]])

    return response
