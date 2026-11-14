# Uniforma — Sistema de apartados e inventario (Equipo 16)

Aplicación web para la tienda de uniformes "Uniforma": consulta de disponibilidad, apartados y pedidos
especiales con anticipo del 50 %, pagos/abonos, avisos al cliente, vencimiento a 30 días, inventario,
entradas de mercancía y reportes. Stack: **Django 5.2 + PostgreSQL** (HTML/CSS sin frameworks).

## Requisitos
Python 3.11+ y PostgreSQL 14+.

## Instalación
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Base de datos (sin contraseñas en el código)
```sql
CREATE USER uniforma WITH PASSWORD 'tu-contraseña';
CREATE DATABASE uniforma_db OWNER uniforma;
```
Copia `.env.example` a `.env` y escribe tu contraseña en `DB_PASSWORD`. `config/settings.py` lee todo
desde variables de entorno / `.env` (ignorado por git). Para una prueba rápida sin PostgreSQL: `DB_ENGINE=sqlite`.

## Ejecución
```bash
python manage.py migrate
python manage.py seed_demo      # crea usuarios gerente/vendedor (contraseñas aleatorias que imprime), catálogo y apartados
python manage.py runserver      # http://127.0.0.1:8000
```

## Pruebas
```bash
python manage.py test           # 50 pruebas que cubren RF-01 a RF-16 y el pedido en línea
```

## Cómo se usa
- **Cliente (sin cuenta):** Catálogo → filtra por categoría, modelo y talla → escribe cuántas piezas quiere de cada talla → «Agregar al pedido» → «Mi pedido» → envía sus datos. Recibe un folio y puede dar seguimiento en «Mi apartado» con folio + teléfono.
- **Vendedor:** el menú **Pedidos** muestra todos los pedidos (mostrador y en línea; la pestaña «Solicitud en línea» son los que esperan anticipo). Al recibir el anticipo del 50 % abre la solicitud y pulsa «Confirmar con anticipo»: se aparta el inventario. También puede armar un pedido en mostrador desde el mismo catálogo.
- Si el cliente pide más piezas de las que hay en existencia (pedidos grandes), lo que sobra queda **por encargo** al proveedor y se avisa al registrar la entrada de mercancía.
- Tallas: XS, CH, M, L, XL, XXL.

Si ya tenías una base de datos de una versión anterior, `python manage.py migrate` convierte tus apartados al formato nuevo; para empezar limpio borra `db.sqlite3` (o recrea la base en PostgreSQL), y vuelve a correr `migrate` y `seed_demo`.

## Vencimientos automáticos (RF-13)
`python manage.py vencer_apartados` (programable con cron) o el botón "Revisar vencimientos" del gerente.

## Estructura
- `tienda/models.py` modelos · `tienda/services.py` reglas de negocio (transacciones) · `tienda/views.py` vistas
- `tienda/permisos.py` roles Vendedor/Gerente · `templates/` pantallas · `tienda/tests.py` pruebas
