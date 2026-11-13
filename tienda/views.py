from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    ApartadoForm, CancelarForm, ClienteForm, EntradaForm, LoginForm, PagoForm, PrendaForm, SeguimientoForm,
)
from .models import Apartado, Cliente, EntradaMercancia, Notificacion, Pago, Prenda
from .permisos import gerente_requerido, personal_requerido
from .services import ReglaDeNegocioError


# ===========================================================================
# Públicas (cliente): RF-01 consultar disponibilidad y RF-05 seguimiento
# ===========================================================================
def catalogo(request):
    prendas = Prenda.objects.filter(activa=True)
    q = request.GET.get("q", "").strip()
    categoria = request.GET.get("categoria", "")
    talla = request.GET.get("talla", "").strip().upper()
    solo_disp = request.GET.get("disponibles") == "1"

    if q:
        prendas = prendas.filter(Q(modelo__icontains=q) | Q(color__icontains=q) | Q(codigo__icontains=q))
    if categoria:
        prendas = prendas.filter(categoria=categoria)
    if talla:
        prendas = prendas.filter(talla=talla)
    if solo_disp:
        prendas = prendas.filter(stock__gt=0)

    tallas = Prenda.objects.filter(activa=True).values_list("talla", flat=True).distinct().order_by("talla")
    return render(request, "tienda/catalogo.html", {
        "prendas": prendas, "q": q, "categoria": categoria, "talla": talla, "solo_disp": solo_disp,
        "categorias": Prenda.CATEGORIAS, "tallas": tallas,
    })


def seguimiento(request):
    apartado = None
    buscado = False
    form = SeguimientoForm(request.GET or None)
    if request.GET and form.is_valid():
        buscado = True
        apartado = services.buscar_apartado_publico(form.cleaned_data["folio"], form.cleaned_data["telefono"])
    ctx = {"form": form, "apartado": apartado, "buscado": buscado}
    if apartado:
        ctx["pagos"] = apartado.pagos.all()
        ctx["avisos"] = apartado.notificaciones.all()
    return render(request, "tienda/seguimiento.html", ctx)


# ===========================================================================
# Autenticación (RF-12)
# ===========================================================================
class IngresarView(LoginView):
    template_name = "tienda/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


# ===========================================================================
# Panel interno
# ===========================================================================
@personal_requerido
def panel(request):
    ahora = timezone.now()
    activos = Apartado.objects.filter(estado=Apartado.ACTIVO)
    ctx = {
        "n_activos": activos.count(),
        "n_listos": Apartado.objects.filter(estado=Apartado.PAGADO).count(),
        "n_por_vencer": activos.filter(vence__lte=ahora + timedelta(days=settings.AVISO_VENCIMIENTO_DIAS)).count(),
        "n_especiales": Apartado.objects.filter(tipo=Apartado.ESPECIAL, estado__in=[Apartado.ACTIVO, Apartado.PAGADO]).count(),
        "saldo_pendiente": sum((a.saldo for a in activos), 0),
        "stock_bajo": Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).order_by("stock")[:6],
        "ultimos": Apartado.objects.select_related("cliente", "prenda")[:6],
        "avisos": Notificacion.objects.filter(atendida=False).select_related("cliente", "apartado")[:6],
    }
    return render(request, "tienda/panel.html", ctx)


# ===========================================================================
# Inventario (RF-10, RF-14, RF-16)
# ===========================================================================
@personal_requerido
def prendas(request):
    qs = Prenda.objects.all()
    q = request.GET.get("q", "").strip()
    solo_bajo = request.GET.get("bajo") == "1"
    if q:
        qs = qs.filter(Q(modelo__icontains=q) | Q(codigo__icontains=q) | Q(color__icontains=q))
    if solo_bajo:
        qs = qs.filter(activa=True, stock__lte=F("stock_minimo"))
    return render(request, "tienda/prendas.html", {"prendas": qs, "q": q, "solo_bajo": solo_bajo})


