from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Apartado, Cliente, EntradaMercancia, Pago, Perfil, Prenda
from .services import ReglaDeNegocioError


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gerente = User.objects.create_user("gerente", password="x12345678")
        Perfil.objects.create(usuario=cls.gerente, rol=Perfil.GERENTE)
        cls.vendedor = User.objects.create_user("vendedor", password="x12345678")
        Perfil.objects.create(usuario=cls.vendedor, rol=Perfil.VENDEDOR)

        def mk(cod, talla, stock, precio="200.00"):
            return Prenda.objects.create(
                codigo=cod, modelo="Camisa escolar", categoria="ESCOLAR", talla=talla, color="Blanco",
                precio=Decimal(precio), stock=stock, stock_minimo=3,
            )

        cls.ch = mk("ESC-CH", "CH", 10)
        cls.m = mk("ESC-M", "M", 10)
        cls.l = mk("ESC-L", "L", 5)
        cls.xxl = mk("ESC-XXL", "XXL", 0, "220.00")
        cls.rojo_m = Prenda.objects.create(
            codigo="ESC-ROJ-M", modelo="Camisa escolar", categoria="ESCOLAR", talla="M", color="Rojo",
            precio=Decimal("200.00"), stock=7, stock_minimo=3,
        )
        cls.medico = Prenda.objects.create(
            codigo="MED-L", modelo="Pantalón médico", categoria="MEDICO", talla="L", color="Verde",
            precio=Decimal("320.00"), stock=4, stock_minimo=3,
        )
        cls.cliente = Cliente.objects.create(nombre="Ana Pérez", telefono="7771234567")

    # --- ayudas -----------------------------------------------------------
    def pedido(self, lineas=None, anticipo="100.00"):
        """Pedido de mostrador ya confirmado con anticipo."""
        return services.crear_pedido(
            cliente=self.cliente, lineas=lineas or [(self.m, 1)], vendedor=self.vendedor, anticipo=anticipo, metodo="EFECTIVO",
        )

    def solicitud(self, lineas=None):
        """Solicitud hecha por el propio cliente (sin vendedor ni anticipo)."""
        return services.crear_pedido(cliente=self.cliente, lineas=lineas or [(self.m, 2)])

    def stock(self, prenda):
        prenda.refresh_from_db()
        return prenda.stock


# ===========================================================================
class RF01Catalogo(Base):
    def test_catalogo_publico_agrupa_por_modelo_con_sus_tallas(self):
        r = self.client.get(reverse("tienda:catalogo"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["grupos"]), 3)  # camisa blanca, camisa roja y pantalón médico
        self.assertContains(r, "XXL")

    def test_tallas_ordenadas_de_chica_a_grande(self):
        grupo = self.client.get(reverse("tienda:catalogo"), {"modelo": "Camisa escolar", "color": "Blanco"}).context["grupos"][0]
        self.assertEqual([p.talla for p in grupo["prendas"]], ["CH", "M", "L", "XXL"])

    def test_filtros_en_cascada_categoria_modelo_talla(self):
        r = self.client.get(reverse("tienda:catalogo"), {"categoria": "MEDICO"})
        self.assertEqual(r.context["modelos"], ["Pantalón médico"])  # solo los modelos de esa categoría
        self.assertEqual([t for t, _ in r.context["tallas"]], ["L"])  # solo las tallas que existen
        r = self.client.get(reverse("tienda:catalogo"), {"categoria": "ESCOLAR", "modelo": "Camisa escolar", "talla": "CH"})
        self.assertEqual([p.talla for p in r.context["grupos"][0]["prendas"]], ["CH"])

    def test_filtro_de_color_muestra_solo_ese_color(self):
        r = self.client.get(reverse("tienda:catalogo"), {"modelo": "Camisa escolar"})
        self.assertEqual(r.context["colores"], ["Blanco", "Rojo"])  # el modelo existe en varios colores
        r = self.client.get(reverse("tienda:catalogo"), {"modelo": "Camisa escolar", "color": "Blanco"})
        self.assertEqual([g["color"] for g in r.context["grupos"]], ["Blanco"])
        self.assertEqual([t for t, _ in r.context["tallas"]], ["CH", "M", "L", "XXL"])
        r = self.client.get(reverse("tienda:catalogo"), {"modelo": "Camisa escolar", "color": "Rojo"})
        self.assertEqual([t for t, _ in r.context["tallas"]], ["M"])

    def test_el_catalogo_ya_no_tiene_buscador(self):
        self.assertNotContains(self.client.get(reverse("tienda:catalogo")), 'name="q"')

    def test_solo_con_existencia(self):
        r = self.client.get(reverse("tienda:catalogo"), {"modelo": "Camisa escolar", "color": "Blanco", "disponibles": "1"})
        self.assertEqual([p.talla for p in r.context["grupos"][0]["prendas"]], ["CH", "M", "L"])

    def test_orden_de_los_filtros(self):
        html = self.client.get(reverse("tienda:catalogo")).content.decode()
        self.assertLess(html.index('id="categoria"'), html.index('id="modelo"'))
        self.assertLess(html.index('id="modelo"'), html.index('id="color"'))
        self.assertLess(html.index('id="color"'), html.index('id="talla"'))


