from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    CancelarForm, ClienteForm, ConfirmarForm, EntradaForm, LoginForm, PagoForm, PedidoClienteForm, PedidoMostradorForm,
    PrendaForm, SeguimientoForm,
)
from .models import Apartado, ApartadoItem, Cliente, EntradaMercancia, Notificacion, Pago, Prenda
from .permisos import es_personal, gerente_requerido, personal_requerido
from .services import ReglaDeNegocioError


# ===========================================================================
# Públicas (cliente): RF-01 consultar disponibilidad y RF-05 seguimiento
# ===========================================================================
def _grupos(prendas):
    """Agrupa las prendas por modelo y color: una tarjeta por modelo con sus tallas ordenadas."""
    grupos = {}
    for p in prendas:
        grupos.setdefault((p.categoria, p.modelo, p.color), []).append(p)
    orden_cat = [c for c, _ in Prenda.CATEGORIAS]
    salida = []
    for (cat, modelo, color), lista in grupos.items():
        lista.sort(key=lambda x: x.orden_talla)
        salida.append({
            "categoria": dict(Prenda.CATEGORIAS)[cat], "modelo": modelo, "color": color, "prendas": lista,
            "desde": min(x.precio for x in lista), "hay_stock": any(x.stock > 0 for x in lista), "_o": (orden_cat.index(cat), modelo, color),
        })
    salida.sort(key=lambda g: g["_o"])
    return salida


def catalogo(request):
    """RF-01: catálogo por categoría → modelo → color → talla, con cantidades para pedir (también para el cliente)."""
    base = Prenda.objects.filter(activa=True)
    categoria = request.GET.get("categoria", "")
    modelo = request.GET.get("modelo", "").strip()
    color = request.GET.get("color", "").strip()
    talla = request.GET.get("talla", "").strip().upper()
    solo_disp = request.GET.get("disponibles") == "1"

    prendas = base
    if categoria:
        prendas = prendas.filter(categoria=categoria)
    if modelo:
        prendas = prendas.filter(modelo=modelo)
    if color:
        prendas = prendas.filter(color=color)
    if talla:
        prendas = prendas.filter(talla=talla)
    if solo_disp:
        prendas = prendas.filter(stock__gt=0)

    # Opciones de los filtros (cada uno depende del anterior) y mapa para el JavaScript
    en_cat = base.filter(categoria=categoria) if categoria else base
    en_modelo = en_cat.filter(modelo=modelo) if modelo else en_cat
    en_color = en_modelo.filter(color=color) if color else en_modelo
    modelos_lista = sorted(set(en_cat.values_list("modelo", flat=True)))
    colores = sorted(set(en_modelo.values_list("color", flat=True)))
    presentes = set(en_color.values_list("talla", flat=True))
    tallas = [(t, n) for t, n in Prenda.TALLAS if t in presentes]
    mapa = {}
    for c, m, col, t in base.values_list("categoria", "modelo", "color", "talla"):
        mapa.setdefault(c, {}).setdefault(m, {}).setdefault(col, set()).add(t)
    mapa = {c: {m: {col: [t for t in Prenda.ORDEN_TALLAS if t in ts] for col, ts in cols.items()} for m, cols in ms.items()}
            for c, ms in mapa.items()}

    return render(request, "tienda/catalogo.html", {
        "grupos": _grupos(prendas), "categoria": categoria, "modelo": modelo, "color": color, "talla": talla, "solo_disp": solo_disp,
        "categorias": Prenda.CATEGORIAS, "modelos": modelos_lista, "colores": colores, "tallas": tallas, "mapa": mapa,
        "en_carrito": sum(_carrito(request).values()),
    })


# ===========================================================================
# Carrito y pedido (lo usan el cliente en línea y el vendedor en mostrador)
# ===========================================================================
MAX_PIEZAS_POR_PARTIDA = 100000


def _carrito(request):
    return request.session.get("carrito", {})


def _entero(valor):
    try:
        return max(0, min(int(str(valor).strip() or 0), MAX_PIEZAS_POR_PARTIDA))
    except ValueError:
        return 0


def _volver(request, defecto="tienda:catalogo"):
    destino = request.POST.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect(defecto)


