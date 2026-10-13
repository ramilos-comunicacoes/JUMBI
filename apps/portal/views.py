from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from apps.billing.services import has_advanced
from apps.legal.services import audit
from .forms import AccessForm, DecisionForm, MessageForm, PublishForm, ReviewForm, RevokeForm
from .models import ClientAccess, DocumentReview, Publication, ReviewDecision
from .services import (authorize_staff, decide_review, grant_access, membership_for, publish_version,
                       request_review, revoke, send_message, verified_source, visible_accesses,
                       visible_publications, visible_reviews)


def portal_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("core:login"))
        organization = getattr(request, "organization", None)
        member = membership_for(request.user, organization) if organization else None
        if not member or member.role not in {"client", "owner", "manager", "operator"}:
            raise PermissionDenied("Você não possui acesso ativo ao portal deste escritório.")
        request.membership = member
        return view(request, *args, **kwargs)
    return wrapped


def staff_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        authorize_staff(request.user, request.organization, write=False)
        return view(request, *args, **kwargs)
    return portal_access(wrapped)


def context(request, **extra):
    client = request.membership.role == "client"
    return {"page_title": "Portal do cliente" if client else "Revisão e portal", "active_nav": "portal",
            "portal_base": "portal/client_base.html" if client else "portal/staff_base.html",
            "portal_client": client, "portal_manager": request.membership.role in {"owner", "manager"},
            "portal_writable": has_advanced(request.organization), **extra}


def form_errors(form, error):
    for message in error.messages:
        form.add_error(None, message)


def form_page(request, form, title, *, subtitle="", submit="Salvar", back=None):
    return render(request, "portal/form.html", context(request, form=form, title=title, subtitle=subtitle, submit_label=submit, back=back or reverse("portal:manage")))


@require_GET
@portal_access
def home(request):
    if request.membership.role != "client":
        return redirect("portal:manage")
    publications = visible_publications(request.user, request.organization).select_related("review__version")
    return render(request, "portal/home.html", context(request, page=Paginator(publications, 18).get_page(request.GET.get("page"))))


@require_GET
@staff_access
def manage(request):
    reviews = visible_reviews(request.user, request.organization).select_related("version__document", "reviewer", "decision")
    state = request.GET.get("state", "pending")
    if state == "pending":
        reviews = reviews.filter(decision__isnull=True)
    elif state in ReviewDecision.Outcome.values:
        reviews = reviews.filter(decision__outcome=state)
    else:
        state = "all"
    pubs = visible_publications(request.user, request.organization, include_revoked=True).select_related("access__contact", "access__membership__user", "review__version")
    accesses = visible_accesses(request.user, request.organization).select_related("contact", "membership__user")
    return render(request, "portal/manage.html", context(request, state=state, page=Paginator(reviews, 20).get_page(request.GET.get("page")), publications=pubs[:30], accesses=accesses[:30]))