# ===========================================================================
class PedidoDelCliente(Base):
    """El cliente arma y envía su propio pedido, sin iniciar sesión."""

    def agregar(self, **cants):
        return self.client.post(reverse("tienda:carrito_agregar"), {f"cant_{pk}": n for pk, n in cants.items()})

    def test_pedido_grande_en_varias_tallas(self):
        self.agregar(**{str(self.ch.pk): 20, str(self.m.pk): 30, str(self.l.pk): 200})
        r = self.client.get(reverse("tienda:carrito"))
        self.assertEqual(r.context["piezas"], 250)
        self.assertEqual(r.context["total"], Decimal("50000.00"))
        self.assertEqual(r.context["minimo"], Decimal("25000.00"))
        self.assertEqual(r.context["encargo"], 10 + 20 + 195)  # lo que excede las existencias

    def test_agregar_sin_cantidad_no_agrega_nada(self):
        r = self.agregar(**{str(self.m.pk): ""})
        self.assertEqual(self.client.session.get("carrito", {}), {})
        self.assertEqual(r.status_code, 302)

    def test_el_cliente_envia_su_pedido_sin_login(self):
        self.agregar(**{str(self.ch.pk): 3, str(self.m.pk): 2})
        r = self.client.post(reverse("tienda:carrito"), {
            "accion": "pedir", f"cant_{self.ch.pk}": 3, f"cant_{self.m.pk}": 2,
            "nombre": "Luis Mora", "telefono": "7779998888", "email": "", "notas": "Primaria",
        })
        self.assertRedirects(r, reverse("tienda:pedido_listo"))
        ap = Apartado.objects.get(cliente__telefono="7779998888")
        self.assertEqual(ap.estado, Apartado.SOLICITADO)
        self.assertEqual(ap.origen, Apartado.EN_LINEA)
        self.assertIsNone(ap.vendedor)
        self.assertEqual(ap.items.count(), 2)
        self.assertEqual(ap.total, Decimal("1000.00"))
        self.assertEqual(self.stock(self.ch), 10)  # una solicitud no mueve inventario
        self.assertEqual(self.client.session["carrito"], {})
        self.assertContains(self.client.get(reverse("tienda:pedido_listo")), ap.folio)

    def test_datos_invalidos_no_crean_pedido(self):
        r = self.client.post(reverse("tienda:carrito"), {"accion": "pedir", f"cant_{self.m.pk}": 1, "nombre": "X", "telefono": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Apartado.objects.count(), 0)

    def test_actualizar_y_quitar_prendas_del_pedido(self):
        self.agregar(**{str(self.ch.pk): 3, str(self.m.pk): 2})
        self.client.post(reverse("tienda:carrito"), {"accion": "actualizar", f"cant_{self.ch.pk}": 0, f"cant_{self.m.pk}": 5})
        self.assertEqual(self.client.session["carrito"], {str(self.m.pk): 5})

    def test_el_cliente_ve_el_estado_con_folio_y_telefono(self):
        ap = self.solicitud()
        r = self.client.get(reverse("tienda:seguimiento"), {"folio": ap.folio, "telefono": "777-123-4567"})
        self.assertContains(r, "mostrador")
        self.assertContains(r, "Camisa escolar")


# ===========================================================================
class RF02a03a09Apartados(Base):
    def test_pedido_de_mostrador_con_varias_tallas_descuenta_stock(self):
        ap = self.pedido([(self.ch, 2), (self.m, 3), (self.l, 1)], anticipo="600.00")  # total 1200, mínimo 600
        self.assertEqual((self.stock(self.ch), self.stock(self.m), self.stock(self.l)), (8, 7, 4))  # RF-09
        self.assertEqual(ap.total, Decimal("1200.00"))
        self.assertEqual(ap.saldo, Decimal("600.00"))
        self.assertEqual(ap.estado, Apartado.ACTIVO)
        self.assertEqual(ap.origen, Apartado.MOSTRADOR)
        self.assertEqual(ap.items.count(), 3)
        self.assertEqual(ap.piezas, 6)
        self.assertEqual(ap.folio, f"APT-{ap.pk:05d}")
        self.assertEqual(ap.pagos.get().tipo, Pago.ANTICIPO)

    def test_anticipo_menor_al_50_rechazado(self):
        with self.assertRaises(ReglaDeNegocioError):
            self.pedido([(self.m, 1)], anticipo="99.99")
        self.assertEqual(self.stock(self.m), 10)
        self.assertEqual(Apartado.objects.count(), 0)

    def test_pedido_vacio_rechazado(self):
        with self.assertRaises(ReglaDeNegocioError):
            services.crear_pedido(cliente=self.cliente, lineas=[(self.m, 0)])

    def test_abono_y_liquidacion(self):
        ap = self.pedido()
        services.registrar_pago(apartado=ap, monto="40", metodo="TARJETA", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.saldo, Decimal("60.00"))
        services.registrar_pago(apartado=ap, monto="60", metodo="EFECTIVO", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.PAGADO)
        self.assertTrue(ap.notificaciones.filter(tipo="LISTO").exists())

    def test_pago_mayor_al_saldo_rechazado(self):
        ap = self.pedido()
        with self.assertRaises(ReglaDeNegocioError):
            services.registrar_pago(apartado=ap, monto="100.01", metodo="EFECTIVO", usuario=self.vendedor)

    def test_entrega_solo_si_liquidado(self):
        ap = self.pedido()
        with self.assertRaises(ReglaDeNegocioError):
            services.entregar_apartado(apartado=ap, usuario=self.vendedor)
        services.registrar_pago(apartado=ap, monto="100", metodo="EFECTIVO", usuario=self.vendedor)
        services.entregar_apartado(apartado=ap, usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ENTREGADO)


class RF08PedidoGrandeYPorEncargo(Base):
    def test_lo_que_excede_el_stock_queda_por_encargo(self):
        ap = self.pedido([(self.l, 8), (self.xxl, 3)], anticipo="1130.00")  # 8x200 + 3x220 = 2260
        self.assertEqual(self.stock(self.l), 0)  # se apartó todo lo que había (5)
        self.assertEqual(self.stock(self.xxl), 0)
        l = ap.items.get(prenda=self.l)
        self.assertEqual((l.cantidad, l.de_inventario, l.por_encargo), (8, 5, 3))
        x = ap.items.get(prenda=self.xxl)
        self.assertEqual((x.de_inventario, x.por_encargo), (0, 3))
        self.assertEqual(ap.por_encargo, 6)

    def test_pedido_de_500_piezas_en_varias_tallas(self):
        ap = self.pedido([(self.ch, 20), (self.m, 30), (self.l, 200), (self.xxl, 3)], anticipo="26330.00")
        self.assertEqual(ap.piezas, 253)
        self.assertEqual(ap.total, Decimal("50660.00"))
        self.assertEqual(self.stock(self.ch), 0)

    def test_cancelar_devuelve_solo_lo_que_se_aparto(self):
        ap = self.pedido([(self.l, 8)], anticipo="800.00")
        services.cancelar_apartado(apartado=ap, motivo="Ya no lo necesita", usuario=self.vendedor)
        self.assertEqual(self.stock(self.l), 5)  # regresan 5, no 8


class ConfirmarSolicitud(Base):
    def test_el_vendedor_confirma_con_anticipo_y_se_aparta_el_inventario(self):
        ap = self.solicitud([(self.m, 2), (self.l, 1)])  # total 600
        self.assertEqual(self.stock(self.m), 10)
        with self.assertRaises(ReglaDeNegocioError):
            services.confirmar_solicitud(apartado=ap, anticipo="299.99", metodo="EFECTIVO", usuario=self.vendedor)
        services.confirmar_solicitud(apartado=ap, anticipo="300.00", metodo="EFECTIVO", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ACTIVO)
        self.assertEqual(ap.vendedor, self.vendedor)
        self.assertEqual((self.stock(self.m), self.stock(self.l)), (8, 4))
        with self.assertRaises(ReglaDeNegocioError):  # no se confirma dos veces
            services.confirmar_solicitud(apartado=ap, anticipo="300.00", metodo="EFECTIVO", usuario=self.vendedor)

    def test_rechazar_solicitud_no_toca_el_inventario(self):
        ap = self.solicitud()
        services.cancelar_apartado(apartado=ap, motivo="No se presentó", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.CANCELADO)
        self.assertEqual(self.stock(self.m), 10)

    def test_solicitud_vencida_a_los_7_dias_no_devuelve_stock(self):
        ap = self.solicitud()
        v, _ = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=8))
        ap.refresh_from_db()
        self.assertEqual((v, ap.estado), (1, Apartado.VENCIDO))
        self.assertEqual(self.stock(self.m), 10)

    def test_pantalla_de_confirmacion_del_vendedor(self):
        ap = self.solicitud([(self.m, 2)])  # 400, mínimo 200
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse("tienda:apartado_detalle", args=[ap.pk])), "Confirmar con anticipo")
        self.client.post(reverse("tienda:apartado_confirmar", args=[ap.pk]), {"anticipo": "200.00", "metodo": "EFECTIVO"})
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ACTIVO)


