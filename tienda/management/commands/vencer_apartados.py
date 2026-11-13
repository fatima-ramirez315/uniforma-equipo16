from django.core.management.base import BaseCommand

from tienda.services import procesar_vencimientos


class Command(BaseCommand):
    help = "RF-13: vence los apartados con más de 30 días y avisa de los próximos a vencer. Programar a diario (cron)."

    def handle(self, *args, **options):
        vencidos, avisados = procesar_vencimientos()
        self.stdout.write(self.style.SUCCESS(f"{vencidos} vencido(s), {avisados} aviso(s) de próximo vencimiento."))