@require_POST
def carrito_agregar(request):
    carrito = dict(_carrito(request))
    agregadas = 0
    for clave, valor in request.POST.items():
        if clave.startswith("cant_"):
            n = _entero(valor)
            if n and clave[5:].isdigit():
                carrito[clave[5:]] = min(carrito.get(clave[5:], 0) + n, MAX_PIEZAS_POR_PARTIDA)
                agregadas += n
    request.session["carrito"] = carrito
    if agregadas:
        messages.success(request, f"Se agregaron {agregadas} pieza(s) a tu pedido. Puedes seguir agregando o ir a «Mi pedido».")
    else:
        messages.error(request, "Escribe la cantidad de piezas que quieres en al menos una talla.")
    return _volver(request)


def _lineas_carrito(request):
    carrito = _carrito(request)
    prendas = {str(p.pk): p for p in Prenda.objects.filter(pk__in=[k for k in carrito if k.isdigit()], activa=True)}
    lineas = []
    for clave, cant in carrito.items():
        p = prendas.get(clave)
        if p:
            lineas.append({
                "prenda": p, "cantidad": cant, "subtotal": p.precio * cant,
                "de_inventario": min(cant, p.stock), "por_encargo": max(0, cant - p.stock),
            })
    lineas.sort(key=lambda l: (l["prenda"].modelo, l["prenda"].color, l["prenda"].orden_talla))
    return lineas


def carrito(request):
    """«Mi pedido»: cantidades por talla y datos para enviar el pedido."""
    personal = es_personal(request.user)
    Form = PedidoMostradorForm if personal else PedidoClienteForm
    if request.method == "POST":
        # 1) actualizar cantidades (0 = quitar)
        nuevo = {}
        for clave, valor in request.POST.items():
            if clave.startswith("cant_") and clave[5:].isdigit():
                n = _entero(valor)
                if n:
                    nuevo[clave[5:]] = n
        request.session["carrito"] = nuevo
        accion = request.POST.get("accion")
        if accion == "vaciar":
            request.session["carrito"] = {}
            messages.info(request, "Tu pedido quedó vacío.")
            return redirect("tienda:carrito")
        if accion == "actualizar":
            messages.success(request, "Cantidades actualizadas.")
            return redirect("tienda:carrito")
        # 2) enviar el pedido
        form = Form(request.POST)
        lineas = _lineas_carrito(request)
        if not lineas:
            messages.error(request, "Tu pedido está vacío. Elige prendas en el catálogo.")
            return redirect("tienda:catalogo")
        if form.is_valid():
            d = form.cleaned_data
            try:
                cliente = services.get_or_create_cliente(d["nombre"], d["telefono"], d["email"])
                ap = services.crear_pedido(
                    cliente=cliente, lineas=[(l["prenda"], l["cantidad"]) for l in lineas], notas=d["notas"],
                    vendedor=request.user if personal else None,
                    anticipo=d.get("anticipo"), metodo=d.get("metodo", "EFECTIVO"),
                )
            except ReglaDeNegocioError as err:
                form.add_error(None, str(err))
            else:
                request.session["carrito"] = {}
                if personal:
                    messages.success(request, f"Pedido {ap.folio} registrado. Se generó el aviso de confirmación para el cliente.")
                    return redirect("tienda:apartado_detalle", pk=ap.pk)
                request.session["ultimo_pedido"] = {"folio": ap.folio, "telefono": cliente.telefono}
                return redirect("tienda:pedido_listo")
    else:
        lineas = _lineas_carrito(request)
        form = Form()
    total = sum((l["subtotal"] for l in lineas), Decimal("0"))
    minimo = (total * Decimal(settings.ANTICIPO_PORCENTAJE) / Decimal(100)).quantize(Decimal("0.01"))
    if personal and not form.is_bound:
        form.initial["anticipo"] = minimo
    return render(request, "tienda/carrito.html", {
        "lineas": lineas, "form": form, "total": total, "minimo": minimo, "personal": personal,
        "piezas": sum(l["cantidad"] for l in lineas), "encargo": sum(l["por_encargo"] for l in lineas),
    })


