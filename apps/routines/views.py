from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.billing.services import require_access
from apps.core.niches import practice_area_choices
from apps.legal.services import can_write, visible_matters
from apps.legal.views import organization_required
from .catalog import EXAMPLES
from .forms import ApplyForm, ChecklistForm, CheckStatusForm, CommentForm, TemplateForm, SectorTutorialForm
from .models import MatterChecklist, RoutineTemplate, SectorTutorial
from .services import (add_checklist, add_comment, apply_template, can_manage_templates,
    import_example, matter_context, save_template, set_checklist_status, visible_templates)


def _write(request):
    require_access(request.organization)
    if not can_write(request.user, request.organization):
        raise PermissionDenied("Seu perfil permite somente consulta.")


def _matter(request, pk):
    require_access(request.organization)
    return get_object_or_404(visible_matters(request.user, request.organization), pk=pk)


@organization_required
@require_GET
def template_list(request):
    require_access(request.organization)
    can_manage = can_manage_templates(request.user, request.organization)

    tab = request.GET.get("tab", "tutorials")
    selected_sector = request.GET.get("sector", "")

    # Tutorials query
    tutorials_qs = SectorTutorial.objects.filter(organization=request.organization)
    if not can_manage:
        tutorials_qs = tutorials_qs.filter(is_published=True)
    if selected_sector:
        tutorials_qs = tutorials_qs.filter(sector=selected_sector)
    tutorials = list(tutorials_qs)

    sector_counts = {}
    for code, label in SectorTutorial.Sector.choices:
        sector_counts[code] = SectorTutorial.objects.filter(
            organization=request.organization,
            sector=code,
            **({} if can_manage else {"is_published": True})
        ).count()

    # Checklist templates query
    niche = request.GET.get("niche", "")
    choices = practice_area_choices(request.organization)
    if niche and niche not in dict(choices):
        raise Http404("Área de atuação não configurada.")
    templates = visible_templates(request.user, request.organization)
    archived = request.GET.get("archived") == "1"
    templates = templates.filter(is_active=not archived)
    if niche:
        ids = [item.pk for item in templates.only("pk", "niches") if not item.niches or niche in item.niches]
        templates = templates.filter(pk__in=ids)
    page = Paginator(templates, 12).get_page(request.GET.get("page"))
    examples = [{"key": key, **value} for key, value in EXAMPLES.items()
                if not value["niches"] or set(value["niches"]) & set(request.organization.practice_areas)]

    return render(request, "routines/list.html", {
        "page_title": "Tutoriais & Rotinas por Nicho",
        "active_nav": "tutorials",
        "tab": tab,
        "tutorials": tutorials,
        "sector_choices": SectorTutorial.Sector.choices,
        "selected_sector": selected_sector,
        "sector_counts": sector_counts,
        "page": page,
        "examples": examples,
        "niche_choices": choices,
        "selected_niche": niche,
        "archived": archived,
        "can_manage_templates": can_manage,
    })