class BandejaDePedidos(Base):
    def test_el_vendedor_ve_todos_los_pedidos_y_las_solicitudes_en_linea(self):
        a = self.pedido()
        b = self.solicitud()
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse("tienda:apartados"))
        self.assertContains(r, a.folio)
        self.assertContains(r, b.folio)
        self.assertEqual(r.context["n_solicitudes"], 1)
        r = self.client.get(reverse("tienda:apartados"), {"estado": "SOLICITADO"})
        self.assertContains(r, b.folio)
        self.assertNotContains(r, a.folio)
        self.assertContains(self.client.get(reverse("tienda:apartados"), {"origen": "EN_LINEA"}), b.folio)

    def test_la_bandeja_exige_login(self):
        self.assertEqual(self.client.get(reverse("tienda:apartados")).status_code, 302)

    def test_el_vendedor_arma_pedido_con_el_mismo_carrito(self):
        self.client.force_login(self.vendedor)
        self.client.post(reverse("tienda:carrito_agregar"), {f"cant_{self.ch.pk}": 2, f"cant_{self.m.pk}": 2})
        r = self.client.post(reverse("tienda:carrito"), {
            "accion": "pedir", f"cant_{self.ch.pk}": 2, f"cant_{self.m.pk}": 2,
            "nombre": "Marta Díaz", "telefono": "7775550000", "email": "", "notas": "", "anticipo": "400.00", "metodo": "EFECTIVO",
        })
        ap = Apartado.objects.get(cliente__telefono="7775550000")
        self.assertRedirects(r, reverse("tienda:apartado_detalle", args=[ap.pk]))
        self.assertEqual((ap.estado, ap.origen), (Apartado.ACTIVO, Apartado.MOSTRADOR))
        self.assertEqual(self.stock(self.ch), 8)


