# Base de datos de Uniforma (PostgreSQL)

**Procedimiento válido de creación: migraciones de Django.** No existe un esquema SQL
independiente que duplique las tablas.

1. Crear la BD vacía y el usuario: `psql -U postgres -f database/crear_bd.sql`
   (antes cambia la contraseña del archivo y ponla igual en `.env`).
2. Crear las tablas: `python manage.py migrate` (usa `tienda/migrations/0001_initial.py`).
3. Datos ficticios: `python manage.py cargar_datos_demo` (se puede repetir sin duplicar).

Tablas (diseño U2, 7 de dominio): `tienda_cliente`, `tienda_usuario`, `tienda_prenda`,
`tienda_apartado` (FK a cliente, prenda y usuario), `tienda_pago` (FK a apartado),
`tienda_notificacion` (FK a apartado), `tienda_entradamercancia` (FK a prenda y usuario).
Las tablas `auth_*` y `django_*` las crea el propio framework.
