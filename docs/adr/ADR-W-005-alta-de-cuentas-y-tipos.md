# ADR-W-005 — Alta de cuentas desde la web y tipos de cuenta (app o web)

05/10/2026 · Estado: aceptada (pedido del equipo del proyecto) · Autor: Claude (asistente de desarrollo)

**Contexto.** En el Maestro Web v1.0 (§7.5) las cuentas solo nacen pendientes desde la app (`POST /auth/register`,
D-05) y el administrador las aprueba en WEB-13. Con el piloto ya publicado en `monitoreo.agricolariachuelo.org` y la
app todavía sin conectar al servidor (fase 4), nadie podía obtener una cuenta de la web salvo con `createsuperuser`.
Además, un especialista o supervisor no debería instalar la app solo para registrarse. El equipo pidió que los
operadores tengan cuentas distintas de las de quienes usan la web.

**Decisión.**

1. **«Nueva cuenta» en WEB-13** (`POST /administracion/usuarios/nueva/`, permiso `usuarios.gestionar`): el
   administrador crea una cuenta **activa**, aprobada por él, con **contraseña temporal** de 12 caracteres (la misma
   de D-07, mostrada una sola vez) y `must_change_password`. Auditoría `CUENTA_CREADA` (sin la contraseña). Servicio:
   `cuentas.services.create_account`.
2. **No hay registro público en la web.** El login lo explica: las cuentas de la web las crea el administrador; los
   operadores se registran desde la app.
3. **Tipos de cuenta** (`cuentas.services.validate_roles`, aplicado también al aprobar y al cambiar roles):
   - cuenta de la **app**: solo `OPERADOR_CAMPO` (rol único);
   - cuenta de la **web**: `ESPECIALISTA_FITOSANITARIO`, `SUPERVISOR` y/o `ADMINISTRADOR` (los permisos se suman,
     DW-04). El administrador ya puede usar la app (RN-02), así que no necesita el rol de operador.
   Una persona que trabaja en el campo y en la web tiene dos cuentas con correos distintos.
4. El formulario pregunta primero el **tipo de cuenta** (web o app). Con «App móvil» la cuenta queda solo con
   `OPERADOR_CAMPO`; sirve mientras la app no esté conectada o para dar de alta a alguien sin su celular.
5. Django Admin ya **no crea usuarios** (`has_add_permission = False`, W-03): las altas pasan por el servicio.

**Alternativas.** Registro público en la web con aprobación posterior (abre a internet un formulario sin necesidad).
Seguir solo con el registro de la app (bloquea a los usuarios de la web hasta la fase 4). Permitir cualquier
combinación de roles (mezcla en una misma cuenta la captura de campo con la revisión; complica la auditoría).

**Consecuencias.** Sin migraciones: se usan las tablas `users`, `user_roles` y `audit_events`. Aprobar o cambiar
roles muestra un error si se intenta combinar «Operador de campo» con roles de la web.
Las rutas, permisos y mensajes nuevos deben incorporarse al Maestro Web en su próxima versión (§6.3, §7.5, §9 WEB-13
y Anexo D.5).
