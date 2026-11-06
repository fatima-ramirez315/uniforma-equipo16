# Alcance y organización (Equipo 16 · Uniforma)

| CU | Prioridad | Responsable | Dependencia |
|----|-----------|-------------|-------------|
| CU-01 Consultar disponibilidad | Alta | Ricardo | Lee Prenda.existencias |
| CU-10 Registrar entrada de mercancía | Alta | Ricardo | Actualiza existencias (base de CU-01 y apartados) |
| CU-02 Registrar apartado | Alta | Fatima | Requiere CU-01; include CU-03 |
| CU-03 Registrar anticipo del 50 % | Alta | Fatima | Include de CU-02 |
(la tabla completa de los 10 CU está en el PDF U3-E1)

## Acuerdo de integración
- Un solo repositorio y las mismas migraciones; rama `main` siempre ejecutable.
- Cada integrante trabaja en su rama `cu-XX-nombre` y la une a `main` por Pull Request.
- El otro integrante revisa que `migrate` y `runserver` funcionen antes de aceptar.
- Si cambia un modelo, se avisa antes y se genera una sola migración nueva.
- Se sincroniza (pull) antes de empezar y push al terminar; los conflictos se resuelven juntos.
