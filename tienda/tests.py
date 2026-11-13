from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Apartado, Cliente, EntradaMercancia, Notificacion, Pago, Perfil, Prenda
from .services import ReglaDeNegocioError


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gerente = User.objects.create_user("gerente", password="x12345678")
        Perfil.objects.create(usuario=cls.gerente, rol=Perfil.GERENTE)
        cls.vendedor = User.objects.create_user("vendedor", password="x12345678")
        Perfil.objects.create(usuario=cls.vendedor, rol=Perfil.VENDEDOR)
        cls.prenda = Prenda.objects.create(
            codigo="ESC-001", modelo="Camisa escolar", talla="M", color="Blanco", precio=Decimal("200.00"), stock=10, stock_minimo=3
        )
        cls.cliente = Cliente.objects.create(nombre="Ana Pérez", telefono="7771234567")

    def apartado(self, cantidad=1, anticipo="100.00", tipo=Apartado.INVENTARIO):
        return services.crear_apartado(
            cliente=self.cliente, prenda=self.prenda, cantidad=cantidad, anticipo=anticipo,
            metodo="EFECTIVO", vendedor=self.vendedor, tipo=tipo,
        )


class RF01Catalogo(Base):
    def test_catalogo_publico_y_filtros(self):
        r = self.client.get(reverse("tienda:catalogo"))
        self.assertContains(r, "Camisa escolar")
        self.assertContains(self.client.get(reverse("tienda:catalogo"), {"q": "camisa", "talla": "m", "disponibles": "1"}), "Camisa escolar")
        self.assertNotContains(self.client.get(reverse("tienda:catalogo"), {"talla": "XL"}), "Camisa escolar")

    def test_sin_stock_no_sale_en_disponibles(self):
        Prenda.objects.filter(pk=self.prenda.pk).update(stock=0)
        self.assertNotContains(self.client.get(reverse("tienda:catalogo"), {"disponibles": "1"}), "Camisa escolar")


class RF02a03a09Apartados(Base):
    def test_crear_apartado_descuenta_stock_y_registra_anticipo(self):
        ap = self.apartado(cantidad=2, anticipo="200.00")  # total 400, mínimo 200
        self.prenda.refresh_from_db()
        self.assertEqual(self.prenda.stock, 8)  # RF-09
        self.assertEqual(ap.total, Decimal("400.00"))
        self.assertEqual(ap.saldo, Decimal("200.00"))
        self.assertEqual(ap.estado, Apartado.ACTIVO)
        self.assertEqual(ap.folio, f"APT-{ap.pk:05d}")
        self.assertEqual(ap.pagos.get().tipo, Pago.ANTICIPO)

    def test_anticipo_menor_al_50_rechazado(self):
        with self.assertRaises(ReglaDeNegocioError):
            self.apartado(cantidad=1, anticipo="99.99")
        self.prenda.refresh_from_db()
        self.assertEqual(self.prenda.stock, 10)
        self.assertEqual(Apartado.objects.count(), 0)

    def test_no_se_aparta_mas_que_el_stock(self):
        with self.assertRaises(ReglaDeNegocioError):
            self.apartado(cantidad=11, anticipo="1100.00")

    def test_abono_y_liquidacion(self):
        ap = self.apartado()
        services.registrar_pago(apartado=ap, monto="40", metodo="TARJETA", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.saldo, Decimal("60.00"))
        self.assertEqual(ap.estado, Apartado.ACTIVO)
        services.registrar_pago(apartado=ap, monto="60", metodo="EFECTIVO", usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.PAGADO)
        self.assertTrue(ap.notificaciones.filter(tipo="LISTO").exists())

    def test_pago_mayor_al_saldo_rechazado(self):
        ap = self.apartado()
        with self.assertRaises(ReglaDeNegocioError):
            services.registrar_pago(apartado=ap, monto="100.01", metodo="EFECTIVO", usuario=self.vendedor)

    def test_entrega_solo_si_liquidado(self):
        ap = self.apartado()
        with self.assertRaises(ReglaDeNegocioError):
            services.entregar_apartado(apartado=ap, usuario=self.vendedor)
        services.registrar_pago(apartado=ap, monto="100", metodo="EFECTIVO", usuario=self.vendedor)
        services.entregar_apartado(apartado=ap, usuario=self.vendedor)
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ENTREGADO)


