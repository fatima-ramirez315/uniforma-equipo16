"""
Reglas de negocio de Uniforma. Toda la lógica que modifica inventario, pagos y
estados vive aquí, dentro de transacciones, para que las vistas sean delgadas
y las pruebas sencillas.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Apartado, Cliente, EntradaMercancia, Notificacion, Pago, Prenda


class ReglaDeNegocioError(Exception):
    """Se lanza cuando una operación viola una regla de negocio (mensaje apto para el usuario)."""


def _aviso(apartado, tipo, mensaje):
    return Notificacion.objects.create(
        apartado=apartado, cliente=apartado.cliente, tipo=tipo, mensaje=mensaje
    )


def _dinero(valor):
    return Decimal(valor).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------
# RF-02 / RF-08 / RF-09: registrar apartado o pedido especial
# --------------------------------------------------------------------------
@transaction.atomic
def crear_apartado(*, cliente, prenda, cantidad, anticipo, metodo, vendedor, tipo=Apartado.INVENTARIO, notas=""):
    prenda = Prenda.objects.select_for_update().get(pk=prenda.pk)
    cantidad = int(cantidad)
    anticipo = _dinero(anticipo)

    if cantidad < 1:
        raise ReglaDeNegocioError("La cantidad debe ser de al menos 1 pieza.")
    if not prenda.activa:
        raise ReglaDeNegocioError("Esta prenda está dada de baja del catálogo.")
    if tipo == Apartado.INVENTARIO and prenda.stock < cantidad:
        raise ReglaDeNegocioError(
            f"Solo hay {prenda.stock} pieza(s) disponibles de {prenda}. "
            "Si el cliente la necesita, regístrela como pedido especial."
        )

    total = _dinero(prenda.precio * cantidad)
    minimo = _dinero(total * Decimal(settings.ANTICIPO_PORCENTAJE) / Decimal(100))
    if anticipo < minimo:
        raise ReglaDeNegocioError(
            f"El anticipo mínimo es del {settings.ANTICIPO_PORCENTAJE}% (${minimo}). Se recibió ${anticipo}."
        )
    if anticipo > total:
        raise ReglaDeNegocioError(f"El anticipo (${anticipo}) no puede ser mayor al total (${total}).")

    apartado = Apartado.objects.create(
        cliente=cliente,
        prenda=prenda,
        cantidad=cantidad,
        tipo=tipo,
        total=total,
        vence=timezone.now() + timedelta(days=settings.VIGENCIA_APARTADO_DIAS),
        vendedor=vendedor,
        notas=notas,
    )
    Pago.objects.create(
        apartado=apartado,
        monto=anticipo,
        tipo=Pago.ANTICIPO if anticipo < total else Pago.LIQUIDACION,
        metodo=metodo,
        registrado_por=vendedor,
    )

    if tipo == Apartado.INVENTARIO:
        prenda.stock -= cantidad  # RF-09: el inventario se actualiza solo
        prenda.save(update_fields=["stock"])

    if anticipo >= total:
        apartado.estado = Apartado.PAGADO
        apartado.save(update_fields=["estado"])

    etiqueta = "pedido especial" if tipo == Apartado.ESPECIAL else "apartado"
    _aviso(
        apartado,
        "CONFIRMACION",
        f"Tu {etiqueta} {apartado.folio} de {cantidad} x {prenda} quedó registrado. "
        f"Anticipo recibido: ${anticipo}. Saldo: ${apartado.saldo}. "
        f"Vigente hasta el {timezone.localtime(apartado.vence):%d/%m/%Y}.",
    )
    if apartado.estado == Apartado.PAGADO:
        _aviso(apartado, "LISTO", f"Tu {etiqueta} {apartado.folio} está liquidado. Pasa a recogerlo.")
    return apartado


# --------------------------------------------------------------------------
# RF-03: pagos y abonos
# --------------------------------------------------------------------------
@transaction.atomic
def registrar_pago(*, apartado, monto, metodo, usuario):
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    monto = _dinero(monto)

    if apartado.estado != Apartado.ACTIVO:
        raise ReglaDeNegocioError(f"No se pueden registrar pagos en un apartado {apartado.get_estado_display().lower()}.")
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
        _aviso(apartado, "LISTO", f"Tu apartado {apartado.folio} está liquidado. Pasa a recogerlo.")
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
        raise ReglaDeNegocioError("Solo se puede entregar un apartado liquidado (saldo en $0).")
    apartado.estado = Apartado.ENTREGADO
    apartado.save(update_fields=["estado"])
    _aviso(apartado, "ENTREGADO", f"Entrega del apartado {apartado.folio} realizada. ¡Gracias por tu compra!")
    return apartado


# --------------------------------------------------------------------------
# RF-06: cancelar apartado
# --------------------------------------------------------------------------
def _devolver_stock(apartado):
    if apartado.tipo == Apartado.INVENTARIO:
        prenda = Prenda.objects.select_for_update().get(pk=apartado.prenda_id)
        prenda.stock += apartado.cantidad
        prenda.save(update_fields=["stock"])


@transaction.atomic
def cancelar_apartado(*, apartado, motivo, usuario):
    apartado = Apartado.objects.select_for_update().get(pk=apartado.pk)
    if not apartado.puede_cancelarse:
        raise ReglaDeNegocioError(f"No se puede cancelar un apartado {apartado.get_estado_display().lower()}.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ReglaDeNegocioError("Indica el motivo de la cancelación.")

    _devolver_stock(apartado)
    apartado.estado = Apartado.CANCELADO
    apartado.motivo_cancelacion = motivo
    apartado.save(update_fields=["estado", "motivo_cancelacion"])
    _aviso(apartado, "CANCELADO", f"Tu apartado {apartado.folio} fue cancelado. Motivo: {motivo}.")
    return apartado


# --------------------------------------------------------------------------
# RF-13: vencimiento automático a los 30 días + aviso previo (RF-04)
# --------------------------------------------------------------------------
@transaction.atomic
def procesar_vencimientos(ahora=None):
    """Marca como vencidos los apartados pasados de fecha y avisa de los próximos a vencer."""
    ahora = ahora or timezone.now()
    vencidos, avisados = 0, 0

    for ap in Apartado.objects.select_for_update().filter(estado=Apartado.ACTIVO, vence__lt=ahora):
        _devolver_stock(ap)
        ap.estado = Apartado.VENCIDO
        ap.save(update_fields=["estado"])
        _aviso(
            ap,
            "VENCIDO",
            f"Tu apartado {ap.folio} venció sin liquidarse. La prenda regresó a inventario.",
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
            f"Tu apartado {ap.folio} vence el {timezone.localtime(ap.vence):%d/%m/%Y}. "
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

    # Avisar a quien tenía un pedido especial de esta prenda
    for ap in Apartado.objects.filter(prenda=prenda, tipo=Apartado.ESPECIAL, estado__in=[Apartado.ACTIVO, Apartado.PAGADO]):
        _aviso(ap, "LLEGO_PEDIDO", f"Llegó tu pedido especial {ap.folio} ({prenda}). Pasa a la tienda.")
    return entrada


# --------------------------------------------------------------------------
# Consultas de apoyo
# --------------------------------------------------------------------------
def buscar_apartado_publico(folio, telefono):
    """RF-05: el cliente consulta su apartado con folio + teléfono."""
    folio = (folio or "").strip().upper()
    telefono = "".join(ch for ch in (telefono or "") if ch.isdigit())
    try:
        return Apartado.objects.select_related("cliente", "prenda").get(folio=folio, cliente__telefono=telefono)
    except Apartado.DoesNotExist:
        return None


def get_or_create_cliente(nombre, telefono, email=""):
    cliente, _ = Cliente.objects.get_or_create(telefono=telefono, defaults={"nombre": nombre, "email": email})
    return cliente
