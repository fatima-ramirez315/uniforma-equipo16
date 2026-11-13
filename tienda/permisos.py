from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect

from .models import Perfil


def rol_de(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return Perfil.GERENTE
    perfil = getattr(user, "perfil", None)
    return perfil.rol if perfil else None


def es_gerente(user):
    return rol_de(user) == Perfil.GERENTE


def es_personal(user):
    return rol_de(user) in (Perfil.VENDEDOR, Perfil.GERENTE)


def personal_requerido(view):
    """Vendedor o Gerente (RF-12)."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not es_personal(request.user):
            messages.error(request, "Tu usuario no tiene un rol asignado. Pide al gerente que lo configure.")
            return redirect("tienda:catalogo")
        return view(request, *args, **kwargs)

    return _wrapped


def gerente_requerido(view):
    """Solo Gerente (RF-12)."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not es_gerente(request.user):
            messages.error(request, "Esta sección es exclusiva del gerente.")
            return redirect("tienda:panel")
        return view(request, *args, **kwargs)

    return _wrapped
