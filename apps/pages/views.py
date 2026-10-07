from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import DemoRequestForm


def home(request):
    return render(request, "pages/home.html")


def demo_request(request):
    if request.method == "POST":
        form = DemoRequestForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Recebemos seu contato. Em breve, nossa equipe falará com você.")
            return redirect("pages:demo-request")
    else:
        form = DemoRequestForm()
    return render(request, "pages/demo_request.html", {"form": form})
