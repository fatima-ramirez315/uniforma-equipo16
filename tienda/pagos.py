"""Datos para pagar por transferencia. Se pueden cambiar con variables de entorno (sin tocar el código)."""
import os


def datos_transferencia():
    return {
        "banco": os.environ.get("TRANSFER_BANCO", "BBVA (cuenta de ejemplo)"),
        "titular": os.environ.get("TRANSFER_TITULAR", "Uniforma Equipo 16"),
        "clabe": os.environ.get("TRANSFER_CLABE", "012345678901234567"),
    }
