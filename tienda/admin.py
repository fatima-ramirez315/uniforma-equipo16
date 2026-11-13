from django.contrib import admin

from .models import Apartado, Cliente, EntradaMercancia, Notificacion, Pago, Perfil, Prenda


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "rol")


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "telefono", "email")
    search_fields = ("nombre", "telefono")


@admin.register(Prenda)
class PrendaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "modelo", "talla", "color", "precio", "stock", "stock_minimo", "activa")
    list_filter = ("categoria", "activa")
    search_fields = ("codigo", "modelo")


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0


@admin.register(Apartado)
class ApartadoAdmin(admin.ModelAdmin):
    list_display = ("folio", "cliente", "prenda", "tipo", "estado", "total", "vence")
    list_filter = ("estado", "tipo")
    search_fields = ("folio", "cliente__nombre")
    inlines = [PagoInline]


admin.site.register(Notificacion)
admin.site.register(EntradaMercancia)
