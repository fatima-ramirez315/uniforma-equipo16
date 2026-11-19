"""Datos de demostración reutilizables: catálogo por modelo, color y talla, y usuarios por rol."""
import os
from decimal import Decimal

from django.contrib.auth.models import User

from .models import Perfil, Prenda

TALLAS = ["XS", "CH", "M", "L", "XL", "XXL"]
EXTRA = {"XL": 10, "XXL": 20}  # las tallas grandes cuestan un poco más
FACTORES = [1.0, 0.7, 0.5, 0.35]  # cada color nuevo tiene un poco menos de existencia

# prefijo, modelo, categoría, precio base, stock por talla (XS, CH, M, L, XL, XXL), colores [(clave, nombre)]
MODELOS = [
    ("ESC-CAM", "Camisa escolar manga corta", "ESCOLAR", "185.00", [4, 14, 20, 15, 6, 2],
     [("BLA", "Blanco"), ("AZC", "Azul cielo"), ("BEI", "Beige")]),
    ("ESC-FAL", "Falda escolar plisada", "ESCOLAR", "260.00", [5, 10, 8, 6, 3, 0],
     [("AZM", "Azul marino"), ("GRI", "Gris"), ("GUI", "Guinda")]),
    ("ESC-PAN", "Pantalón escolar", "ESCOLAR", "290.00", [3, 9, 12, 10, 5, 2],
     [("GRI", "Gris"), ("AZM", "Azul marino"), ("BEI", "Beige")]),
    ("DEP-PLA", "Playera deportiva", "DEPORTIVO", "150.00", [6, 12, 18, 14, 8, 4],
     [("ROJ", "Rojo"), ("BLA", "Blanco"), ("AZR", "Azul rey"), ("NEG", "Negro")]),
    ("DEP-CHA", "Chamarra deportiva", "DEPORTIVO", "480.00", [2, 5, 8, 6, 3, 0],
     [("NEG", "Negro"), ("AZM", "Azul marino"), ("ROJ", "Rojo")]),
    ("EMP-CAM", "Camisa empresarial", "EMPRESARIAL", "320.00", [2, 6, 10, 9, 4, 2],
     [("BLA", "Blanco"), ("AZC", "Azul cielo"), ("GRI", "Gris")]),
    ("EMP-CHA", "Chaleco empresarial", "EMPRESARIAL", "390.00", [1, 4, 6, 5, 3, 1],
     [("GOX", "Gris Oxford"), ("NEG", "Negro"), ("AZM", "Azul marino")]),
    ("MED-FIL", "Filipina médica", "MEDICO", "340.00", [3, 8, 11, 9, 5, 2],
     [("BLA", "Blanco"), ("VQ", "Verde quirófano"), ("AZM", "Azul marino"), ("VIN", "Vino")]),
    ("MED-PAN", "Pantalón médico", "MEDICO", "320.00", [2, 7, 10, 8, 4, 1],
     [("BLA", "Blanco"), ("VQ", "Verde quirófano"), ("AZM", "Azul marino"), ("VIN", "Vino")]),
]
MODELO_DE = {m[0]: m[1] for m in MODELOS}


def prenda(prefijo, color, talla):
    return Prenda.objects.get(modelo=MODELO_DE[prefijo], color=color, talla=talla)


def cargar_catalogo():
    """Crea el catálogo completo (todas las tallas y colores). Es seguro repetirlo: no pisa existencias ni precios."""
    Prenda.objects.exclude(talla__in=TALLAS).filter(partidas__isnull=True).delete()
    nuevas = 0
    for prefijo, modelo, cat, precio, stocks, colores in MODELOS:
        for i, (clave, color) in enumerate(colores):
            for talla, base in zip(TALLAS, stocks):
                stock = round(base * FACTORES[i]) if not (i >= 2 and talla == "XXL") else 0
                _, creada = Prenda.objects.get_or_create(
                    modelo=modelo, color=color, talla=talla,
                    defaults=dict(codigo=f"{prefijo}-{clave}-{talla}", categoria=cat, precio=Decimal(precio) + EXTRA.get(talla, 0),
                                  stock=stock, stock_minimo=3, activa=True),
                )
                nuevas += creada
    return nuevas


def asegurar_usuarios(pw_gerente, pw_vendedor, reiniciar=False):
    """Crea gerente y vendedor. Con ``reiniciar`` también les cambia la contraseña."""
    usuarios = []
    for nombre, rol, pw, staff in (("gerente", Perfil.GERENTE, pw_gerente, True), ("vendedor", Perfil.VENDEDOR, pw_vendedor, False)):
        user, creado = User.objects.get_or_create(username=nombre, defaults={"first_name": nombre.title(), "is_staff": staff})
        if creado or reiniciar:
            user.set_password(pw)
            user.is_staff = staff
            user.save()
        Perfil.objects.update_or_create(usuario=user, defaults={"rol": rol})
        usuarios.append(user)
    return usuarios


def autoseed(**kwargs):
    """Para despliegues sin terminal (Render gratis): con AUTOSEED_DEMO=1 llena el catálogo y crea los usuarios
    después de ``migrate``. Las contraseñas vienen de DEMO_GERENTE_PASSWORD y DEMO_VENDEDOR_PASSWORD."""
    if os.environ.get("AUTOSEED_DEMO") != "1":
        return
    cargar_catalogo()
    pg, pv = os.environ.get("DEMO_GERENTE_PASSWORD"), os.environ.get("DEMO_VENDEDOR_PASSWORD")
    if pg and pv:
        asegurar_usuarios(pg, pv)
