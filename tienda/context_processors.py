from django.db.models import F

from .models import Apartado, Notificacion, Prenda
from .permisos import es_gerente, es_personal


def contadores(request):
    """Datos globales para la barra de navegación."""
    ctx = {"es_gerente": False, "es_personal": False}
    ctx["nav_carrito"] = sum(request.session.get("carrito", {}).values()) if hasattr(request, "session") else 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["es_gerente"] = es_gerente(user)
        ctx["es_personal"] = es_personal(user)
        if ctx["es_personal"]:
            ctx["nav_solicitudes"] = Apartado.objects.filter(estado=Apartado.SOLICITADO).count()
            ctx["nav_pendientes"] = Notificacion.objects.filter(atendida=False).count()
            ctx["nav_stock_bajo"] = Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).count()
    return ctx