# ===========================================================================
class RF04Notificaciones(Base):
    def test_avisos_de_solicitud_y_confirmacion(self):
        ap = self.solicitud()
        self.assertTrue(ap.notificaciones.filter(tipo="SOLICITUD").exists())
        services.confirmar_solicitud(apartado=ap, anticipo="200.00", metodo="EFECTIVO", usuario=self.vendedor)
        n = ap.notificaciones.get(tipo="CONFIRMACION")
        self.assertIn(ap.folio, n.mensaje)
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse("tienda:notificaciones")), ap.folio)
        self.client.post(reverse("tienda:notificacion_atendida", args=[n.pk]))
        n.refresh_from_db()
        self.assertTrue(n.atendida)

    def test_mensaje_de_pedido_grande_cabe_en_el_aviso(self):
        ap = self.pedido([(self.ch, 20), (self.m, 30), (self.l, 200)], anticipo="25000.00")
        self.assertLessEqual(len(ap.notificaciones.get(tipo="CONFIRMACION").mensaje), 300)


class RF05Seguimiento(Base):
    def test_cliente_consulta_con_folio_y_telefono(self):
        ap = self.pedido()
        r = self.client.get(reverse("tienda:seguimiento"), {"folio": ap.folio.lower(), "telefono": "777-123-4567"})
        self.assertContains(r, ap.folio)
        self.assertContains(r, "Saldo pendiente")
        self.assertContains(r, "Tus prendas")

    def test_telefono_incorrecto_no_muestra_nada(self):
        ap = self.pedido()
        self.assertContains(self.client.get(reverse("tienda:seguimiento"), {"folio": ap.folio, "telefono": "7770000000"}), "No encontramos")


