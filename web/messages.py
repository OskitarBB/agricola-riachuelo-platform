# web/messages.py — Textos de la web que no son etiquetas de campos (es-PE). Centralizados para revisarlos juntos.
LOGIN_INVALIDO = "Correo o contraseña incorrectos."
LOGIN_BLOQUEADO = "Demasiados intentos fallidos. Vuelve a intentarlo en {minutos} minutos."
CUENTA_PENDIENTE = "Tu cuenta está pendiente de aprobación del administrador."
CUENTA_RECHAZADA = "Tu solicitud de cuenta fue rechazada. Comunícate con el administrador."
CUENTA_BLOQUEADA = "Tu cuenta está bloqueada. Comunícate con el administrador."
SIN_ACCESO_WEB = "Tu cuenta no tiene acceso a la plataforma web. Usa la app móvil."
CONTRASENA_OBLIGATORIA = "Debes cambiar tu contraseña temporal antes de continuar."
CONTRASENA_CAMBIADA = "Tu contraseña se cambió."
CASO_DECIDIDO = "Decisión registrada: {decision}."
CASO_YA_DECIDIDO = "Este caso ya fue decidido por {quien} el {cuando}. Se muestra la decisión vigente."
CASO_CORREGIDO = "La decisión se corrigió. La anterior queda en el historial."
DECISION_CAMBIO = "La decisión vigente cambió mientras corregías. Revisa la versión actual."
AVISO_ENCOLADO = "Se avisará por WhatsApp a {n} destinatario(s)."
AVISO_SIN_DESTINATARIOS = "No hay destinatarios activos para este lote: no se envió ningún aviso."
CASO_MANUAL_ABIERTO = "Caso abierto para revisión."
TAREA_REENCOLADA = "La tarea volvió a la cola de análisis."
CUENTA_APROBADA = "Cuenta aprobada."
CUENTA_ACTUALIZADA = "Cuenta actualizada."
CUENTA_EDITADA = "Datos de {nombre} guardados."
CUENTA_SIN_CAMBIOS = "No había cambios que guardar."
CONTRASENA_ASIGNADA = ("Contraseña de {nombre} asignada. Se cerró su sesión en la app; entrégale la contraseña en "
                       "persona{extra}.")
CONTRASENA_TEMPORAL = ("Contraseña temporal de {nombre}: {clave} — entrégala en persona; no se volverá a mostrar. "
                       "Se cerró su sesión en la app.")
# v1.1 (ADR-W-005): alta de cuentas desde la web
CUENTA_CREADA = ("Cuenta creada para {nombre} ({correo}). Contraseña temporal: {clave} — entrégala en persona; no se "
                 "volverá a mostrar. {donde}")
CUENTA_CREADA_WEB = "Ingresa en {url} y, al entrar, deberá cambiarla."
CUENTA_CREADA_APP = "Es una cuenta de la app móvil: ingresa desde la app y allí deberá cambiarla."
CELULAR_REVOCADO = "Celular revocado: ya no puede usar la API."
DESTINATARIO_GUARDADO = "Destinatario guardado."
IA_AVISO = "Indicio sugerido por IA: no es un diagnóstico. La decisión es del especialista."
DESCARTADAS_AYUDA = ("Fotos que la IA descartó: no abrieron caso ni avisaron a nadie. Revísalas de vez en cuando; si ves "
                     "una plaga que la IA no marcó, abre la foto y pulsa «Abrir caso para revisión».")
BANDEJA_AYUDA = "Cada caso es una foto con un indicio sugerido por la IA o abierta por el especialista."
# v1.0+ (textos nuevos de esta entrega)
NUBE_SIMULADA = ("Modo demostración: Cloudinary no está configurado. Las fotos se sirven desde esta computadora "
                 "(o son ilustraciones generadas). En piloto se usan las URLs firmadas de Cloudinary.")
SIN_MODELO_IA = "No hay un modelo de IA activo: las fotos nuevas no se analizarán hasta activar uno en Gestión."
# v1.2 (ADR-W-006): catálogos del fundo
CATALOGO_LOTE_CREADO = "Lote {lote} creado. Agrega sus hileras."
CATALOGO_GUARDADO = "Cambios guardados. Llegan a la app cuando el controlador toca «Actualizar» en Catálogos."
CATALOGO_NO_GUARDADO = "No se guardó: {errores}"
CATALOGO_HILERAS_CREADAS = "Se crearon {n} hilera(s)."
CATALOGO_HILERAS_SALTADAS = "Ya existían y se saltaron: {numeros}."
CATALOGO_COMPLETADAS = "Se agregó el segmento de hilera completa a {n} hilera(s)."
CATALOGO_DESACTIVADO = "Desactivado. Ya no aparecerá en la app ni en el plano; la historia se conserva."
CATALOGO_REACTIVADO = "Reactivado."
CATALOGO_SESION_EN_CURSO = ("Hay {n} sesión(es) en curso en esta zona: los celulares que ya la tienen pueden "
                            "terminarla y sincronizar.")
# v1.3.1 (ADR-W-008): limpieza de fotos
LIMPIEZA_SESION_OK = "Sesión eliminada: se borraron {fotos} foto(s), {casos} caso(s) y sus análisis."
LIMPIEZA_DESCARTADAS_OK = "Se borraron {n} foto(s) descartadas por la IA."
LIMPIEZA_NADA = "No hay fotos que cumplan la condición: no se borró nada."
LIMPIEZA_NUBE_PENDIENTE = ("{n} foto(s) aún no se borraron en Cloudinary (sin conexión o error): el worker lo "
                           "reintenta cada minuto.")