class RF04Notificaciones(Base):
    def test_confirmacion_al_crear_y_marcar_atendida(self):
        ap = self.apartado()
        n = ap.notificaciones.get(tipo="CONFIRMACION")
        self.assertIn(ap.folio, n.mensaje)
        self.client.force_login(self.vendedor)
        self.assertContains(self.client.get(reverse("tienda:notificaciones")), ap.folio)
        self.client.post(reverse("tienda:notificacion_atendida", args=[n.pk]))
        n.refresh_from_db()
        self.assertTrue(n.atendida)


class RF05Seguimiento(Base):
    def test_cliente_consulta_con_folio_y_telefono(self):
        ap = self.apartado()
        r = self.client.get(reverse("tienda:seguimiento"), {"folio": ap.folio.lower(), "telefono": "777-123-4567"})
        self.assertContains(r, ap.folio)
        self.assertContains(r, "Saldo pendiente")

    def test_telefono_incorrecto_no_muestra_nada(self):
        ap = self.apartado()
        r = self.client.get(reverse("tienda:seguimiento"), {"folio": ap.folio, "telefono": "7770000000"})
        self.assertContains(r, "No encontramos")


class RF06Cancelar(Base):
    def test_cancelar_devuelve_stock_y_exige_motivo(self):
        ap = self.apartado(cantidad=2, anticipo="200")
        with self.assertRaises(ReglaDeNegocioError):
            services.cancelar_apartado(apartado=ap, motivo=" ", usuario=self.vendedor)
        services.cancelar_apartado(apartado=ap, motivo="Cliente desistió", usuario=self.vendedor)
        ap.refresh_from_db()
        self.prenda.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.CANCELADO)
        self.assertEqual(self.prenda.stock, 10)
        with self.assertRaises(ReglaDeNegocioError):
            services.cancelar_apartado(apartado=ap, motivo="otra vez", usuario=self.vendedor)


class RF08PedidoEspecial(Base):
    def test_pedido_especial_sin_stock_no_descuenta(self):
        Prenda.objects.filter(pk=self.prenda.pk).update(stock=0)
        ap = self.apartado(cantidad=3, anticipo="300", tipo=Apartado.ESPECIAL)
        self.prenda.refresh_from_db()
        self.assertEqual(self.prenda.stock, 0)
        self.assertEqual(ap.tipo, Apartado.ESPECIAL)


class RF10a14Inventario(Base):
    def test_gerente_crea_y_edita_prenda(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("tienda:prenda_nueva"), {
            "codigo": "dep-001", "modelo": "Playera deportiva", "categoria": "DEPORTIVO", "talla": "l", "color": "Azul",
            "precio": "150.00", "stock": 5, "stock_minimo": 2, "activa": "on",
        })
        self.assertRedirects(r, reverse("tienda:prendas"))
        p = Prenda.objects.get(codigo="DEP-001")
        self.assertEqual(p.talla, "L")
        r = self.client.post(reverse("tienda:prenda_editar", args=[p.pk]), {
            "codigo": "DEP-001", "modelo": "Playera deportiva", "categoria": "DEPORTIVO", "talla": "L", "color": "Azul",
            "precio": "175.00", "stock": 5, "stock_minimo": 2, "activa": "on",
        })
        p.refresh_from_db()
        self.assertEqual(p.precio, Decimal("175.00"))

    def test_vendedor_no_puede_editar_prendas(self):
        self.client.force_login(self.vendedor)
        r = self.client.get(reverse("tienda:prenda_nueva"))
        self.assertRedirects(r, reverse("tienda:panel"))

    def test_alerta_stock_bajo(self):
        Prenda.objects.filter(pk=self.prenda.pk).update(stock=2)
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
        r = self.client.post(reverse("tienda:cliente_nuevo"), {"nombre": "X", "telefono": "123", "email": ""})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("tienda:cliente_nuevo"), {"nombre": "Y", "telefono": "7771234567", "email": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Cliente.objects.count(), 1)


class RF12Roles(Base):
    def test_rutas_internas_exigen_login(self):
        for name in ["panel", "apartados", "clientes", "prendas", "notificaciones", "entradas", "reportes"]:
            r = self.client.get(reverse(f"tienda:{name}"))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/ingresar/", r["Location"])

    def test_vendedor_no_ve_reportes_ni_entradas(self):
        self.client.force_login(self.vendedor)
        for name in ["reportes", "entradas"]:
            self.assertRedirects(self.client.get(reverse(f"tienda:{name}")), reverse("tienda:panel"))

    def test_login_y_logout(self):
        r = self.client.post(reverse("tienda:login"), {"username": "gerente", "password": "x12345678"})
        self.assertRedirects(r, reverse("tienda:panel"))
        self.client.post(reverse("tienda:logout"))
        self.assertEqual(self.client.get(reverse("tienda:panel")).status_code, 302)