class RF06Cancelar(Base):
    def test_cancelar_devuelve_stock_y_exige_motivo(self):
        ap = self.pedido([(self.m, 2)], anticipo="200")
        with self.assertRaises(ReglaDeNegocioError):
            services.cancelar_apartado(apartado=ap, motivo=" ", usuario=self.vendedor)
        services.cancelar_apartado(apartado=ap, motivo="Cliente desistió", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.CANCELADO)
        self.assertEqual(self.stock(self.m), 10)
        with self.assertRaises(ReglaDeNegocioError):
            services.cancelar_apartado(apartado=ap, motivo="otra vez", usuario=self.vendedor)


# ===========================================================================
class RF10a14Inventario(Base):
    def test_gerente_crea_y_edita_prenda_con_talla_del_catalogo(self):
        self.client.force_login(self.gerente)
        datos = {"codigo": "dep-001", "modelo": "Playera deportiva", "categoria": "DEPORTIVO", "talla": "XL", "color": "Azul",
                 "precio": "150.00", "stock": 5, "stock_minimo": 2, "activa": "on"}
        self.assertRedirects(self.client.post(reverse("tienda:prenda_nueva"), datos), reverse("tienda:prendas"))
        p = Prenda.objects.get(codigo="DEP-001")
        datos["precio"] = "175.00"
        self.client.post(reverse("tienda:prenda_editar", args=[p.pk]), datos)
        p.refresh_from_db()
        self.assertEqual(p.precio, Decimal("175.00"))

    def test_talla_fuera_del_catalogo_se_rechaza(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("tienda:prenda_nueva"), {"codigo": "X-1", "modelo": "X", "categoria": "OTRO", "talla": "28",
                                                              "color": "Gris", "precio": "10", "stock": 1, "stock_minimo": 1, "activa": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Prenda.objects.filter(codigo="X-1").exists())

    def test_vendedor_no_puede_editar_prendas(self):
        self.client.force_login(self.vendedor)
        self.assertRedirects(self.client.get(reverse("tienda:prenda_nueva")), reverse("tienda:panel"))

    def test_alerta_stock_bajo(self):
        Prenda.objects.filter(pk=self.l.pk).update(stock=2)
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse("tienda:prendas"), {"bajo": "1"}), "Camisa escolar")
        self.assertContains(self.client.get(reverse("tienda:panel")), "Camisa escolar")


