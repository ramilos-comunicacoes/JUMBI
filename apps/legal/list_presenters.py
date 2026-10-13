"""Page-specific read models, always built from the already authorized queryset."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Prefetch, Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import DocumentVersion, FinanceEntry, Opportunity, Payment


MODULE_PAGES = {
    "matters": ("CARTEIRA JURÍDICA", "Cada demanda tem seu lugar.", "Reúna processos, documentos e entregas dentro de uma pasta.", "Nova pasta", "Buscar título, cliente ou área…", "Situação", "Crie sua primeira pasta", "Vincule um cliente e defina o responsável para organizar o trabalho."),
    "contacts": ("DIRETÓRIO DO ESCRITÓRIO", "As pessoas por trás de cada caso.", "Mantenha contatos e datas de nascimento atualizados em um único cadastro.", "Nova pessoa", "Buscar nome, CPF/CNPJ, e-mail ou telefone…", "Tipo de pessoa", "Seu diretório começa aqui", "Cadastre pessoas físicas e jurídicas para vinculá-las às pastas e oportunidades."),
    "cases": ("REGISTRO PROCESSUAL", "Do número ao contexto do caso.", "Consulte os processos cadastrados e abra a pasta para acompanhar o trabalho relacionado.", "Novo processo", "Buscar número, tribunal, pasta ou parte…", "Situação", "Cadastre o primeiro processo", "Informe o número e o órgão responsável e vincule o processo a uma pasta."),
    "deadlines": ("CONTROLADORIA", "O próximo prazo pede atenção.", "Confira a origem, valide o vencimento e registre a evidência do cumprimento.", "Novo prazo", "Buscar obrigação, publicação ou pasta…", "Etapa do prazo", "Nenhum prazo cadastrado", "Registre a obrigação, sua origem e a data de vencimento para iniciar a conferência."),
    "documents": ("BIBLIOTECA PRIVADA", "Arquivos organizados. Histórico preservado.", "Baixe a versão atual ou envie uma nova versão sem substituir o histórico.", "Novo documento", "Buscar título, classificação ou pasta…", "Situação", "Monte a biblioteca do escritório", "Adicione um arquivo a uma pasta. O acesso acompanha as permissões dessa pasta."),
    "finance": ("LIVRO-CAIXA", "Previsão e movimentação, lado a lado.", "Registre baixas e estornos para manter os saldos de cada lançamento conferíveis.", "Novo lançamento", "Buscar descrição ou pasta…", "Tipo de lançamento", "Seu financeiro começa com um lançamento", "Separe receitas, despesas e valores de clientes desde o cadastro."),
    "crm": ("RELACIONAMENTO", "Cada conversa tem um próximo passo.", "Atualize a etapa e a próxima ação no atendimento. As estimativas não são receitas realizadas.", "Nova oportunidade", "Buscar oportunidade, pessoa ou próxima ação…", "Etapa", "Abra a primeira oportunidade", "Vincule uma pessoa, indique o responsável e descreva o próximo contato."),
}


def prepare_queryset(queryset, module):
    if module == "documents":
        return queryset.prefetch_related(Prefetch("versions", queryset=DocumentVersion.objects.order_by("-number"), to_attr="list_versions"))
    if module == "finance":
        return queryset.prefetch_related(Prefetch("payments", queryset=Payment.objects.all(), to_attr="list_payments"))
    return queryset


def stats_for(queryset, module):
    """Totals cover all filtered records, not only the current page."""
    today = timezone.localdate()
    if module == "matters":
        values = queryset.aggregate(active=Count("pk", filter=Q(status="active")), waiting=Count("pk", filter=Q(status="waiting")), closed=Count("pk", filter=Q(status="closed")))
        labels = [("active", "Em andamento"), ("waiting", "Aguardando"), ("closed", "Encerradas")]
    elif module == "contacts":
        values = queryset.aggregate(person=Count("pk", filter=Q(kind="person")), company=Count("pk", filter=Q(kind="company")), birthday=Count("pk", filter=Q(birth_date__month=today.month, birth_date__day=today.day)))
        labels = [("person", "Pessoas físicas"), ("company", "Pessoas jurídicas"), ("birthday", "Aniversários hoje")]
    elif module == "cases":
        values = queryset.aggregate(total=Count("pk"), matters=Count("matter", distinct=True), courts=Count("court", distinct=True, filter=~Q(court="")))
        labels = [("total", "Processos"), ("matters", "Pastas vinculadas"), ("courts", "Órgãos informados")]
    elif module == "deadlines":
        open_deadlines = ~Q(status="fulfilled")
        values = queryset.aggregate(pending=Count("pk", filter=Q(status="pending")), overdue=Count("pk", filter=open_deadlines & Q(due_date__lt=today)), soon=Count("pk", filter=open_deadlines & Q(due_date__gte=today, due_date__lte=today + timedelta(days=7))))
        labels = [("pending", "A conferir"), ("overdue", "Vencidos em aberto"), ("soon", "Hoje e próximos 7 dias")]
    elif module == "documents":
        values = queryset.aggregate(total=Count("pk", distinct=True), versions=Count("versions"), matters=Count("matter", distinct=True))
        labels = [("total", "Documentos"), ("versions", "Versões preservadas"), ("matters", "Pastas vinculadas")]
    elif module == "crm":
        values = queryset.aggregate(open=Count("pk", filter=~Q(stage__in=["won", "lost"])), awaiting=Count("pk", filter=Q(next_action__regex=r"^\s*$") & ~Q(stage__in=["won", "lost"])), won=Count("pk", filter=Q(stage="won")))
        labels = [("open", "Em negociação"), ("awaiting", "Sem próxima ação"), ("won", "Ganhas")]
    else:
        return []
    return [{"label": label, "value": values[key], "key": key} for key, label in labels]


def finance_totals(queryset, money_label):
    totals = {row["kind"]: row["amount"] for row in queryset.order_by().values("kind").annotate(amount=Sum("amount"))}
    payments = Payment.objects.filter(entry__in=queryset).order_by().values("entry__kind").annotate(received=Sum("amount", filter=Q(reversal_of__isnull=True)), reversed=Sum("amount", filter=Q(reversal_of__isnull=False)))
    moved = {row["entry__kind"]: (row["received"] or Decimal("0")) - (row["reversed"] or Decimal("0")) for row in payments}
    return [{"key": kind, "label": label, "forecast": money_label(totals.get(kind, Decimal("0"))), "moved": money_label(moved.get(kind, Decimal("0"))), "balance": money_label(totals.get(kind, Decimal("0")) - moved.get(kind, Decimal("0")))} for kind, label in FinanceEntry.Kind.choices]


def present_list(request, module, queryset, page_obj, *, editable, actions, money_label, user_label, summary_queryset=None):
    if module not in MODULE_PAGES:
        return {}
    kicker, headline, help_text, create_label, placeholder, status_label, empty_title, empty_help = MODULE_PAGES[module]
    today = timezone.localdate()
    rows = []
    for obj in page_obj:
        matter = obj if module == "matters" else getattr(obj, "matter", None)
        row = {"record": obj, "matter": matter, "url": reverse("legal:detail", args=[matter.pk]) if matter else "", "edit_url": reverse("legal:edit", args=[module, obj.pk]) if editable else "", "owner": user_label(getattr(obj, "owner", None))}
        if module == "documents":
            row["version"] = obj.list_versions[0] if obj.list_versions else None
            obj._list_latest_version = row["version"]
            row["version_count"] = len(obj.list_versions)
        if module == "finance":
            paid = sum((p.amount if p.reversal_of_id is None else -p.amount for p in obj.list_payments), Decimal("0"))
            obj._list_balance = obj.amount - paid
            reversed_ids = {p.reversal_of_id for p in obj.list_payments if p.reversal_of_id}
            obj._list_reversible = any(p.reversal_of_id is None and p.pk not in reversed_ids for p in obj.list_payments)
            row.update(amount=money_label(obj.amount), paid=money_label(paid), balance=money_label(obj._list_balance), settled=obj._list_balance == 0)
        if module == "deadlines":
            days = (obj.due_date - today).days
            row["timing"] = "Cumprido" if obj.status == "fulfilled" else "Vencido" if days < 0 else "Hoje" if days == 0 else "Amanhã" if days == 1 else f"Em {days} dias"
            row["urgency"] = "done" if obj.status == "fulfilled" else "overdue" if days < 0 else "soon" if days <= 7 else "later"
        if module == "crm":
            row["amount"] = money_label(obj.amount)
            row["next_action"] = obj.next_action.strip()
        row["actions"] = actions(request, module, obj)
        rows.append(row)
    context = {"module_template": f"legal/modules/{module}.html", "module_kicker": kicker, "module_headline": headline, "module_help": help_text, "create_label": create_label, "search_placeholder": placeholder, "status_label": status_label, "empty_title": empty_title, "empty_help": empty_help, "module_rows": rows, "module_stats": stats_for(queryset, module)}
    if module == "finance":
        context["finance_totals"] = finance_totals(queryset, money_label)
    if module == "crm":
        if summary_queryset is not None:
            context["module_stats"] = stats_for(summary_queryset, module)
        grouped = {row["stage"]: row for row in queryset.order_by().values("stage").annotate(total=Count("pk"), amount=Sum("amount"))}
        context["pipeline"] = [{"key": key, "label": label, "rows": [row for row in rows if row["record"].stage == key], "total": grouped.get(key, {}).get("total", 0), "amount": money_label(grouped.get(key, {}).get("amount", Decimal("0")))} for key, label in Opportunity.Stage.choices]
        for stat, focus in zip(context["module_stats"], ["open", "no_action", "won"]):
            params = request.GET.copy()
            for name in ["page", "status"]:
                params.pop(name, None)
            params["focus"] = focus
            stat["url"] = reverse("legal:list", args=["crm"]) + "?" + params.urlencode()
    return context
