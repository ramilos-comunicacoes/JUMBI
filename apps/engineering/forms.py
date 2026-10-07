from django import forms

from .models import Employee, FinanceEntry, Project, ProjectEvidence, ProjectTask, Purchase, Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ("name", "document", "email", "phone")
        labels = {"name": "Nome / razão social", "document": "CNPJ / CPF", "email": "E-mail", "phone": "Telefone"}


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "client_name", "status", "budget", "start_date", "end_date")
        labels = {
            "name": "Nome da obra",
            "client_name": "Cliente",
            "status": "Etapa atual",
            "budget": "Orçamento total",
            "start_date": "Data de início",
            "end_date": "Previsão de conclusão",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class ProjectTaskForm(forms.ModelForm):
    class Meta:
        model = ProjectTask
        fields = ("project", "title", "description", "priority", "due_date", "assignee")
        labels = {
            "project": "Obra",
            "title": "Título da tarefa",
            "description": "Descrição",
            "priority": "Prioridade",
            "due_date": "Prazo",
            "assignee": "Responsável",
        }
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["project"].queryset = Project.objects.filter(organization=organization)
            self.fields["assignee"].queryset = self.fields["assignee"].queryset.filter(
                memberships__organization=organization,
                memberships__is_active=True,
            ).distinct()


class ProjectEvidenceForm(forms.ModelForm):
    class Meta:
        model = ProjectEvidence
        fields = ("project", "task", "title", "notes", "file")
        labels = {
            "project": "Obra",
            "task": "Tarefa relacionada",
            "title": "Título da evidência",
            "notes": "Observações",
            "file": "Arquivo",
        }
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["project"].queryset = Project.objects.filter(organization=organization)
            self.fields["task"].queryset = ProjectTask.objects.filter(organization=organization)


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ("name", "role", "email", "phone", "project", "is_active")
        labels = {
            "name": "Nome completo",
            "role": "Função",
            "email": "E-mail",
            "phone": "Telefone",
            "project": "Obra principal",
            "is_active": "Profissional ativo",
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["project"].queryset = Project.objects.filter(organization=organization)


class FinanceEntryForm(forms.ModelForm):
    class Meta:
        model = FinanceEntry
        fields = ("project", "kind", "description", "amount", "due_date", "status")
        labels = {
            "project": "Obra",
            "kind": "Tipo",
            "description": "Descrição",
            "amount": "Valor",
            "due_date": "Vencimento",
            "status": "Situação",
        }
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["project"].queryset = Project.objects.filter(organization=organization)


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ("project", "supplier", "item", "quantity", "total_amount", "status", "requested_at")
        labels = {
            "project": "Obra",
            "supplier": "Fornecedor",
            "item": "Item / material",
            "quantity": "Quantidade",
            "total_amount": "Valor total",
            "status": "Etapa da compra",
            "requested_at": "Data da solicitação",
        }
        widgets = {"requested_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["project"].queryset = Project.objects.filter(organization=organization)
            self.fields["supplier"].queryset = Supplier.objects.filter(organization=organization)