@require_http_methods(["GET", "POST"])
@staff_access
def access_create(request):
    authorize_staff(request.user, request.organization, manager=True)
    form = AccessForm(request.POST if request.method == "POST" else None, actor=request.user, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        try:
            grant_access(actor=request.user, organization=request.organization, membership=form.cleaned_data["membership"], contact=form.cleaned_data["contact"])
            messages.success(request, "Conta vinculada ao contato. Compartilhe os documentos individualmente após a revisão.")
            return redirect("portal:manage")
        except ValidationError as error:
            form_errors(form, error)
    return form_page(request, form, "Vincular conta de cliente", subtitle="Convide primeiro a pessoa pela Equipe com o perfil Cliente. O vínculo não libera pastas ou documentos automaticamente.", submit="Confirmar vínculo")


@require_http_methods(["GET", "POST"])
@staff_access
def review_create(request):
    authorize_staff(request.user, request.organization)
    form = ReviewForm(request.POST if request.method == "POST" else None, actor=request.user, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        try:
            review = request_review(actor=request.user, organization=request.organization, **form.cleaned_data)
            messages.success(request, "Revisão solicitada para esta versão exata.")
            return redirect("portal:review", pk=review.pk)
        except ValidationError as error:
            form_errors(form, error)
    return form_page(request, form, "Solicitar revisão", subtitle="O arquivo, o número da versão e a integridade ficam vinculados à decisão.", submit="Enviar para revisão")


@require_http_methods(["GET", "POST"])
@staff_access
def review_detail(request, pk):
    review = get_object_or_404(visible_reviews(request.user, request.organization).select_related("version__document", "reviewer", "requested_by", "decision"), pk=pk)
    decision = getattr(review, "decision", None)
    eligible = request.user.pk == review.reviewer_id and not decision and request.membership.role in {"owner", "manager"}
    form = DecisionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not eligible:
            raise PermissionDenied("Esta revisão não está disponível para sua decisão.")
        if form.is_valid():
            try:
                decide_review(actor=request.user, review=review, outcome=form.cleaned_data["outcome"], note=form.cleaned_data["note"])
                messages.success(request, "Decisão registrada. A aprovação não publica o arquivo automaticamente.")
                return redirect("portal:review", pk=review.pk)
            except ValidationError as error:
                form_errors(form, error)
    return render(request, "portal/review.html", context(request, review=review, decision=decision, eligible=eligible, form=form))


@require_http_methods(["GET", "POST"])
@staff_access
def publish(request, pk):
    authorize_staff(request.user, request.organization, manager=True)
    review = get_object_or_404(visible_reviews(request.user, request.organization).select_related("version__document__matter"), pk=pk, decision__outcome=ReviewDecision.Outcome.APPROVED)
    form = PublishForm(request.POST if request.method == "POST" else None, review=review, initial={"title": review.version.document.title})
    if request.method == "POST" and form.is_valid():
        try:
            publication = publish_version(actor=request.user, review=review, access=form.cleaned_data["access"], title=form.cleaned_data["title"], note=form.cleaned_data["note"])
            messages.success(request, "Versão aprovada publicada para o cliente selecionado.")
            return redirect("portal:publication", pk=publication.pk)
        except ValidationError as error:
            form_errors(form, error)
    return form_page(request, form, "Publicar versão aprovada", subtitle=f"{review.version.document.title} · versão {review.version.number}. Novas versões exigem outra revisão e publicação.", submit="Compartilhar com o cliente", back=reverse("portal:review", args=[review.pk]))


@require_http_methods(["GET", "POST"])
@portal_access
def publication_detail(request, pk):
    is_client = request.membership.role == "client"
    publication = get_object_or_404(visible_publications(request.user, request.organization, include_revoked=not is_client).select_related("review__version", "access__membership__user"), pk=pk)
    form = MessageForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            send_message(actor=request.user, publication=publication, body=form.cleaned_data["body"])
            messages.success(request, "Mensagem registrada nesta conversa.")
            return redirect("portal:publication", pk=publication.pk)
        except ValidationError as error:
            form_errors(form, error)
    thread = publication.messages.select_related("actor").order_by("-created_at", "-pk")
    thread_page = Paginator(thread, 30).get_page(request.GET.get("page"))
    return render(request, "portal/publication.html", context(request, publication=publication, form=form, thread_page=thread_page,
                  publication_active=not publication.revoked_at and not publication.access.revoked_at))


@require_GET
@portal_access
def download(request, pk):
    publication = get_object_or_404(visible_publications(request.user, request.organization).select_related("review__version"), pk=pk)
    version = publication.review.version
    source = verified_source(version, publication.review.checksum)
    audit(organization=request.organization, actor=request.user, action="portal.document_downloaded", obj=publication, description=f"Download autorizado da versão {version.number} publicada.")
    response = FileResponse(source, as_attachment=True, filename=version.original_name, content_type="application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET", "POST"])
@staff_access
def revoke_record(request, kind, pk):
    authorize_staff(request.user, request.organization, manager=True, write=False)
    queryset = visible_accesses(request.user, request.organization) if kind == "access" else visible_publications(request.user, request.organization, include_revoked=True)
    record = get_object_or_404(queryset, pk=pk)
    form = RevokeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            revoke(actor=request.user, record=record, reason=form.cleaned_data["reason"])
            messages.success(request, "Acesso revogado. Os registros de revisão e publicação foram preservados.")
            return redirect("portal:manage")
        except ValidationError as error:
            form_errors(form, error)
    return form_page(request, form, "Revogar vínculo" if kind == "access" else "Revogar publicação", subtitle="A revogação do vínculo retira todos os documentos deste contato da conta selecionada." if kind == "access" else "O cliente deixará de acessar esta publicação pelo portal.", submit="Confirmar revogação")