@organization_required
@require_http_methods(["GET", "POST"])
def template_edit(request, pk=None):
    require_access(request.organization)
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Somente direção e gestão podem editar modelos de rotina.")
    template = get_object_or_404(RoutineTemplate, pk=pk, organization=request.organization) if pk else None
    initial = {}
    if template:
        initial = {key: getattr(template, key) for key in ("title", "description", "niches", "is_active")}
        initial.update({key: "\n".join(getattr(template, key)) for key in ("tasks", "checklist", "documents")})
        initial["expected_version"] = template.version
    form = TemplateForm(request.POST or None, initial=initial, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_template(actor=request.user, organization=request.organization, data=form.cleaned_data,
                template_id=pk, expected_version=form.cleaned_data["expected_version"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Modelo salvo. Rotinas já aplicadas preservam a versão original.")
            return redirect("routines:detail", pk=saved.pk)
    return render(request, "routines/form.html", {"page_title": "Editar rotina" if pk else "Nova rotina",
        "active_nav": "routines", "form": form, "back_url": reverse("routines:list"), "submit_label": "Salvar modelo"})


@organization_required
@require_POST
def template_import(request, key):
    try:
        template = import_example(actor=request.user, organization=request.organization, key=key)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("routines:list")
    messages.success(request, "Exemplo disponível no catálogo. Revise e personalize para sua equipe.")
    return redirect("routines:edit", pk=template.pk)


@organization_required
@require_http_methods(["GET", "POST"])
def template_detail(request, pk):
    require_access(request.organization)
    template = get_object_or_404(visible_templates(request.user, request.organization), pk=pk)
    initial = {"matter": request.GET.get("matter"), "expected_version": template.version, "task_due_date": timezone.localdate()}
    form = ApplyForm(request.POST or None, initial=initial, organization=request.organization, user=request.user, template=template)
    confirmed = False
    preview_matter = None
    if request.method == "POST":
        _write(request)
        if form.is_valid():
            if request.POST.get("action") == "apply":
                try:
                    application, created = apply_template(actor=request.user, organization=request.organization,
                        template_id=template.pk, matter_id=form.cleaned_data["matter"].pk,
                        expected_version=form.cleaned_data["expected_version"], task_due_date=form.cleaned_data["task_due_date"])
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Rotina aplicada. As tarefas estão no Kanban e as conferências nesta pasta." if created else "Esta rotina já estava aplicada. Nenhum item foi duplicado.")
                    return redirect(reverse("routines:matter", args=[application.matter_id]))
            else:
                confirmed = True
                preview_matter = form.cleaned_data["matter"]
    return render(request, "routines/detail.html", {"page_title": template.title, "active_nav": "routines", "template": template,
        "form": form, "confirmed": confirmed, "preview_matter": preview_matter,
        "checklist_count": len(template.checklist) + len(template.documents),
        "can_apply": can_write(request.user, request.organization) and template.is_active,
        "can_manage_templates": can_manage_templates(request.user, request.organization)})


@organization_required
@require_http_methods(["GET", "POST"])
def matter_routine(request, pk):
    matter = _matter(request, pk)
    checklist_form = ChecklistForm(prefix="check")
    comment_form = CommentForm(prefix="comment")
    if request.method == "POST":
        _write(request)
        action = request.POST.get("action")
        if action not in {"check", "comment"}:
            raise Http404("Ação não encontrada.")
        form = ChecklistForm(request.POST, prefix="check") if action == "check" else CommentForm(request.POST, prefix="comment")
        if form.is_valid():
            try:
                if action == "check":
                    add_checklist(actor=request.user, matter=matter, **form.cleaned_data)
                else:
                    add_comment(actor=request.user, matter=matter, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Item adicionado." if action == "check" else "Comentário registrado no histórico.")
                return redirect("routines:matter", pk=matter.pk)
        if action == "check":
            checklist_form = form
        else:
            comment_form = form
    context = matter_context(request.user, request.organization, matter)
    return render(request, "routines/matter.html", {**context, "matter": matter, "checklist_form": checklist_form,
        "comment_form": comment_form, "page_title": "Rotina da pasta", "active_nav": "routines"})


@organization_required
@require_http_methods(["GET", "POST"])
def check_status(request, pk):
    _write(request)
    item = get_object_or_404(MatterChecklist, pk=pk, organization=request.organization,
        matter__in=visible_matters(request.user, request.organization))
    form = CheckStatusForm(request.POST or None, initial={"expected_version": item.version, "done": "0" if item.done else "1"})
    if request.method == "POST" and form.is_valid():
        try:
            set_checklist_status(actor=request.user, item=item, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Conferência atualizada com registro no histórico.")
            return redirect("routines:matter", pk=item.matter_id)
    return render(request, "routines/form.html", {"form": form, "page_title": item.title, "active_nav": "routines",
        "back_url": reverse("routines:matter", args=[item.matter_id]), "submit_label": "Registrar conferência"})


@organization_required
@require_GET
def tutorial_detail(request, pk):
    require_access(request.organization)
    can_manage = can_manage_templates(request.user, request.organization)
    tutorial = get_object_or_404(SectorTutorial, pk=pk, organization=request.organization)
    if not can_manage and not tutorial.is_published:
        raise Http404("Tutorial indisponível.")

    related_tutorials = SectorTutorial.objects.filter(
        organization=request.organization,
        sector=tutorial.sector,
        **({} if can_manage else {"is_published": True})
    ).exclude(pk=tutorial.pk)[:6]

    return render(request, "routines/tutorial_detail.html", {
        "page_title": tutorial.title,
        "active_nav": "tutorials",
        "tutorial": tutorial,
        "related_tutorials": related_tutorials,
        "can_manage": can_manage,
    })


@organization_required
@require_http_methods(["GET", "POST"])
def tutorial_create(request):
    require_access(request.organization)
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Apenas a gestão do escritório pode cadastrar novos tutoriais.")

    form = SectorTutorialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tutorial = form.save(commit=False)
        tutorial.organization = request.organization
        tutorial.created_by = request.user
        tutorial.save()
        messages.success(request, f"Tutorial '{tutorial.title}' cadastrado com sucesso!")
        return redirect("routines:tutorial_detail", pk=tutorial.pk)

    return render(request, "routines/tutorial_form.html", {
        "page_title": "Novo Tutorial / Treinamento",
        "active_nav": "tutorials",
        "form": form,
        "is_create": True,
        "back_url": reverse("routines:list"),
    })


@organization_required
@require_http_methods(["GET", "POST"])
def tutorial_edit(request, pk):
    require_access(request.organization)
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Apenas a gestão do escritório pode editar tutoriais.")

    tutorial = get_object_or_404(SectorTutorial, pk=pk, organization=request.organization)
    form = SectorTutorialForm(request.POST or None, instance=tutorial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Tutorial '{tutorial.title}' atualizado com sucesso!")
        return redirect("routines:tutorial_detail", pk=tutorial.pk)

    return render(request, "routines/tutorial_form.html", {
        "page_title": f"Editar: {tutorial.title}",
        "active_nav": "tutorials",
        "form": form,
        "tutorial": tutorial,
        "is_create": False,
        "back_url": reverse("routines:tutorial_detail", args=[tutorial.pk]),
    })


@organization_required
@require_POST
def tutorial_delete(request, pk):
    require_access(request.organization)
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Apenas a gestão do escritório pode excluir tutoriais.")

    tutorial = get_object_or_404(SectorTutorial, pk=pk, organization=request.organization)
    title = tutorial.title
    tutorial.delete()
    messages.success(request, f"Tutorial '{title}' removido com sucesso.")
    return redirect("routines:list")

