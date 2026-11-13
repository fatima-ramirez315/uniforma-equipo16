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

CATALOGO = [
    # codigo, modelo, categoria, talla, color, precio, stock, minimo
    ("ESC-CAM-CH", "Camisa escolar manga corta", "ESCOLAR", "CH", "Blanco", "185.00", 14, 4),
    ("ESC-CAM-M", "Camisa escolar manga corta", "ESCOLAR", "M", "Blanco", "185.00", 9, 4),
    ("ESC-CAM-G", "Camisa escolar manga corta", "ESCOLAR", "G", "Blanco", "195.00", 2, 4),
    ("ESC-FAL-12", "Falda escolar plisada", "ESCOLAR", "12", "Azul marino", "260.00", 6, 3),
    ("ESC-FAL-14", "Falda escolar plisada", "ESCOLAR", "14", "Azul marino", "270.00", 0, 3),
    ("ESC-PAN-28", "Pantalón escolar", "ESCOLAR", "28", "Gris", "290.00", 8, 3),
    ("ESC-PAN-30", "Pantalón escolar", "ESCOLAR", "30", "Gris", "300.00", 5, 3),
    ("DEP-PLA-M", "Playera deportiva", "DEPORTIVO", "M", "Rojo", "150.00", 12, 5),
    ("DEP-CHA-G", "Chamarra deportiva", "DEPORTIVO", "G", "Negro", "480.00", 3, 3),
    ("EMP-CHA-M", "Chaleco empresarial", "EMPRESARIAL", "M", "Gris Oxford", "390.00", 4, 2),
    ("MED-FIL-M", "Filipina médica", "MEDICO", "M", "Verde quirófano", "340.00", 7, 3),
    ("MED-PAN-L", "Pantalón médico", "MEDICO", "L", "Verde quirófano", "320.00", 1, 3),
]


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

        for cod, modelo, cat, talla, color, precio, stock, minimo in CATALOGO:
            Prenda.objects.update_or_create(
                codigo=cod,
                defaults=dict(modelo=modelo, categoria=cat, talla=talla, color=color, precio=Decimal(precio), stock=stock, stock_minimo=minimo, activa=True),
            )

        if Apartado.objects.exists():
            self.stdout.write("Ya hay apartados; no se crean más de ejemplo.")
        else:
            c1 = Cliente.objects.get_or_create(telefono="7771234567", defaults={"nombre": "María López Hernández", "email": "maria@example.com"})[0]
            c2 = Cliente.objects.get_or_create(telefono="7779876543", defaults={"nombre": "Carlos Ramírez Soto"})[0]
            c3 = Cliente.objects.get_or_create(telefono="7775551122", defaults={"nombre": "Ana Torres Vega"})[0]

            a1 = services.crear_apartado(cliente=c1, prenda=Prenda.objects.get(codigo="ESC-CAM-M"), cantidad=2, anticipo=Decimal("185.00"), metodo="EFECTIVO", vendedor=vendedor)
            services.registrar_pago(apartado=a1, monto=Decimal("100.00"), metodo="EFECTIVO", usuario=vendedor)
            a2 = services.crear_apartado(cliente=c2, prenda=Prenda.objects.get(codigo="ESC-PAN-30"), cantidad=1, anticipo=Decimal("300.00"), metodo="TARJETA", vendedor=vendedor)
            a3 = services.crear_apartado(cliente=c3, prenda=Prenda.objects.get(codigo="ESC-FAL-14"), cantidad=1, anticipo=Decimal("135.00"), metodo="EFECTIVO", vendedor=vendedor, tipo=Apartado.ESPECIAL, notas="Pedido especial, talla agotada")
            # Un apartado próximo a vencer para demostrar la alerta
            a4 = services.crear_apartado(cliente=c2, prenda=Prenda.objects.get(codigo="DEP-PLA-M"), cantidad=3, anticipo=Decimal("225.00"), metodo="EFECTIVO", vendedor=vendedor)
            Apartado.objects.filter(pk=a4.pk).update(creado=timezone.now() - timedelta(days=27), vence=timezone.now() + timedelta(days=3))
            self.stdout.write(f"Apartados de ejemplo: {a1.folio}, {a2.folio}, {a3.folio}, {a4.folio}")

        self.stdout.write(self.style.SUCCESS("Datos demo listos."))
        self.stdout.write(f"  gerente  → contraseña: {pw_gerente}")
        self.stdout.write(f"  vendedor → contraseña: {pw_vendedor}")
