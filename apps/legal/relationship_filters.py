"""Validated filters for the relationship pipeline; no financial side effects."""
from django import forms

from apps.core.models import Membership
from apps.core.niches import practice_area_choices
from .models import Opportunity


class RelationshipFilterForm(forms.Form):
    q = forms.CharField(label="Buscar atendimento ou pessoa", max_length=120, required=False)
    status = forms.ChoiceField(label="Etapa", required=False, choices=[("", "Todas as etapas"), *Opportunity.Stage.choices])
    owner = forms.ChoiceField(label="Responsável", required=False)
    focus = forms.ChoiceField(label="Atenção", required=False, choices=[("", "Todos os atendimentos"), ("open", "Em negociação"), ("no_action", "Sem próxima ação"), ("won", "Ganhos")])
    niche = forms.ChoiceField(label="Nicho das pastas acessíveis", required=False)
    sort = forms.ChoiceField(label="Ordenar", required=False, choices=[("", "Mais recentes"), ("oldest", "Mais antigos"), ("amount", "Maior estimativa"), ("name", "Nome da oportunidade")])
    view = forms.ChoiceField(label="Visualização", required=False, choices=[("", "Quadro"), ("list", "Lista")])

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        members = Membership.objects.filter(organization=request.organization, is_active=True, user__is_active=True, role__in=["owner", "manager", "operator", "viewer"]).select_related("user").order_by("user__email")
        self.fields["owner"].choices = [("", "Toda a equipe"), *((str(m.user_id), m.user.get_full_name() or m.user.email) for m in members)]
        self.fields["niche"].choices = [("", "Todos os nichos"), *practice_area_choices(request.organization)]
