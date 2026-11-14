from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "tienda"

urlpatterns = [
    # Públicas
    path("", views.catalogo, name="catalogo"),
    path("seguimiento/", views.seguimiento, name="seguimiento"),
    path("pedido/agregar/", views.carrito_agregar, name="carrito_agregar"),
    path("pedido/", views.carrito, name="carrito"),
    path("pedido/enviado/", views.pedido_listo, name="pedido_listo"),
    path("ingresar/", views.IngresarView.as_view(), name="login"),
    path("salir/", LogoutView.as_view(), name="logout"),
    # Panel interno
    path("panel/", views.panel, name="panel"),
    path("prendas/", views.prendas, name="prendas"),
    path("prendas/nueva/", views.prenda_form, name="prenda_nueva"),
    path("prendas/<int:pk>/editar/", views.prenda_form, name="prenda_editar"),
    path("entradas/", views.entradas, name="entradas"),
    path("clientes/", views.clientes, name="clientes"),
    path("clientes/nuevo/", views.cliente_form, name="cliente_nuevo"),
    path("clientes/<int:pk>/editar/", views.cliente_form, name="cliente_editar"),
    path("apartados/", views.apartados, name="apartados"),
    path("apartados/nuevo/", views.apartado_nuevo, name="apartado_nuevo"),
    path("apartados/<int:pk>/", views.apartado_detalle, name="apartado_detalle"),
    path("apartados/<int:pk>/confirmar/", views.apartado_confirmar, name="apartado_confirmar"),
    path("apartados/<int:pk>/pago/", views.apartado_pago, name="apartado_pago"),
    path("apartados/<int:pk>/entregar/", views.apartado_entregar, name="apartado_entregar"),
    path("apartados/<int:pk>/cancelar/", views.apartado_cancelar, name="apartado_cancelar"),
    path("avisos/", views.notificaciones, name="notificaciones"),
    path("avisos/<int:pk>/atendida/", views.notificacion_atendida, name="notificacion_atendida"),
    path("vencimientos/", views.procesar_vencimientos, name="procesar_vencimientos"),
    path("reportes/", views.reportes, name="reportes"),
]