@gerente_requerido
def prenda_form(request, pk=None):
    prenda = get_object_or_404(Prenda, pk=pk) if pk else None
    form = PrendaForm(request.POST or None, instance=prenda)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Prenda «{obj}» guardada.")
        return redirect("tienda:prendas")
    return render(request, "tienda/form.html", {
        "form": form, "titulo": "Editar prenda" if prenda else "Nueva prenda", "volver": "tienda:prendas",
    })


@gerente_requerido
def entradas(request):
    if request.method == "POST":
        form = EntradaForm(request.POST)
        if form.is_valid():
            try:
                e = services.registrar_entrada(usuario=request.user, **form.cleaned_data)
                messages.success(request, f"Entrada registrada: +{e.cantidad} de {e.prenda}. Stock actual: {e.prenda.stock}.")
                return redirect("tienda:entradas")
            except ReglaDeNegocioError as err:
                form.add_error(None, str(err))
    else:
        form = EntradaForm(initial={"prenda": request.GET.get("prenda")})
    return render(request, "tienda/entradas.html", {
        "form": form, "entradas": EntradaMercancia.objects.select_related("prenda", "registrado_por")[:30],
    })


# ===========================================================================
# Clientes (RF-11)
# ===========================================================================
@personal_requerido
def clientes(request):
    q = request.GET.get("q", "").strip()
    qs = Cliente.objects.annotate(n_apartados=Count("apartados"))
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q))
    return render(request, "tienda/clientes.html", {"clientes": qs, "q": q})


@personal_requerido
def cliente_form(request, pk=None):
    cliente = get_object_or_404(Cliente, pk=pk) if pk else None
    form = ClienteForm(request.POST or None, instance=cliente)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Cliente «{obj.nombre}» guardado.")
        return redirect("tienda:clientes")
    return render(request, "tienda/form.html", {
        "form": form, "titulo": "Editar cliente" if cliente else "Nuevo cliente", "volver": "tienda:clientes",
    })


# ===========================================================================
# Apartados (RF-02, RF-03, RF-05, RF-06, RF-08)
# ===========================================================================
@personal_requerido
def apartados(request):
    qs = Apartado.objects.select_related("cliente", "prenda")
    estado = request.GET.get("estado", "")
    tipo = request.GET.get("tipo", "")
    q = request.GET.get("q", "").strip()
    if estado:
        qs = qs.filter(estado=estado)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(cliente__nombre__icontains=q) | Q(cliente__telefono__icontains=q))
    return render(request, "tienda/apartados.html", {
        "apartados": qs, "estado": estado, "tipo": tipo, "q": q,
        "estados": Apartado.ESTADOS, "tipos": Apartado.TIPOS,
    })


@personal_requerido
def apartado_nuevo(request):
    initial = {}
    if request.GET.get("prenda"):
        initial["prenda"] = request.GET["prenda"]
    if request.GET.get("tipo") in dict(Apartado.TIPOS):
        initial["tipo"] = request.GET["tipo"]
    form = ApartadoForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            cliente = services.get_or_create_cliente(d["nombre"], d["telefono"], d["email"])
            ap = services.crear_apartado(
                cliente=cliente, prenda=d["prenda"], cantidad=d["cantidad"], anticipo=d["anticipo"],
                metodo=d["metodo"], vendedor=request.user, tipo=d["tipo"], notas=d["notas"],
            )
        except ReglaDeNegocioError as err:
            form.add_error(None, str(err))
        else:
            messages.success(request, f"Apartado {ap.folio} registrado. Se generó el aviso de confirmación para el cliente.")
            return redirect("tienda:apartado_detalle", pk=ap.pk)
    return render(request, "tienda/apartado_nuevo.html", {
        "form": form, "precios": {p.pk: str(p.precio) for p in Prenda.objects.filter(activa=True)},
        "stocks": {p.pk: p.stock for p in Prenda.objects.filter(activa=True)},
    })


@personal_requerido
def apartado_detalle(request, pk):
    ap = get_object_or_404(Apartado.objects.select_related("cliente", "prenda", "vendedor"), pk=pk)
    return render(request, "tienda/apartado_detalle.html", {
        "ap": ap, "pagos": ap.pagos.select_related("registrado_por"), "avisos": ap.notificaciones.all(),
        "pago_form": PagoForm(initial={"monto": ap.saldo}), "cancelar_form": CancelarForm(),
    })


