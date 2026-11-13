from django.db.models import F

from .models import Notificacion, Prenda
from .permisos import es_gerente, es_personal


def contadores(request):
    """Datos globales para la barra de navegación."""
    ctx = {"es_gerente": False, "es_personal": False}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["es_gerente"] = es_gerente(user)
        ctx["es_personal"] = es_personal(user)
        if ctx["es_personal"]:
            ctx["nav_pendientes"] = Notificacion.objects.filter(atendida=False).count()
            ctx["nav_stock_bajo"] = Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).count()
    return ctx
