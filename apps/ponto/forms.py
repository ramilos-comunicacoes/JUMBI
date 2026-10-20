import datetime
from django import forms
from .models import (
    WorkSchedule,
    EmployeeSchedule,
    HolidayOrDayOff,
    TimeRecord,
    TimeAdjustmentRequest,
)


class ManualTimeRecordForm(forms.ModelForm):
    """Formulário para inclusão ou retificação manual de batida de ponto pelo Gestor."""
    punch_time = forms.TimeField(
        label="Horário (HH:MM)",
        widget=forms.TimeInput(attrs={"type": "time", "class": "input"}),
        required=True,
    )

    class Meta:
        model = TimeRecord
        fields = [
            "membership",
            "recorded_date",
            "record_type",
            "adjustment_reason",
        ]
        widgets = {
            "membership": forms.Select(attrs={"class": "input"}),
            "recorded_date": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "record_type": forms.Select(attrs={"class": "input"}),
            "adjustment_reason": forms.Textarea(
                attrs={
                    "class": "input",
                    "rows": 3,
                    "placeholder": "Descreva o motivo legal da retificação ou inclusão manual (ex: 'Esquecimento de batida confirmado pelo gestor').",
                    "required": "required",
                }
            ),
        }
        labels = {
            "membership": "Colaborador",
            "recorded_date": "Data da jornada",
            "record_type": "Tipo de batida",
            "adjustment_reason": "Justificativa obrigatória da alteração",
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["membership"].queryset = organization.memberships.filter(
                is_active=True
            ).exclude(role="client").select_related("user")
        if self.instance and self.instance.pk and self.instance.timestamp:
            self.fields["punch_time"].initial = self.instance.timestamp.strftime("%H:%M")

    def clean(self):
        cleaned_data = super().clean()
        p_time = cleaned_data.get("punch_time")
        if p_time:
            cleaned_data["time_str"] = p_time
        return cleaned_data


class WorkScheduleForm(forms.ModelForm):
    """Cadastro e edição de jornada de trabalho e horários."""
    class Meta:
        model = WorkSchedule
        fields = [
            "name",
            "daily_expected_hours",
            "tolerance_minutes",
            "is_default",
            "is_active",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "placeholder": "Ex: Jornada 40h (08:00 às 17:00)"}),
            "daily_expected_hours": forms.NumberInput(attrs={"class": "input", "step": "0.25", "min": "1", "max": "24"}),
            "tolerance_minutes": forms.NumberInput(attrs={"class": "input", "min": "0", "max": "60"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 2}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        }


class HolidayForm(forms.ModelForm):
    """Cadastro de feriado ou folga da empresa."""
    class Meta:
        model = HolidayOrDayOff
        fields = ["name", "date", "kind", "repeats_yearly"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input", "placeholder": "Nome do feriado ou folga"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "kind": forms.Select(attrs={"class": "input"}),
            "repeats_yearly": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
        }


class TimeAdjustmentRequestForm(forms.ModelForm):
    """Envio de atestado médico ou solicitação de ajuste pelo colaborador."""
    class Meta:
        model = TimeAdjustmentRequest
        fields = [
            "date",
            "request_type",
            "suggested_record_type",
            "suggested_time",
            "reason",
            "attachment",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "request_type": forms.Select(attrs={"class": "input"}),
            "suggested_record_type": forms.Select(attrs={"class": "input"}),
            "suggested_time": forms.TimeInput(attrs={"type": "time", "class": "input"}),
            "reason": forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "Explique o motivo do ajuste ou atestado..."}),
            "attachment": forms.FileInput(attrs={"class": "input", "accept": "image/*,application/pdf"}),
        }
