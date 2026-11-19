"""Carga datos de demostración: usuarios por rol, catálogo, clientes y apartados."""
import os
import secrets
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tienda import demo, services
from tienda.models import Apartado, Cliente


def _prenda(prefijo, color, talla):
    return demo.prenda(prefijo, color, talla)


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

        gerente, vendedor = demo.asegurar_usuarios(pw_gerente, pw_vendedor, reiniciar=True)
        nuevas = demo.cargar_catalogo()
        self.stdout.write(f"Catálogo: {nuevas} prendas nuevas (modelos × colores × tallas XS–XXL).")

        if Apartado.objects.exists():
            self.stdout.write("Ya hay apartados; no se crean más de ejemplo.")
        else:
            c1 = Cliente.objects.get_or_create(telefono="7771234567", defaults={"nombre": "María López Hernández", "email": "maria@example.com"})[0]
            c2 = Cliente.objects.get_or_create(telefono="7779876543", defaults={"nombre": "Carlos Ramírez Soto"})[0]
            c3 = Cliente.objects.get_or_create(telefono="7775551122", defaults={"nombre": "Ana Torres Vega"})[0]

            def pedir(cliente, lineas, **kw):
                lineas = [(_prenda(pre, col, t), c) for pre, col, t, c in lineas]
                return services.crear_pedido(cliente=cliente, lineas=lineas, vendedor=vendedor, anticipo=_anticipo(lineas), metodo="EFECTIVO", **kw)

            # Pedido con varias tallas: 2 M + 1 L + 1 XL de camisa escolar
            a1 = pedir(c1, [("ESC-CAM", "Blanco", "M", 2), ("ESC-CAM", "Blanco", "L", 1), ("ESC-CAM", "Blanco", "XL", 1)])
            services.registrar_pago(apartado=a1, monto=Decimal("100.00"), metodo="EFECTIVO", usuario=vendedor)
            # Pedido liquidado, listo para entregar
            lin2 = [(_prenda("ESC-PAN", "Gris", "M"), 1)]
            a2 = services.crear_pedido(cliente=c2, lineas=lin2, vendedor=vendedor, anticipo=Decimal("290.00"), metodo="TARJETA")
            # Talla agotada: la falda XXL se pide al proveedor
            a3 = pedir(c3, [("ESC-FAL", "Azul marino", "XXL", 2), ("ESC-FAL", "Azul marino", "M", 1)], notas="Falda XXL por encargo")
            # Un pedido próximo a vencer para demostrar la alerta
            a4 = pedir(c2, [("DEP-PLA", "Rojo", "M", 3)])
            Apartado.objects.filter(pk=a4.pk).update(creado=timezone.now() - timedelta(days=27), vence=timezone.now() + timedelta(days=3))
            # Solicitud hecha por el propio cliente en línea (pedido grande, varias tallas)
            escuela = Cliente.objects.get_or_create(telefono="7775559900", defaults={"nombre": "Escuela Primaria Benito Juárez"})[0]
            a5 = services.crear_pedido(
                cliente=escuela, notas="Uniformes para el ciclo escolar",
                lineas=[(_prenda("ESC-CAM", "Blanco", "CH"), 20), (_prenda("ESC-CAM", "Blanco", "M"), 30), (_prenda("ESC-CAM", "Blanco", "L"), 200), (_prenda("ESC-CAM", "Blanco", "XXL"), 3)],
            )
            self.stdout.write(f"Pedidos de ejemplo: {a1.folio}, {a2.folio}, {a3.folio}, {a4.folio} y la solicitud en línea {a5.folio} (teléfono 7775559900)")

        self.stdout.write(self.style.SUCCESS("Datos demo listos."))
        self.stdout.write(f"  gerente  → contraseña: {pw_gerente}")
        self.stdout.write(f"  vendedor → contraseña: {pw_vendedor}")
