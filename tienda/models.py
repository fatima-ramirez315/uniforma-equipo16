from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


class Perfil(models.Model):
    """Rol del usuario interno (Vendedor o Gerente). RF-12."""

    VENDEDOR = "VENDEDOR"
    GERENTE = "GERENTE"
    ROLES = [(VENDEDOR, "Vendedor"), (GERENTE, "Gerente")]

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name="perfil")
    rol = models.CharField(max_length=10, choices=ROLES, default=VENDEDOR)

    def __str__(self):
        return f"{self.usuario.get_username()} ({self.get_rol_display()})"


class Cliente(models.Model):
    """RF-11: registro de clientes."""

    nombre = models.CharField(max_length=120)
    telefono = models.CharField(
        max_length=15,
        unique=True,
        validators=[RegexValidator(r"^\d{10}$", "El teléfono debe tener 10 dígitos.")],
    )
    email = models.EmailField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.telefono})"


class Prenda(models.Model):
    """Un modelo de uniforme en una talla y color concretos (RF-01, RF-10)."""

    CATEGORIAS = [
        ("ESCOLAR", "Escolar"),
        ("DEPORTIVO", "Deportivo"),
        ("EMPRESARIAL", "Empresarial"),
        ("MEDICO", "Médico"),
        ("OTRO", "Otro"),
    ]

    TALLAS = [
        ("XS", "XS · Extra chica"),
        ("CH", "CH · Chica"),
        ("M", "M · Mediana"),
        ("L", "L · Grande"),
        ("XL", "XL · Extra grande"),
        ("XXL", "XXL · Doble extra grande"),
    ]
    ORDEN_TALLAS = [t for t, _ in TALLAS]

    codigo = models.CharField(max_length=20, unique=True)
    modelo = models.CharField(max_length=120)
    categoria = models.CharField(max_length=12, choices=CATEGORIAS, default="ESCOLAR")
    talla = models.CharField(max_length=6, choices=TALLAS)
    color = models.CharField(max_length=40)
    precio = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    stock = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(default=3)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["modelo", "color"]
        constraints = [
            models.UniqueConstraint(fields=["modelo", "talla", "color"], name="prenda_modelo_talla_color_unica"),
        ]

    def __str__(self):
        return f"{self.modelo} · talla {self.talla} · {self.color}"

    @property
    def disponible(self):
        return self.activa and self.stock > 0

    @property
    def stock_bajo(self):
        return self.activa and self.stock <= self.stock_minimo

    COLORES_HEX = {
        "Blanco": "#f8fafc", "Negro": "#111827", "Gris": "#9ca3af", "Gris Oxford": "#4b5563", "Azul marino": "#1e3a8a",
        "Azul cielo": "#7dd3fc", "Azul rey": "#2563eb", "Rojo": "#dc2626", "Beige": "#e7d3b1", "Guinda": "#7f1d1d",
        "Vino": "#7b1f3a", "Verde quirófano": "#34d399",
    }

    @property
    def color_hex(self):
        return self.COLORES_HEX.get(self.color, "#cbd5e1")

    @property
    def talla_nombre(self):
        """«Extra chica», «Mediana»… (sin la abreviatura)."""
        return self.get_talla_display().split(" · ")[-1]

    @property
    def orden_talla(self):
        return self.ORDEN_TALLAS.index(self.talla) if self.talla in self.ORDEN_TALLAS else 99


