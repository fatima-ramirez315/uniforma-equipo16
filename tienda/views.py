from django.shortcuts import render

from .models import (Apartado, Cliente, EntradaMercancia, Notificacion, Pago,
                     Prenda, Usuario)


def conexion(request):
    """Vista técnica de E1: consulta la BD PostgreSQL mediante el ORM."""
    conteos = [
        (m._meta.db_table, m.objects.count())
        for m in (Cliente, Usuario, Prenda, Apartado, Pago, Notificacion, EntradaMercancia)
    ]
    prendas = Prenda.objects.order_by('modelo', 'talla')
    return render(request, 'tienda/conexion.html', {'conteos': conteos, 'prendas': prendas})