@personal_requerido
@require_POST
def apartado_pago(request, pk):
    ap = get_object_or_404(Apartado, pk=pk)
    form = PagoForm(request.POST)
    if form.is_valid():
        try:
            ap = services.registrar_pago(apartado=ap, usuario=request.user, **form.cleaned_data)
            messages.success(request, f"Pago registrado. Saldo pendiente: ${ap.saldo}.")
        except ReglaDeNegocioError as err:
            messages.error(request, str(err))
    else:
        messages.error(request, "Revisa el monto del pago.")
    return redirect("tienda:apartado_detalle", pk=pk)


@personal_requerido
@require_POST
def apartado_entregar(request, pk):
    ap = get_object_or_404(Apartado, pk=pk)
    try:
        services.entregar_apartado(apartado=ap, usuario=request.user)
        messages.success(request, f"Apartado {ap.folio} entregado al cliente.")
    except ReglaDeNegocioError as err:
        messages.error(request, str(err))
    return redirect("tienda:apartado_detalle", pk=pk)


@personal_requerido
@require_POST
def apartado_cancelar(request, pk):
    ap = get_object_or_404(Apartado, pk=pk)
    form = CancelarForm(request.POST)
    if form.is_valid():
        try:
            services.cancelar_apartado(apartado=ap, motivo=form.cleaned_data["motivo"], usuario=request.user)
            messages.success(request, f"Apartado {ap.folio} cancelado. La prenda regresó al inventario.")
        except ReglaDeNegocioError as err:
            messages.error(request, str(err))
    else:
        messages.error(request, "Indica el motivo de la cancelación.")
    return redirect("tienda:apartado_detalle", pk=pk)


# ===========================================================================
# Notificaciones (RF-04)
# ===========================================================================
@personal_requerido
def notificaciones(request):
    ver = request.GET.get("ver", "pendientes")
    qs = Notificacion.objects.select_related("cliente", "apartado")
    if ver != "todas":
        qs = qs.filter(atendida=False)
    return render(request, "tienda/notificaciones.html", {"avisos": qs[:100], "ver": ver})


@personal_requerido
@require_POST
def notificacion_atendida(request, pk):
    Notificacion.objects.filter(pk=pk).update(atendida=True)
    return redirect(request.POST.get("next") or "tienda:notificaciones")


# ===========================================================================
# Gerente: vencimientos (RF-13) y reportes (RF-15)
# ===========================================================================
@gerente_requerido
@require_POST
def procesar_vencimientos(request):
    vencidos, avisados = services.procesar_vencimientos()
    messages.success(request, f"Revisión terminada: {vencidos} apartado(s) vencido(s), {avisados} aviso(s) de próximo vencimiento.")
    return redirect(request.POST.get("next") or "tienda:panel")


@gerente_requerido
def reportes(request):
    por_estado = Apartado.objects.values("estado").annotate(n=Count("id"), total=Sum("total")).order_by("estado")
    nombres = dict(Apartado.ESTADOS)
    por_estado = [{"estado": nombres[r["estado"]], "n": r["n"], "total": r["total"] or 0} for r in por_estado]
    ingresos = Pago.objects.aggregate(s=Sum("monto"))["s"] or 0
    top = (
        Apartado.objects.exclude(estado__in=[Apartado.CANCELADO, Apartado.VENCIDO])
        .values("prenda__modelo", "prenda__talla").annotate(piezas=Sum("cantidad")).order_by("-piezas")[:5]
    )
    activos = Apartado.objects.filter(estado=Apartado.ACTIVO).select_related("cliente", "prenda").order_by("vence")
    return render(request, "tienda/reportes.html", {
        "por_estado": por_estado, "ingresos": ingresos, "top": top, "activos": activos,
        "stock_bajo": Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).order_by("stock"),
        "valor_inventario": sum((p.precio * p.stock for p in Prenda.objects.filter(activa=True)), 0),
    })
