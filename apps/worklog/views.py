from uuid import uuid4

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.legal.models import Task
from apps.legal.services import can_write
from apps.legal.views import organization_required, scoped_queryset
from .services import comment_on_task, visible_comments


class CommentForm(forms.Form):
    body = forms.CharField(label="Comentário para a equipe", max_length=3000, strip=True, widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Registre uma atualização, uma dúvida ou uma orientação…"}))
    operation_key = forms.UUIDField(widget=forms.HiddenInput)


@organization_required
@require_http_methods(["GET", "POST"])
def task_detail(request, pk):
    task = get_object_or_404(scoped_queryset(request.user, request.organization, Task).select_related("matter", "owner"), pk=pk)
    editable = can_write(request.user, request.organization)
    form = CommentForm(request.POST if request.method == "POST" else None, initial={"operation_key": uuid4()})
    if request.method == "POST":
        if not editable:
            raise PermissionDenied("Seu acesso permite apenas a leitura desta tarefa.")
        if form.is_valid():
            try:
                comment_on_task(actor=request.user, task=task, **form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Comentário registrado no histórico da tarefa.")
                return redirect("worklog:task", pk=task.pk)
    comments = Paginator(visible_comments(request.user, request.organization).filter(task=task).select_related("created_by"), 20).get_page(request.GET.get("page"))
    return render(request, "worklog/task.html", {"task": task, "form": form, "comments": comments, "can_comment": editable, "page_title": "Detalhes da tarefa", "active_nav": "tasks"}, status=400 if request.method == "POST" else 200)
