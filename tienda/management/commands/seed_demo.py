"""Carga datos de demostración: usuarios por rol, catálogo, clientes y apartados."""
import os
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tienda import services
from tienda.models import Apartado, Cliente, Perfil, Prenda

TALLAS = ["XS", "CH", "M", "L", "XL", "XXL"]
EXTRA = {"XL": 10, "XXL": 20}  # las tallas grandes cuestan un poco más

# prefijo, modelo, categoría, color, precio base, stock por talla (XS, CH, M, L, XL, XXL)
MODELOS = [
    ("ESC-CAM", "Camisa escolar manga corta", "ESCOLAR", "Blanco", "185.00", [4, 14, 20, 15, 6, 2]),
    ("ESC-FAL", "Falda escolar plisada", "ESCOLAR", "Azul marino", "260.00", [5, 10, 8, 6, 3, 0]),
    ("ESC-PAN", "Pantalón escolar", "ESCOLAR", "Gris", "290.00", [3, 9, 12, 10, 5, 2]),
    ("DEP-PLA", "Playera deportiva", "DEPORTIVO", "Rojo", "150.00", [6, 12, 18, 14, 8, 4]),
    ("DEP-CHA", "Chamarra deportiva", "DEPORTIVO", "Negro", "480.00", [2, 5, 8, 6, 3, 0]),
    ("EMP-CAM", "Camisa empresarial", "EMPRESARIAL", "Azul cielo", "320.00", [2, 6, 10, 9, 4, 2]),
    ("EMP-CHA", "Chaleco empresarial", "EMPRESARIAL", "Gris Oxford", "390.00", [1, 4, 6, 5, 3, 1]),
    ("MED-FIL", "Filipina médica", "MEDICO", "Verde quirófano", "340.00", [3, 8, 11, 9, 5, 2]),
    ("MED-PAN", "Pantalón médico", "MEDICO", "Verde quirófano", "320.00", [0, 7, 10, 8, 4, 1]),
]


def _prenda(prefijo, talla):
    return Prenda.objects.get(codigo=f"{prefijo}-{talla}")


def _anticipo(lineas):
    total = sum(p.precio * c for p, c in lineas)
    return (total / 2).quantize(Decimal("0.01"))


class Command(BaseCommand):
    help = "Crea usuarios (gerente / vendedor), catálogo y apartados de ejemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        # Las contraseñas de demo NO viven en el código: vienen del entorno o se generan al azar.
        pw_gerente = os.environ.get("DEMO_GERENTE_PASSWORD") or secrets.token_urlsafe(9)
        pw_vendedor = os.environ.get("DEMO_VENDEDOR_PASSWORD") or secrets.token_urlsafe(9)

        gerente, _ = User.objects.get_or_create(username="gerente", defaults={"first_name": "Gerente", "is_staff": True})
        gerente.set_password(pw_gerente)
        gerente.is_staff = True
        gerente.save()
        Perfil.objects.update_or_create(usuario=gerente, defaults={"rol": Perfil.GERENTE})

        vendedor, _ = User.objects.get_or_create(username="vendedor", defaults={"first_name": "Vendedor"})
        vendedor.set_password(pw_vendedor)
        vendedor.save()
        Perfil.objects.update_or_create(usuario=vendedor, defaults={"rol": Perfil.VENDEDOR})

        # Quita prendas de versiones anteriores con tallas que ya no existen (si no tienen pedidos)
        Prenda.objects.exclude(talla__in=TALLAS).filter(partidas__isnull=True).delete()

        for prefijo, modelo, cat, color, precio, stocks in MODELOS:
            for talla, stock in zip(TALLAS, stocks):
                Prenda.objects.update_or_create(
                    codigo=f"{prefijo}-{talla}",
                    defaults=dict(modelo=modelo, categoria=cat, talla=talla, color=color,
                                  precio=Decimal(precio) + EXTRA.get(talla, 0), stock=stock, stock_minimo=3, activa=True),
                )

        if Apartado.objects.exists():
            self.stdout.write("Ya hay apartados; no se crean más de ejemplo.")
        else:
            c1 = Cliente.objects.get_or_create(telefono="7771234567", defaults={"nombre": "María López Hernández", "email": "maria@example.com"})[0]
            c2 = Cliente.objects.get_or_create(telefono="7779876543", defaults={"nombre": "Carlos Ramírez Soto"})[0]
            c3 = Cliente.objects.get_or_create(telefono="7775551122", defaults={"nombre": "Ana Torres Vega"})[0]

            def pedir(cliente, lineas, **kw):
                lineas = [(_prenda(pre, t), c) for pre, t, c in lineas]
                return services.crear_pedido(cliente=cliente, lineas=lineas, vendedor=vendedor, anticipo=_anticipo(lineas), metodo="EFECTIVO", **kw)

            # Pedido con varias tallas: 2 M + 1 L + 1 XL de camisa escolar
            a1 = pedir(c1, [("ESC-CAM", "M", 2), ("ESC-CAM", "L", 1), ("ESC-CAM", "XL", 1)])
            services.registrar_pago(apartado=a1, monto=Decimal("100.00"), metodo="EFECTIVO", usuario=vendedor)
            # Pedido liquidado, listo para entregar
            lin2 = [(_prenda("ESC-PAN", "M"), 1)]
            a2 = services.crear_pedido(cliente=c2, lineas=lin2, vendedor=vendedor, anticipo=Decimal("290.00"), metodo="TARJETA")
            # Talla agotada: la falda XXL se pide al proveedor
            a3 = pedir(c3, [("ESC-FAL", "XXL", 2), ("ESC-FAL", "M", 1)], notas="Falda XXL por encargo")
            # Un pedido próximo a vencer para demostrar la alerta
            a4 = pedir(c2, [("DEP-PLA", "M", 3)])
            Apartado.objects.filter(pk=a4.pk).update(creado=timezone.now() - timedelta(days=27), vence=timezone.now() + timedelta(days=3))
            # Solicitud hecha por el propio cliente en línea (pedido grande, varias tallas)
            escuela = Cliente.objects.get_or_create(telefono="7775559900", defaults={"nombre": "Escuela Primaria Benito Juárez"})[0]
            a5 = services.crear_pedido(
                cliente=escuela, notas="Uniformes para el ciclo escolar",
                lineas=[(_prenda("ESC-CAM", "CH"), 20), (_prenda("ESC-CAM", "M"), 30), (_prenda("ESC-CAM", "L"), 200), (_prenda("ESC-CAM", "XXL"), 3)],
            )
            self.stdout.write(f"Pedidos de ejemplo: {a1.folio}, {a2.folio}, {a3.folio}, {a4.folio} y la solicitud en línea {a5.folio} (teléfono 7775559900)")

        self.stdout.write(self.style.SUCCESS("Datos demo listos."))
        self.stdout.write(f"  gerente  → contraseña: {pw_gerente}")
        self.stdout.write(f"  vendedor → contraseña: {pw_vendedor}")