class RF13Vencimientos(Base):
    def test_vence_a_los_30_dias_y_devuelve_stock(self):
        ap = self.apartado(cantidad=2, anticipo="200")
        self.assertAlmostEqual((ap.vence - ap.creado).days, 30, delta=1)
        v, _ = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=31))
        ap.refresh_from_db()
        self.prenda.refresh_from_db()
        self.assertEqual(v, 1)
        self.assertEqual(ap.estado, Apartado.VENCIDO)
        self.assertEqual(self.prenda.stock, 10)
        self.assertTrue(ap.notificaciones.filter(tipo="VENCIDO").exists())

    def test_aviso_previo_una_sola_vez(self):
        ap = self.apartado()
        _, a1 = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=26))
        _, a2 = services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=26))
        self.assertEqual((a1, a2), (1, 0))
        self.assertEqual(ap.notificaciones.filter(tipo="POR_VENCER").count(), 1)

    def test_liquidado_no_vence(self):
        ap = self.apartado(anticipo="200")
        services.procesar_vencimientos(ahora=timezone.now() + timedelta(days=40))
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.PAGADO)

    def test_boton_del_gerente(self):
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("tienda:procesar_vencimientos"))
        self.assertRedirects(r, reverse("tienda:panel"))


class RF15Reportes(Base):
    def test_reportes_del_gerente(self):
        self.apartado(cantidad=2, anticipo="200")
        self.client.force_login(self.gerente)
        r = self.client.get(reverse("tienda:reportes"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Camisa escolar")
        self.assertContains(r, "Pagos recibidos")


class RF16Entradas(Base):
    def test_entrada_sube_stock_y_avisa_pedido_especial(self):
        Prenda.objects.filter(pk=self.prenda.pk).update(stock=0)
        ap = self.apartado(cantidad=1, anticipo="100", tipo=Apartado.ESPECIAL)
        self.client.force_login(self.gerente)
        r = self.client.post(reverse("tienda:entradas"), {
            "prenda": self.prenda.pk, "cantidad": 12, "proveedor": "Textiles SA", "remision": "R-77",
        })
        self.assertRedirects(r, reverse("tienda:entradas"))
        self.prenda.refresh_from_db()
        self.assertEqual(self.prenda.stock, 12)
        self.assertEqual(EntradaMercancia.objects.count(), 1)
        self.assertTrue(ap.notificaciones.filter(tipo="LLEGO_PEDIDO").exists())


class FlujoWeb(Base):
    """Recorre las pantallas internas con el navegador de pruebas: ninguna debe dar error."""

    def test_todas_las_pantallas_responden(self):
        ap = self.apartado()
        self.client.force_login(self.gerente)
        urls = [
            reverse("tienda:catalogo"), reverse("tienda:seguimiento"), reverse("tienda:panel"), reverse("tienda:prendas"),
            reverse("tienda:prenda_nueva"), reverse("tienda:entradas"), reverse("tienda:clientes"), reverse("tienda:cliente_nuevo"),
            reverse("tienda:apartados"), reverse("tienda:apartado_nuevo"), reverse("tienda:apartado_detalle", args=[ap.pk]),
            reverse("tienda:notificaciones"), reverse("tienda:reportes"),
        ]
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_crear_apartado_desde_el_formulario_y_pagar(self):
        self.client.force_login(self.vendedor)
        r = self.client.post(reverse("tienda:apartado_nuevo"), {
            "nombre": "Marta Díaz", "telefono": "7775550000", "email": "", "prenda": self.prenda.pk, "cantidad": 1,
            "tipo": "INVENTARIO", "anticipo": "100.00", "metodo": "EFECTIVO", "notas": "",
        })
        ap = Apartado.objects.get(cliente__telefono="7775550000")
        self.assertRedirects(r, reverse("tienda:apartado_detalle", args=[ap.pk]))
        self.client.post(reverse("tienda:apartado_pago", args=[ap.pk]), {"monto": "100.00", "metodo": "EFECTIVO"})
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.PAGADO)
        self.client.post(reverse("tienda:apartado_entregar", args=[ap.pk]))
        ap.refresh_from_db()
        self.assertEqual(ap.estado, Apartado.ENTREGADO)
