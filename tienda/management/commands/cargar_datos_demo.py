from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from tienda.models import (Apartado, Cliente, EntradaMercancia, Notificacion,
                           Pago, Prenda, Usuario)


class Command(BaseCommand):
    help = 'Carga datos FICTICIOS de demostración (no hay personas reales).'

    @transaction.atomic
    def handle(self, *args, **opts):
        gerente, _ = Usuario.objects.get_or_create(
            correo='gerente.demo@example.com',
            defaults={'nombre': 'Gerente Demo', 'rol': Usuario.Rol.GERENTE})
        vendedor, _ = Usuario.objects.get_or_create(
            correo='vendedor.demo@example.com',
            defaults={'nombre': 'Vendedor Demo', 'rol': Usuario.Rol.VENDEDOR})
        cliente, _ = Cliente.objects.get_or_create(
            telefono='0000000001', defaults={'nombre': 'Cliente Demo 1', 'correo': 'cliente1@example.com'})
        datos = [('Camisa escolar', 'M', 'Blanco', 220, 15), ('Pantalón escolar', '30', 'Azul marino', 310, 8),
                 ('Falda escolar', 'S', 'Gris', 280, 5), ('Bata de laboratorio', 'L', 'Blanco', 350, 3)]
        prendas = [Prenda.objects.get_or_create(modelo=m, talla=t, color=c,
                   defaults={'precio': p, 'existencias': e})[0] for m, t, c, p, e in datos]
        if not Apartado.objects.exists():
            hoy = date.today()
            ap = Apartado.objects.create(cliente=cliente, prenda=prendas[0], usuario=vendedor, cantidad=2,
                                         fecha_apartado=hoy, fecha_limite=hoy + timedelta(days=30))
            Pago.objects.create(apartado=ap, monto=220, tipo=Pago.Tipo.ANTICIPO)  # 50% de 2 x 220
            Notificacion.objects.create(apartado=ap, mensaje='Apartado registrado (demo).')
            EntradaMercancia.objects.create(prenda=prendas[1], usuario=gerente, cantidad=8, fecha=hoy)
        self.stdout.write(self.style.SUCCESS('Datos ficticios cargados.'))