class Apartado(models.Model):
    """RF-02, RF-05, RF-06, RF-08. Un pedido: varias prendas/tallas, pedido por el cliente o en mostrador."""

    SOLICITADO = "SOLICITADO"
    ACTIVO = "ACTIVO"
    PAGADO = "PAGADO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"
    VENCIDO = "VENCIDO"
    ESTADOS = [
        (SOLICITADO, "Solicitud en línea (falta anticipo)"),
        (ACTIVO, "Activo (con saldo pendiente)"),
        (PAGADO, "Liquidado (listo para entregar)"),
        (ENTREGADO, "Entregado"),
        (CANCELADO, "Cancelado"),
        (VENCIDO, "Vencido"),
    ]

    MOSTRADOR = "MOSTRADOR"
    EN_LINEA = "EN_LINEA"
    ORIGENES = [(MOSTRADOR, "Mostrador"), (EN_LINEA, "En línea (cliente)")]

    folio = models.CharField(max_length=12, unique=True, editable=False, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="apartados")
    origen = models.CharField(max_length=10, choices=ORIGENES, default=MOSTRADOR)
    estado = models.CharField(max_length=10, choices=ESTADOS, default=ACTIVO, db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    creado = models.DateTimeField(default=timezone.now)
    vence = models.DateTimeField()
    vendedor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="apartados_registrados", null=True, blank=True)
    notas = models.CharField(max_length=255, blank=True)
    motivo_cancelacion = models.CharField(max_length=255, blank=True)
    aviso_vencimiento_enviado = models.BooleanField(default=False)

    class Meta:
        ordering = ["-creado"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.folio:
            self.folio = f"APT-{self.pk:05d}"
            super().save(update_fields=["folio"])

    def __str__(self):
        return self.folio

    # --- cálculos -----------------------------------------------------
    @property
    def pagado(self):
        return self.pagos.aggregate(s=models.Sum("monto"))["s"] or Decimal("0")

    @property
    def saldo(self):
        return self.total - self.pagado

    @property
    def anticipo_requerido(self):
        return (self.total * Decimal(settings.ANTICIPO_PORCENTAJE) / Decimal(100)).quantize(Decimal("0.01"))

    @property
    def piezas(self):
        return sum(i.cantidad for i in self.items.all())

    @property
    def por_encargo(self):
        return sum(i.por_encargo for i in self.items.all())

    @property
    def resumen(self):
        n = self.items.count()
        return f"{self.piezas} pieza(s) en {n} partida(s)"

    @property
    def dias_restantes(self):
        return (self.vence - timezone.now()).days

    @property
    def es_solicitud(self):
        return self.estado == self.SOLICITADO

    @property
    def es_activo(self):
        return self.estado == self.ACTIVO

    @property
    def puede_cancelarse(self):
        return self.estado in (self.SOLICITADO, self.ACTIVO, self.PAGADO)

    @property
    def puede_entregarse(self):
        return self.estado == self.PAGADO


class ApartadoItem(models.Model):
    """Una partida del pedido: una prenda en una talla, con su cantidad.

    ``de_inventario`` son las piezas que se apartaron del stock; el resto
    (``por_encargo``) se pide al proveedor (pedidos grandes o tallas agotadas).
    """

    apartado = models.ForeignKey(Apartado, on_delete=models.CASCADE, related_name="items")
    prenda = models.ForeignKey(Prenda, on_delete=models.PROTECT, related_name="partidas")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    de_inventario = models.PositiveIntegerField(default=0)
    precio_unitario = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        ordering = ["prenda__modelo", "prenda__color", "id"]
        constraints = [models.UniqueConstraint(fields=["apartado", "prenda"], name="partida_unica_por_prenda")]

    def __str__(self):
        return f"{self.cantidad} x {self.prenda}"

    @property
    def por_encargo(self):
        return self.cantidad - self.de_inventario

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad


class Pago(models.Model):
    """RF-03: anticipo, abonos y liquidación."""

    ANTICIPO = "ANTICIPO"
    ABONO = "ABONO"
    LIQUIDACION = "LIQUIDACION"
    TIPOS = [(ANTICIPO, "Anticipo"), (ABONO, "Abono"), (LIQUIDACION, "Liquidación")]

    METODOS = [("EFECTIVO", "Efectivo"), ("TARJETA", "Tarjeta"), ("TRANSFERENCIA", "Transferencia")]

    apartado = models.ForeignKey(Apartado, on_delete=models.CASCADE, related_name="pagos")
    monto = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    tipo = models.CharField(max_length=12, choices=TIPOS)
    metodo = models.CharField(max_length=14, choices=METODOS, default="EFECTIVO")
    fecha = models.DateTimeField(default=timezone.now)
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.apartado.folio} · {self.get_tipo_display()} ${self.monto}"


class Notificacion(models.Model):
    """RF-04: avisos al cliente sobre su apartado (se guardan y se muestran en el panel)."""

    TIPOS = [
        ("CONFIRMACION", "Confirmación de apartado"),
        ("PAGO", "Pago recibido"),
        ("LISTO", "Listo para entregar"),
        ("POR_VENCER", "Apartado por vencer"),
        ("VENCIDO", "Apartado vencido"),
        ("CANCELADO", "Apartado cancelado"),
        ("ENTREGADO", "Entrega realizada"),
        ("LLEGO_PEDIDO", "Llegó pedido especial"),
        ("SOLICITUD", "Solicitud recibida"),
    ]

    apartado = models.ForeignKey(Apartado, on_delete=models.CASCADE, related_name="notificaciones")
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="notificaciones")
    tipo = models.CharField(max_length=14, choices=TIPOS)
    mensaje = models.CharField(max_length=300)
    fecha = models.DateTimeField(default=timezone.now)
    atendida = models.BooleanField(default=False, help_text="El vendedor ya avisó al cliente.")

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()} → {self.cliente.nombre}"


class EntradaMercancia(models.Model):
    """RF-16: registro de mercancía que llega de proveedores."""

    prenda = models.ForeignKey(Prenda, on_delete=models.PROTECT, related_name="entradas")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    proveedor = models.CharField(max_length=120)
    remision = models.CharField("Folio de remisión", max_length=40, blank=True)
    fecha = models.DateTimeField(default=timezone.now)
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "entradas de mercancía"

    def __str__(self):
        return f"+{self.cantidad} {self.prenda} ({self.proveedor})"
