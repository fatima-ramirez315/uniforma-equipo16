-- Prepara la BD vacía y el usuario (ejecutar como superusuario de PostgreSQL).
-- Cambia la contraseña por una propia y colócala también en .env (DB_PASSWORD).
-- Las TABLAS no se crean aquí: las crean las migraciones de Django (tienda/migrations).
CREATE ROLE uniforma_user LOGIN PASSWORD 'cambia_esta_contrasena';
CREATE DATABASE uniforma_db OWNER uniforma_user ENCODING 'UTF8';