def pedido_listo(request):
    datos = request.session.get("ultimo_pedido")
    if not datos:
        return redirect("tienda:catalogo")
    ap = services.buscar_apartado_publico(datos["folio"], datos["telefono"])
    return render(request, "tienda/pedido_listo.html", {"ap": ap, "telefono": datos["telefono"]})


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
        "n_solicitudes": Apartado.objects.filter(estado=Apartado.SOLICITADO).count(),
        "saldo_pendiente": sum((a.saldo for a in activos), 0),
        "stock_bajo": Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).order_by("stock")[:6],
        "ultimos": Apartado.objects.select_related("cliente").annotate(n_piezas=Sum("items__cantidad"))[:6],
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
    """Bandeja de pedidos: aquí se ven todos los pedidos registrados (mostrador y en línea)."""
    base = Apartado.objects.select_related("cliente").annotate(n_piezas=Sum("items__cantidad"))
    qs = base
    estado = request.GET.get("estado", "")
    origen = request.GET.get("origen", "")
    q = request.GET.get("q", "").strip()
    if estado:
        qs = qs.filter(estado=estado)
    if origen:
        qs = qs.filter(origen=origen)
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(cliente__nombre__icontains=q) | Q(cliente__telefono__icontains=q))
    conteo = {r["estado"]: r["n"] for r in Apartado.objects.values("estado").annotate(n=Count("id"))}
    pestanas = [("", "Todos", sum(conteo.values()))] + [(v, n, conteo.get(v, 0)) for v, n in Apartado.ESTADOS]
    return render(request, "tienda/apartados.html", {
        "apartados": qs, "estado": estado, "origen": origen, "q": q,
        "origenes": Apartado.ORIGENES, "pestanas": pestanas, "n_solicitudes": conteo.get(Apartado.SOLICITADO, 0),
    })


@personal_requerido
def apartado_nuevo(request):
    """El vendedor arma el pedido en el catálogo (mismo flujo que el cliente) y lo confirma con el anticipo."""
    messages.info(request, "Elige las prendas y tallas en el catálogo, luego entra a «Mi pedido» para capturar los datos del cliente y el anticipo.")
    return redirect("tienda:catalogo")


@personal_requerido
def apartado_detalle(request, pk):
    ap = get_object_or_404(Apartado.objects.select_related("cliente", "vendedor"), pk=pk)
    items = ap.items.select_related("prenda")
    return render(request, "tienda/apartado_detalle.html", {
        "ap": ap, "items": items, "pagos": ap.pagos.select_related("registrado_por"), "avisos": ap.notificaciones.all(),
        "pago_form": PagoForm(initial={"monto": ap.saldo}), "cancelar_form": CancelarForm(),
        "confirmar_form": ConfirmarForm(initial={"anticipo": ap.anticipo_requerido}),
    })


@personal_requerido
@require_POST
def apartado_confirmar(request, pk):
    ap = get_object_or_404(Apartado, pk=pk)
    form = ConfirmarForm(request.POST)
    if form.is_valid():
        try:
            ap = services.confirmar_solicitud(apartado=ap, usuario=request.user, **form.cleaned_data)
            extra = f" {ap.por_encargo} pieza(s) quedan por encargo al proveedor." if ap.por_encargo else ""
            messages.success(request, f"Pedido {ap.folio} confirmado con su anticipo. Saldo pendiente: ${ap.saldo}.{extra}")
        except ReglaDeNegocioError as err:
            messages.error(request, str(err))
    else:
        messages.error(request, "Revisa el monto del anticipo.")
    return redirect("tienda:apartado_detalle", pk=pk)


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
            messages.success(request, f"Pedido {ap.folio} cancelado. Las piezas apartadas regresaron al inventario.")
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
        ApartadoItem.objects.exclude(apartado__estado__in=[Apartado.CANCELADO, Apartado.VENCIDO, Apartado.SOLICITADO])
        .values("prenda__modelo", "prenda__talla").annotate(piezas=Sum("cantidad")).order_by("-piezas")[:5]
    )
    activos = Apartado.objects.filter(estado=Apartado.ACTIVO).select_related("cliente").order_by("vence")
    return render(request, "tienda/reportes.html", {
        "por_estado": por_estado, "ingresos": ingresos, "top": top, "activos": activos,
        "stock_bajo": Prenda.objects.filter(activa=True, stock__lte=F("stock_minimo")).order_by("stock"),
        "valor_inventario": sum((p.precio * p.stock for p in Prenda.objects.filter(activa=True)), 0),
    })
