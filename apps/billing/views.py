from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.http import Http404
from django.views.decorators.http import require_http_methods, require_GET
from apps.core.models import Organization
from .models import OrganizationSubscription, SubscriptionEvent
from .plans import PLAN_CHOICES, PLANS
from .services import subscription_for, usage


@require_GET
def contact(request, plan):
    selected = PLANS.get(plan)
    if selected is None:
        raise Http404("Plano não encontrado.")
    matter_limit = f"{selected['matters']:,}".replace(",", ".")
    version_limit = f"{selected['versions']:,}".replace(",", ".")
    text = (
        f"Olá! Quero assinar o JUMBI {selected['name']} por R$ {selected['price_label']}/mês.\n\n"
        f"Plano para até {selected['members']} usuários ativos, {matter_limit} pastas ativas e {version_limit} versões de documentos.\n"
        "Com gestão jurídica, calendário, Kanban e relacionamento com clientes (CRM).\n"
    )
    if selected["advanced"]:
        text += "Inclui também financeiro, honorários, montagem de contratos, revisão e publicação no portal do cliente, estoque e patrimônio.\n"
    organization = getattr(request, "organization", None)
    membership = getattr(request, "membership", None)
    if organization and membership and membership.role == "owner" and "demonstracao" not in organization.slug:
        text += f"Escritório: {organization.name}.\n"
    text += "\nPode me orientar sobre a contratação e a ativação?"
    response = redirect("https://wa.me/5588992745456?" + urlencode({"text": text}))
    response["Cache-Control"] = "private, no-store"
    return response


class PlanRequestForm(forms.Form):
    plan = forms.ChoiceField(label="Plano desejado", choices=PLAN_CHOICES)


@login_required
@require_http_methods(["GET", "POST"])
def subscription(request):
    org = getattr(request, "organization", None)
    if not org or not request.membership:
        raise PermissionDenied("Selecione um escritório para consultar a assinatura.")
    current = subscription_for(org)
    form = PlanRequestForm(request.POST if request.method == "POST" else None, initial={"plan": current.plan if current else "start"})
    if request.method == "POST":
        if request.membership.role != "owner":
            raise PermissionDenied("Somente a direção pode solicitar a alteração contratual.")
        if form.is_valid():
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=org.pk)
                current, _ = OrganizationSubscription.objects.get_or_create(organization=org)
                current.requested_plan = form.cleaned_data["plan"]
                current.save(update_fields=["requested_plan", "updated_at"])
                SubscriptionEvent.objects.create(subscription=current, actor=request.user, description=f"Solicitada contratação/alteração para {current.requested_plan}. Não representa pagamento nem liberação automática.")
            messages.success(request, "Solicitação registrada. A administração fará a ativação após a contratação; nenhuma cobrança automática foi realizada.")
            return redirect("billing:subscription")
    return render(request, "billing/subscription.html", {"subscription": current, "usage": usage(org), "form": form, "page_title": "Plano e assinatura", "active_nav": "subscription"})
