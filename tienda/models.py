"""Modelos de Uniforma: implementan las 7 tablas del diseño de BD de U2
(Cliente, Usuario, Prenda, Apartado, Pago, Notificacion, EntradaMercancia)."""
from django.db import models


class Cliente(models.Model):
    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=20)
    correo = models.EmailField(blank=True)

    def __str__(self):
        return self.nombre


class Usuario(models.Model):
    class Rol(models.TextChoices):
        VENDEDOR = 'VENDEDOR', 'Vendedor'
        GERENTE = 'GERENTE', 'Gerente'

    nombre = models.CharField(max_length=120)
    correo = models.EmailField(unique=True)
    rol = models.CharField(max_length=10, choices=Rol.choices)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.nombre} ({self.get_rol_display()})'


class Prenda(models.Model):
    modelo = models.CharField(max_length=100)
    talla = models.CharField(max_length=10)
    color = models.CharField(max_length=30)
    precio = models.DecimalField(max_digits=8, decimal_places=2)
    existencias = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['modelo', 'talla', 'color'], name='prenda_unica')
        ]

    def __str__(self):
        return f'{self.modelo} {self.talla} {self.color}'


class Apartado(models.Model):
    class Estado(models.TextChoices):
        ACTIVO = 'ACTIVO', 'Activo'
        ENTREGADO = 'ENTREGADO', 'Entregado'
        CANCELADO = 'CANCELADO', 'Cancelado'
        VENCIDO = 'VENCIDO', 'Vencido'

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='apartados')
    prenda = models.ForeignKey(Prenda, on_delete=models.PROTECT, related_name='apartados')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='apartados')
    cantidad = models.PositiveIntegerField(default=1)
    fecha_apartado = models.DateField()
    fecha_limite = models.DateField()  # 30 días después (extend del CU)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)


class Pago(models.Model):
    class Tipo(models.TextChoices):
        ANTICIPO = 'ANTICIPO', 'Anticipo (50%)'
        LIQUIDACION = 'LIQUIDACION', 'Liquidación'

    apartado = models.ForeignKey(Apartado, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=8, decimal_places=2)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    fecha = models.DateTimeField(auto_now_add=True)


class Notificacion(models.Model):
    apartado = models.ForeignKey(Apartado, on_delete=models.CASCADE, related_name='notificaciones')
    mensaje = models.CharField(max_length=250)
    fecha_envio = models.DateTimeField(auto_now_add=True)
    enviada = models.BooleanField(default=False)


class EntradaMercancia(models.Model):
    prenda = models.ForeignKey(Prenda, on_delete=models.PROTECT, related_name='entradas')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='entradas')
    cantidad = models.PositiveIntegerField()
    fecha = models.DateField()
