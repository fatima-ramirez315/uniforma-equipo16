# Uniforma — Sistema de apartados e inventario de uniformes

**Materia:** Ingeniería de Software (Unidad 3, E1) · **Equipo 16** · ITZ
**Integrantes:** Ricardo Uriel Mejía Cortez, Fatima Blancas Ramírez
**Propósito:** controlar existencias de uniformes, registrar apartados con anticipo del 50 % y dar
seguimiento a pedidos, para corregir la inconsistencia de información detectada en la tienda.
**Tipo de aplicación:** web.

## Stack y versiones
Python 3.13 · Django 5.2 · PostgreSQL 16 · psycopg 3.3 · python-dotenv 1.2 · VS Code · Git/GitHub.
Versiones exactas de librerías en `requirements.txt`.

## Estado E1
Entorno, proyecto y BD de 7 tablas funcionando con migraciones; consulta técnica `/conexion/`
operativa. Los casos de uso se construyen en E2 (ver `docs/alcance_e1.md`).

## Instalación y ejecución
```bash
git clone <URL-del-repositorio> && cd uniforma
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1) BD y usuario en PostgreSQL (edita antes la contraseña del archivo)
psql -U postgres -f database/crear_bd.sql

# 2) Variables de entorno: copia el ejemplo y pon tus valores
cp .env.example .env               # Windows: copy .env.example .env

# 3) Tablas y datos ficticios
python manage.py migrate
python manage.py cargar_datos_demo

# 4) Iniciar
python manage.py runserver
```
Abrir **http://127.0.0.1:8000/conexion/**: muestra el número de registros de cada tabla y la lista
de prendas leída desde PostgreSQL.

## Configuración
`config/settings.py` carga `.env` con `python-dotenv` (Django no lo lee por sí solo) y toma
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`.
`.env` está en `.gitignore`; solo se sube `.env.example` (sin claves reales).

## Estructura
```
config/    configuración del proyecto Django
tienda/    app: models.py (7 tablas), views.py, migrations/, comando cargar_datos_demo
database/  crear_bd.sql (BD y usuario) y notas de creación
docs/      alcance, responsables y acuerdo de integración
```
Todos los datos de demostración son ficticios.