class RF11Clientes(Base):
    def test_alta_y_busqueda_de_clientes(self):
        self.client.force_login(self.vendedor)
        r = self.client.post(reverse("tienda:cliente_nuevo"), {"nombre": "Luis Mora", "telefono": "7779998888", "email": ""})
        self.assertRedirects(r, reverse("tienda:clientes"))
        self.assertContains(self.client.get(reverse("tienda:clientes"), {"q": "Mora"}), "Luis Mora")

    def test_telefono_invalido_o_duplicado(self):
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.post(reverse("tienda:cliente_nuevo"), {"nombre": "X", "telefono": "123", "email": ""}).status_code, 200)
        self.assertEqual(self.client.post(reverse("tienda:cliente_nuevo"), {"nombre": "Y", "telefono": "7771234567", "email": ""}).status_code, 200)
        self.assertEqual(Cliente.objects.count(), 1)


class RF12Roles(Base):
    def test_rutas_internas_exigen_login(self):
        for name in ["panel", "apartados", "clientes", "prendas", "notificaciones", "entradas", "reportes"]:
            r = self.client.get(reverse(f"tienda:{name}"))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/ingresar/", r["Location"])

    def test_catalogo_y_pedido_son_publicos(self):
        for name in ["catalogo", "carrito", "seguimiento"]:
            self.assertEqual(self.client.get(reverse(f"tienda:{name}")).status_code, 200, name)

    def test_vendedor_no_ve_reportes_ni_entradas(self):
        self.client.force_login(self.vendedor)
        for name in ["reportes", "entradas"]:
            self.assertRedirects(self.client.get(reverse(f"tienda:{name}")), reverse("tienda:panel"))

    def test_login_y_logout(self):
        self.assertRedirects(self.client.post(reverse("tienda:login"), {"username": "gerente", "password": "x12345678"}), reverse("tienda:panel"))
        self.client.post(reverse("tienda:logout"))
        self.assertEqual(self.client.get(reverse("tienda:panel")).status_code, 302)


class RF13Vencimientos(Base):
    def test_vence_a_los_30_dias_y_devuelve_stock(self):
        ap = self.pedido([(self.m, 2), (self.l, 1)], anticipo="300")
        self.assertAlmostEqual((ap.vence - ap.creado).days, 30, delta=1)
        v, _ = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=31))
        ap.refresh_from_db()
        self.assertEqual((v, ap.estado), (1, Apartado.VENCIDO))
        self.assertEqual((self.stock(self.m), self.stock(self.l)), (10, 5))
        self.assertTrue(ap.notificaciones.filter(tipo="VENCIDO").exists())

    def test_aviso_previo_una_sola_vez(self):
        ap = self.pedido()
        _, a1 = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=26))
        _, a2 = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=26))
        self.assertEqual((a1, a2), (1, 0))
        self.assertEqual(ap.notificaciones.filter(tipo="POR_VENCER").count(), 1)

    def test_liquidado_no_vence(self):
        ap = self.pedido(anticipo="200")
        services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=40))
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.PAGADO)

    def test_boton_del_gerente(self):
        self.client.force_login(self.gerente)
        self.assertRedirects(self.client.post(reverse("tienda:procesar_vencimientos")), reverse("tienda:panel"))


