from django import forms

from apps.core.models import Membership
from apps.core.niches import practice_area_choices
from .models import Task


class TaskBoardFilterForm(forms.Form):
    q = forms.CharField(label="Buscar", max_length=120, required=False)
    owner = forms.ChoiceField(label="Responsável", required=False)
    priority = forms.ChoiceField(label="Prioridade", required=False, choices=[("", "Todas"), *Task.Priority.choices])
    niche = forms.ChoiceField(label="Nicho", required=False)
    period = forms.ChoiceField(label="Recorte de trabalho", required=False, choices=[("", "Todas as entregas"), ("pending", "Em aberto"), ("today", "Para hoje · em aberto"), ("week", "Próximos 7 dias · em aberto"), ("overdue", "Atrasadas"), ("completed_month", "Concluídas neste mês")])

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        members = Membership.objects.filter(organization=request.organization, is_active=True, user__is_active=True, role__in=["owner", "manager", "operator", "viewer"]).select_related("user").order_by("user__email")
        self.fields["owner"].choices = [("", "Toda a equipe"), *((str(m.user_id), m.user.get_full_name() or m.user.email) for m in members)]
        self.fields["niche"].choices = [("", "Todos os nichos"), *practice_area_choices(request.organization)]
