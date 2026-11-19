"""
Reglas de negocio de Uniforma. Toda la lógica que modifica inventario, pagos y
estados vive aquí, dentro de transacciones, para que las vistas sean delgadas
y las pruebas sencillas.

Un pedido (Apartado) tiene varias partidas (ApartadoItem): una prenda en una
talla con su cantidad. Al confirmarse con el anticipo, cada partida aparta del
inventario lo que haya; lo que falte queda "por encargo" al proveedor.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Apartado, ApartadoItem, Cliente, EntradaMercancia, Notificacion, Pago, Prenda


class ReglaDeNegocioError(Exception):
    """Se lanza cuando una operación viola una regla de negocio (mensaje apto para el usuario)."""


def _aviso(apartado, tipo, mensaje):
    return Notificacion.objects.create(
        apartado=apartado, cliente=apartado.cliente, tipo=tipo, mensaje=mensaje[:300]
    )


def _dinero(valor):
    return Decimal(valor).quantize(Decimal("0.01"))


def _minimo(total):
    return _dinero(total * Decimal(settings.ANTICIPO_PORCENTAJE) / Decimal(100))


def normalizar_lineas(lineas):
    """Junta partidas repetidas y descarta cantidades en cero. ``lineas``: iterable de (prenda, cantidad)."""
    acumulado = {}
    for prenda, cantidad in lineas:
        cantidad = int(cantidad or 0)
        if cantidad < 0:
            raise ReglaDeNegocioError("Las cantidades no pueden ser negativas.")
        if cantidad:
            acumulado[prenda.pk] = acumulado.get(prenda.pk, 0) + cantidad
    if not acumulado:
        raise ReglaDeNegocioError("Agrega al menos una prenda al pedido.")
    prendas = {p.pk: p for p in Prenda.objects.filter(pk__in=acumulado)}
    return [(prendas[pk], c) for pk, c in acumulado.items()]


# --------------------------------------------------------------------------
# RF-02 / RF-08 / RF-09: crear pedido (solicitud del cliente o apartado en mostrador)
# --------------------------------------------------------------------------
@transaction.atomic
def crear_pedido(*, cliente, lineas, vendedor=None, anticipo=None, metodo="EFECTIVO", notas=""):
    """Crea un pedido con varias partidas.

    - Sin ``vendedor``/``anticipo``: es una *solicitud en línea* del cliente (no mueve inventario).
    - Con ``vendedor`` y ``anticipo``: apartado de mostrador, ya confirmado.
    """
    lineas = normalizar_lineas(lineas)
    for prenda, _ in lineas:
        if not prenda.activa:
            raise ReglaDeNegocioError(f"«{prenda}» está dada de baja del catálogo.")
    total = _dinero(sum(p.precio * c for p, c in lineas))

    en_mostrador = vendedor is not None
    ahora = timezone.now()
    dias = settings.VIGENCIA_APARTADO_DIAS if en_mostrador else getattr(settings, "SOLICITUD_VIGENCIA_DIAS", 7)
    ap = Apartado.objects.create(
        cliente=cliente,
        origen=Apartado.MOSTRADOR if en_mostrador else Apartado.EN_LINEA,
        estado=Apartado.SOLICITADO,
        total=total,
        vence=ahora + timedelta(days=dias),
        vendedor=vendedor,
        notas=notas,
    )
    for prenda, cantidad in lineas:
        ApartadoItem.objects.create(apartado=ap, prenda=prenda, cantidad=cantidad, precio_unitario=prenda.precio)

    if en_mostrador:
        if anticipo is None:
            raise ReglaDeNegocioError("Indica el anticipo recibido.")
        return confirmar_solicitud(apartado=ap, anticipo=anticipo, metodo=metodo, usuario=vendedor)

    _aviso(
        ap,
        "SOLICITUD",
        f"Recibimos tu pedido {ap.folio} ({ap.resumen}) por ${total}. Para apartarlo acude a mostrador "
        f"con tu anticipo mínimo de ${_minimo(total)} (50 %) antes del {timezone.localtime(ap.vence):%d/%m/%Y}.",
    )
    return ap


@transaction.atomic
def confirmar_solicitud(*, apartado, anticipo, metodo, usuario):
    """El vendedor recibe el anticipo: se aparta el inventario y el pedido queda activo."""
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    if apartado.estado != Apartado.SOLICITADO:
        raise ReglaDeNegocioError("Este pedido ya fue confirmado o cerrado.")
    anticipo = _dinero(anticipo)
    minimo = _minimo(apartado.total)
    if anticipo < minimo:
        raise ReglaDeNegocioError(
            f"El anticipo mínimo es del {settings.ANTICIPO_PORCENTAJE}% (${minimo}). Se recibió ${anticipo}."
        )
    if anticipo > apartado.total:
        raise ReglaDeNegocioError(f"El anticipo (${anticipo}) no puede ser mayor al total (${apartado.total}).")

    # Apartar del inventario lo que haya; el resto queda por encargo
    items = list(apartado.items.select_related("prenda"))
    prendas = {p.pk: p for p in Prenda.objects.select_for_update().filter(pk__in=[i.prenda_id for i in items])}
    for item in items:
        prenda = prendas[item.prenda_id]
        tomar = min(item.cantidad, prenda.stock)
        item.de_inventario = tomar
        item.save(update_fields=["de_inventario"])
        prenda.stock -= tomar  # RF-09: el inventario se actualiza solo
        prenda.save(update_fields=["stock"])

    Pago.objects.create(
        apartado=apartado,
        monto=anticipo,
        tipo=Pago.ANTICIPO if anticipo < apartado.total else Pago.LIQUIDACION,
        metodo=metodo,
        registrado_por=usuario,
    )
    apartado.vendedor = usuario
    apartado.estado = Apartado.PAGADO if anticipo >= apartado.total else Apartado.ACTIVO
    apartado.vence = timezone.now() + timedelta(days=settings.VIGENCIA_APARTADO_DIAS)
    apartado.save(update_fields=["vendedor", "estado", "vence"])

    encargo = sum(i.cantidad - i.de_inventario for i in items)
    extra = f" {encargo} pieza(s) se piden al proveedor." if encargo else ""
    _aviso(
        apartado,
        "CONFIRMACION",
        f"Tu pedido {apartado.folio} ({apartado.resumen}) quedó registrado. Anticipo recibido: ${anticipo}. "
        f"Saldo: ${apartado.saldo}. Vigente hasta el {timezone.localtime(apartado.vence):%d/%m/%Y}.{extra}",
    )
    if apartado.estado == Apartado.PAGADO:
        _aviso(apartado, "LISTO", f"Tu pedido {apartado.folio} está liquidado. Pasa a recogerlo.")
    return apartado


# --------------------------------------------------------------------------
# RF-03: pagos y abonos
# --------------------------------------------------------------------------
@transaction.atomic
def registrar_pago(*, apartado, monto, metodo, usuario):
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    monto = _dinero(monto)

    if apartado.estado != Apartado.ACTIVO:
        raise ReglaDeNegocioError(f"No se pueden registrar pagos en un pedido {apartado.get_estado_display().lower()}.")
    if monto <= 0:
        raise ReglaDeNegocioError("El monto debe ser mayor a cero.")
    saldo = apartado.saldo
    if monto > saldo:
        raise ReglaDeNegocioError(f"El pago (${monto}) excede el saldo pendiente (${saldo}).")

    liquida = monto == saldo
    Pago.objects.create(
        apartado=apartado,
        monto=monto,
        tipo=Pago.LIQUIDACION if liquida else Pago.ABONO,
        metodo=metodo,
        registrado_por=usuario,
    )
    if liquida:
        apartado.estado = Apartado.PAGADO
        apartado.save(update_fields=["estado"])
        _aviso(apartado, "LISTO", f"Tu pedido {apartado.folio} está liquidado. Pasa a recogerlo.")
    else:
        _aviso(
            apartado,
            "PAGO",
            f"Recibimos tu abono de ${monto} en {apartado.folio}. Saldo pendiente: ${apartado.saldo}.",
        )
    return apartado


# --------------------------------------------------------------------------
# Entrega de la prenda
# --------------------------------------------------------------------------
@transaction.atomic
def entregar_apartado(*, apartado, usuario):
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    if apartado.estado != Apartado.PAGADO:
        raise ReglaDeNegocioError("Solo se puede entregar un pedido liquidado (saldo en $0).")
    apartado.estado = Apartado.ENTREGADO
    apartado.save(update_fields=["estado"])
    _aviso(apartado, "ENTREGADO", f"Entrega del pedido {apartado.folio} realizada. ¡Gracias por tu compra!")
    return apartado


# --------------------------------------------------------------------------
# RF-06: cancelar pedido / rechazar solicitud
# --------------------------------------------------------------------------
def _devolver_stock(apartado):
    for item in apartado.items.all():
        if item.de_inventario:
            prenda = Prenda.objects.select_for_update().get(pk=item.prenda_id)
            prenda.stock += item.de_inventario
            prenda.save(update_fields=["stock"])
            item.de_inventario = 0
            item.save(update_fields=["de_inventario"])


@transaction.atomic
def cancelar_apartado(*, apartado, motivo, usuario):
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    if not apartado.puede_cancelarse:
        raise ReglaDeNegocioError(f"No se puede cancelar un pedido {apartado.get_estado_display().lower()}.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ReglaDeNegocioError("Indica el motivo de la cancelación.")

    _devolver_stock(apartado)
    apartado.estado = Apartado.CANCELADO
    apartado.motivo_cancelacion = motivo
    apartado.save(update_fields=["estado", "motivo_cancelacion"])
    _aviso(apartado, "CANCELADO", f"Tu pedido {apartado.folio} fue cancelado. Motivo: {motivo}.")
    return apartado


# --------------------------------------------------------------------------
# RF-13: vencimiento automático a los 30 días + aviso previo (RF-04)
# --------------------------------------------------------------------------
@transaction.atomic
def procesar_vencimientos(ahora=None):
    """Marca como vencidos los pedidos pasados de fecha y avisa de los próximos a vencer."""
    ahora = ahora or timezone.now()
    vencidos, avisados = 0, 0

    for ap in Apartado.objects.select_for_update().filter(estado__in=[Apartado.ACTIVO, Apartado.SOLICITADO], vence__lt=ahora):
        _devolver_stock(ap)
        ap.estado = Apartado.VENCIDO
        ap.save(update_fields=["estado"])
        _aviso(
            ap,
            "VENCIDO",
            f"Tu pedido {ap.folio} venció sin completarse. Las piezas apartadas regresaron a inventario.",
        )
        vencidos += 1

    limite = ahora + timedelta(days=settings.AVISO_VENCIMIENTO_DIAS)
    por_vencer = Apartado.objects.filter(
        estado=Apartado.ACTIVO, vence__gte=ahora, vence__lte=limite, aviso_vencimiento_enviado=False
    )
    for ap in por_vencer:
        _aviso(
            ap,
            "POR_VENCER",
            f"Tu pedido {ap.folio} vence el {timezone.localtime(ap.vence):%d/%m/%Y}. "
            f"Saldo pendiente: ${ap.saldo}.",
        )
        ap.aviso_vencimiento_enviado = True
        ap.save(update_fields=["aviso_vencimiento_enviado"])
        avisados += 1
    return vencidos, avisados


# --------------------------------------------------------------------------
# RF-16: entrada de mercancía
# --------------------------------------------------------------------------
@transaction.atomic
def registrar_entrada(*, prenda, cantidad, proveedor, remision, usuario):
    prenda = Prenda.objects.select_for_update().get(pk=prenda.pk)
    cantidad = int(cantidad)
    if cantidad < 1:
        raise ReglaDeNegocioError("La cantidad recibida debe ser de al menos 1 pieza.")

    entrada = EntradaMercancia.objects.create(
        prenda=prenda, cantidad=cantidad, proveedor=proveedor, remision=remision, registrado_por=usuario
    )
    prenda.stock += cantidad
    prenda.save(update_fields=["stock"])

    # Avisar a quien esperaba esta prenda por encargo
    esperando = Apartado.objects.filter(
        estado__in=[Apartado.ACTIVO, Apartado.PAGADO],
        items__prenda=prenda,
        items__cantidad__gt=F("items__de_inventario"),
    ).distinct()
    for ap in esperando:
        _aviso(ap, "LLEGO_PEDIDO", f"Llegó mercancía de tu pedido {ap.folio} ({prenda}). Pasa a la tienda.")
    return entrada


# --------------------------------------------------------------------------
# Consultas de apoyo
# --------------------------------------------------------------------------
def buscar_apartado_publico(folio, telefono):
    """RF-05: el cliente consulta su pedido con folio + teléfono."""
    folio = (folio or "").strip().upper()
    telefono = "".join(ch for ch in (telefono or "") if ch.isdigit())
    try:
        return Apartado.objects.select_related("cliente").prefetch_related("items__prenda").get(
            folio=folio, cliente__telefono=telefono
        )
    except Apartado.DoesNotExist:
        return None


def get_or_create_cliente(nombre, telefono, email=""):
    cliente, creado = Cliente.objects.get_or_create(telefono=telefono, defaults={"nombre": nombre, "email": email})
    return cliente