class RF15Reportes(Base):
    def test_reportes_del_gerente(self):
        self.pedido([(self.m, 2), (self.l, 1)], anticipo="300")
        self.client.force_login(self.gerente)
        r = self.client.get(reverse("tienda:reportes"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Camisa escolar")
        self.assertContains(r, "Pagos recibidos")


class RF16Entradas(Base):
    def test_entrada_sube_stock_y_avisa_a_quien_esperaba_por_encargo(self):
        ap = self.pedido([(self.xxl, 3)], anticipo="330.00")  # XXL sin existencia: 3 por encargo
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("tienda:entradas"), {"prenda": self.xxl.pk, "cantidad": 12, "proveedor": "Textiles SA", "remision": "R-77"})
        self.assertRedirects(r, reverse("tienda:entradas"))
        self.assertEqual(self.stock(self.xxl), 12)
        self.assertEqual(EntradaMercancia.objects.count(), 1)
        self.assertTrue(ap.notificaciones.filter(tipo="LLEGO_PEDIDO").exists())


class FlujoWeb(Base):
    def test_todas_las_pantallas_responden(self):
        ap = self.pedido()
        sol = self.solicitud()
        self.client.force_login(self.gerente)
        self.client.post(reverse("tienda:carrito_agregar"), {f"cant_{self.m.pk}": 2})
        urls = [
            reverse("tienda:catalogo"), reverse("tienda:seguimiento"), reverse("tienda:carrito"), reverse("tienda:panel"),
            reverse("tienda:prendas"), reverse("tienda:prenda_nueva"), reverse("tienda:entradas"), reverse("tienda:clientes"),
            reverse("tienda:cliente_nuevo"), reverse("tienda:apartados"), reverse("tienda:apartado_detalle", args=[ap.pk]),
            reverse("tienda:apartado_detalle", args=[sol.pk]), reverse("tienda:notificaciones"), reverse("tienda:reportes"),
        ]
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 200, u)
        self.assertRedirects(self.client.get(reverse("tienda:apartado_nuevo")), reverse("tienda:catalogo"))

    def test_flujo_completo_pagar_y_entregar_desde_la_web(self):
        self.client.force_login(self.vendedor)
        ap = self.pedido(anticipo="100.00")
        self.client.post(reverse("tienda:apartado_pago", args=[ap.pk]), {"monto": "100.00", "metodo": "EFECTIVO"})
        self.client.post(reverse("tienda:apartado_entregar", args=[ap.pk]))
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ENTREGADO)


# ===========================================================================
class DatosDeDemostracion(TestCase):
    def test_catalogo_completo_con_varios_colores_y_es_repetible(self):
        from tienda import demo

        n = demo.cargar_catalogo()
        self.assertGreater(n, 100)
        self.assertEqual(demo.cargar_catalogo(), 0)  # repetirlo no duplica nada
        camisa = Prenda.objects.filter(modelo="Camisa escolar manga corta")
        self.assertEqual(set(camisa.values_list("color", flat=True)), {"Blanco", "Azul cielo", "Beige"})
        self.assertEqual(camisa.filter(color="Blanco").count(), 6)  # XS a XXL

    def test_autoseed_solo_con_la_variable_activada(self):
        import os
        from unittest import mock
        from tienda import demo

        with mock.patch.dict(os.environ, {"AUTOSEED_DEMO": "0"}):
            demo.autoseed()
        self.assertEqual(Prenda.objects.count(), 0)
        with mock.patch.dict(os.environ, {"AUTOSEED_DEMO": "1", "DEMO_GERENTE_PASSWORD": "Abc12345!x", "DEMO_VENDEDOR_PASSWORD": "Def12345!x"}):
            demo.autoseed()
        self.assertGreater(Prenda.objects.count(), 100)
        self.assertTrue(User.objects.filter(username="gerente").exists())
