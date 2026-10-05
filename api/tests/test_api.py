# api/tests/test_api.py — Contrato /api/v1 de la app móvil (Maestro App Móvil §15): forma de errores, autenticación
# con celular, sincronización idempotente y flujo de fotos ticket → Cloudinary → confirmación → cola de IA.
import hashlib
import json
import uuid
from datetime import timedelta

import cloudinary
import cloudinary.utils
from django.core.cache import cache
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from auditoria.models import AuditEvent
from cuentas.models import AccountStatus, Device, PasswordResetRequest, Role, User
from evidencias import nube
from evidencias.models import Capture
from ia.models import AiStatus, AiTask
from monitoreo.models import CaptureSequence, Incident, MonitoringPass, MonitoringSession
from web.tests import factories as F

API = "/api/v1"


def ahora(delta_min=0):
    return (timezone.now() + timedelta(minutes=delta_min)).isoformat().replace("+00:00", "Z")


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.w = F.world()
        self.device_id = str(uuid.uuid4())
        self.c = APIClient()

    def device(self, device_id=None):
        return {"deviceId": device_id or self.device_id, "platform": "android", "model": "Moto G54",
                "osVersion": "14", "appVersion": "0.4.0"}

    def login(self, email="op@x.pe", password=F.PASSWORD, device_id=None):
        return self.c.post(f"{API}/auth/login", {"email": email, "password": password,
                                                 "device": self.device(device_id)}, format="json")

    def autenticar(self, email="op@x.pe"):
        r = self.login(email)
        self.assertEqual(r.status_code, 200, r.content)
        self.tokens = r.json()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['accessToken']}", HTTP_X_DEVICE_ID=self.device_id)
        return self.tokens

    def assertError(self, r, status, code):
        self.assertEqual(r.status_code, status, r.content)
        body = r.json()
        self.assertEqual(body["code"], code)
        self.assertTrue(body["message"])
        self.assertTrue(body["traceId"])
        self.assertEqual(body["traceId"], r["X-Trace-Id"])
        return body


class Autenticacion(Base):
    def test_health_es_publico_con_o_sin_barra_final(self):
        for url in (f"{API}/health", f"{API}/health/"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "UP")
            self.assertTrue(r.json()["serverTime"].endswith("Z"))

    def test_registro_queda_pendiente_y_no_duplica_correos(self):
        datos = {"fullName": "Rosa Quispe Huamán", "email": "Rosa@Campo.pe", "phone": "+51 987 654 321",
                 "employeeCode": "E-77", "password": "Vid-Ica-2026", "acceptedPrivacyNotice": True}
        r = self.c.post(f"{API}/auth/register", datos, format="json", HTTP_X_DEVICE_ID=self.device_id)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["status"], AccountStatus.PENDIENTE_APROBACION)
        u = User.objects.get(email="rosa@campo.pe")
        self.assertEqual((u.phone, u.roles), ("+51987654321", set()))
        self.assertTrue(AuditEvent.objects.filter(action="CUENTA_REGISTRADA", entity_id=str(u.pk)).exists())
        self.assertError(self.c.post(f"{API}/auth/register", datos, format="json"), 409, "EMAIL_ALREADY_REGISTERED")

    def test_registro_errores_por_campo_en_camelcase(self):
        r = self.c.post(f"{API}/auth/register", {"fullName": "Ana", "email": "no-es-correo", "password": "corta",
                                                 "acceptedPrivacyNotice": False}, format="json")
        body = self.assertError(r, 400, "VALIDATION_ERROR")
        campos = {e["field"] for e in body["fieldErrors"]}
        self.assertTrue({"fullName", "email", "acceptedPrivacyNotice"} <= campos, campos)
        r = self.c.post(f"{API}/auth/register", {"fullName": "Ana Torres", "email": "ana@x.pe", "password": "12345678",
                                                 "acceptedPrivacyNotice": True}, format="json")
        self.assertEqual(self.assertError(r, 400, "VALIDATION_ERROR")["fieldErrors"][0]["field"], "password")

    def test_login_operador_emite_tokens_y_registra_el_celular(self):
        t = self.autenticar()
        self.assertEqual(set(t), {"accessToken", "accessTokenExpiresAt", "refreshToken", "refreshTokenExpiresAt",
                                  "user", "serverTime"})
        self.assertEqual(t["user"]["roles"], [Role.OPERADOR_CAMPO])
        self.assertEqual(t["user"]["mustChangePassword"], False)
        d = Device.objects.get(pk=self.device_id)
        self.assertEqual((d.user, d.model, d.app_version), (self.w.op, "Moto G54", "0.4.0"))
        self.assertTrue(AuditEvent.objects.filter(action="INGRESO_APP", user=self.w.op).exists())
        r = self.c.get(f"{API}/auth/me")
        self.assertEqual(r.json()["email"], "op@x.pe")

    def test_login_responde_el_estado_solo_con_contrasena_correcta(self):
        F.user("pend@x.pe", Role.OPERADOR_CAMPO, status=AccountStatus.PENDIENTE_APROBACION)
        F.user("bloq@x.pe", Role.OPERADOR_CAMPO, status=AccountStatus.BLOQUEADO)
        F.user("rech@x.pe", Role.OPERADOR_CAMPO, status=AccountStatus.RECHAZADO)
        self.assertError(self.login("pend@x.pe", "mala"), 401, "INVALID_CREDENTIALS")
        self.assertError(self.login("pend@x.pe"), 403, "ACCOUNT_PENDING")
        self.assertError(self.login("bloq@x.pe"), 403, "ACCOUNT_BLOCKED")
        self.assertError(self.login("rech@x.pe"), 403, "ACCOUNT_REJECTED")
        self.assertError(self.login("sup@x.pe"), 403, "ROLE_NOT_ALLOWED")  # supervisor: solo web
        self.assertEqual(self.login("admin@x.pe").status_code, 200)  # administrador: web y app
        self.assertError(self.login("noexiste@x.pe"), 401, "INVALID_CREDENTIALS")

    def test_bloqueo_temporal_tras_cinco_fallos(self):
        for _ in range(5):
            self.login(password="mala")
        self.assertError(self.login(), 429, "TOO_MANY_ATTEMPTS")

    def test_refresh_rota_y_el_anterior_deja_de_servir(self):
        t = self.autenticar()
        r = self.c.post(f"{API}/auth/refresh", {"refreshToken": t["refreshToken"], "deviceId": self.device_id},
                        format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(r.json()["refreshToken"], t["refreshToken"])
        r = self.c.post(f"{API}/auth/refresh", {"refreshToken": t["refreshToken"], "deviceId": self.device_id},
                        format="json")
        self.assertError(r, 401, "REFRESH_INVALID")

    def test_refresh_de_otro_celular_se_rechaza(self):
        t = self.autenticar()
        r = self.c.post(f"{API}/auth/refresh", {"refreshToken": t["refreshToken"], "deviceId": str(uuid.uuid4())},
                        format="json")
        self.assertError(r, 401, "REFRESH_INVALID")

    def test_logout_invalida_el_refresh(self):
        t = self.autenticar()
        r = self.c.post(f"{API}/auth/logout", {"refreshToken": t["refreshToken"], "deviceId": self.device_id},
                        format="json")
        self.assertEqual(r.status_code, 204)
        r = self.c.post(f"{API}/auth/refresh", {"refreshToken": t["refreshToken"], "deviceId": self.device_id},
                        format="json")
        self.assertError(r, 401, "REFRESH_INVALID")

    def test_sin_token_o_con_token_invalido_401(self):
        self.assertError(self.c.get(f"{API}/auth/me"), 401, "TOKEN_EXPIRED")
        self.c.credentials(HTTP_AUTHORIZATION="Bearer basura")
        self.assertError(self.c.get(f"{API}/auth/me"), 401, "TOKEN_EXPIRED")

    def test_token_usado_desde_otro_celular_401(self):
        self.autenticar()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['accessToken']}", HTTP_X_DEVICE_ID=str(uuid.uuid4()))
        self.assertError(self.c.get(f"{API}/auth/me"), 401, "TOKEN_EXPIRED")

    def test_x_device_id_mal_formado_400(self):
        self.autenticar()
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['accessToken']}", HTTP_X_DEVICE_ID="no-es-uuid")
        self.assertError(self.c.get(f"{API}/auth/me"), 400, "VALIDATION_ERROR")

    def test_celular_revocado_y_cuenta_bloqueada_cortan_el_acceso(self):
        self.autenticar()
        Device.objects.filter(pk=self.device_id).update(revoked_at=timezone.now())
        self.assertError(self.c.get(f"{API}/auth/me"), 403, "DEVICE_REVOKED")
        self.assertError(self.login(), 403, "DEVICE_REVOKED")
        Device.objects.filter(pk=self.device_id).update(revoked_at=None)
        User.objects.filter(pk=self.w.op.pk).update(status=AccountStatus.BLOQUEADO)
        self.assertError(self.c.get(f"{API}/auth/me"), 403, "ACCOUNT_BLOCKED")

    def test_cambiar_contrasena(self):
        self.autenticar()
        url = f"{API}/auth/change-password"
        self.assertError(self.c.post(url, {"currentPassword": "mala", "newPassword": "Vid-Ica-2027"}, format="json"),
                         401, "INVALID_CREDENTIALS")
        body = self.assertError(self.c.post(url, {"currentPassword": F.PASSWORD, "newPassword": "solo-letras"},
                                            format="json"), 400, "PASSWORD_POLICY")
        self.assertEqual(body["fieldErrors"][0]["field"], "newPassword")
        User.objects.filter(pk=self.w.op.pk).update(must_change_password=True)
        r = self.c.post(url, {"currentPassword": F.PASSWORD, "newPassword": "Vid-Ica-2027"}, format="json")
        self.assertEqual(r.status_code, 204)
        self.w.op.refresh_from_db()
        self.assertTrue(self.w.op.check_password("Vid-Ica-2027"))
        self.assertFalse(self.w.op.must_change_password)

    def test_pedido_de_restablecimiento_siempre_202_y_sin_duplicar(self):
        url = f"{API}/auth/password-reset-requests"
        for email in ("op@x.pe", "OP@x.pe", "nadie@x.pe"):
            self.assertEqual(self.c.post(url, {"email": email}, format="json").status_code, 202)
        self.assertEqual(PasswordResetRequest.objects.filter(email="op@x.pe").count(), 1)
        self.assertEqual(PasswordResetRequest.objects.get(email="nadie@x.pe").user, None)

    def test_esquema_openapi_publico(self):
        r = self.c.get(f"{API}/schema")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"/api/v1/captures/upload", r.content)


class SyncMixin:
    """Payloads como los arma la app (src/api/dto.ts). Lo reutilizan las pruebas del Cloudinary simulado."""

    def preparar_ids(self):
        self.autenticar()
        self.sid, self.pid, self.qid, self.cid, self.mcid = (str(uuid.uuid4()) for _ in range(5))

    def sesion(self, status="ACTIVE", **extra):
        return {"sessionId": self.sid, "operatorUserId": str(self.w.op.pk), "controllerDeviceId": self.device_id,
                "status": status, "mode": "MANUAL", "intervalMs": 0, "startedAt": ahora(-30),
                "endedAt": ahora() if status == "CLOSED" else None, "appVersion": "0.4.0", "configVersion": "CFG-4",
                "qualityProfileVersion": "Q0", "shortTestPassedAt": ahora(-31),
                "cameras": [{"role": "CAMERA_1", "deviceId": self.device_id, "userId": str(self.w.op.pk),
                             "platform": "android", "model": "Moto G54", "osVersion": "14", "appVersion": "0.4.0",
                             "pairedAt": ahora(-31), "released": False}], **extra}

    def pasada(self, **extra):
        return {"passId": self.pid, "lotId": "SWG1", "rowId": "SWG1-H05", "lateralCode": "LATERAL_A", "passOrder": 1,
                "direction": "ASCENDENTE", "startMarkerId": "SWG1-M1", "endMarkerId": None, "status": "ACTIVE",
                "startedAt": ahora(-25), "endedAt": None, "sequencesTotal": 1, "sequencesComplete": 1,
                "sequencesIncomplete": 0,
                "markerChanges": [{"markerChangeId": self.mcid, "markerId": "SWG1-M1", "segmentId": "SWG1-S1",
                                   "changedAt": ahora(-24), "lat": -14.06, "lon": -75.73, "gpsAccuracyM": 5,
                                   "gpsTimestamp": ahora(-24)}], **extra}

    def secuencia(self, **extra):
        return {"sequenceId": self.qid, "passId": self.pid, "sequenceNumber": 1, "mode": "MANUAL", "status": "COMPLETE",
                "segmentId": "SWG1-S1", "markerId": "SWG1-M1", "lat": -14.0601, "lon": -75.7302, "gpsAccuracyM": 4.0,
                "gpsTimestamp": ahora(-20), "issuedAt": ahora(-20), "completedAt": ahora(-20),
                "expectedCaptureIds": {"CAMERA_1": self.cid}, "slotOutcomes": {"CAMERA_1": "OK_RECIBIDA"}, **extra}

    def preparar(self):
        self.assertEqual(self.c.post(f"{API}/sessions", self.sesion(), format="json").status_code, 201)
        self.assertEqual(self.c.post(f"{API}/sessions/{self.sid}/passes", self.pasada(), format="json").status_code, 201)
        r = self.c.post(f"{API}/sessions/{self.sid}/sequences/batch",
                        {"sessionId": self.sid, "sequences": [self.secuencia()]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def ticket_body(self, size=2_400_000, md5="a" * 32):
        return {"captureId": self.cid, "sessionId": self.sid, "passId": self.pid, "sequenceId": self.qid,
                "sizeBytes": size, "md5": md5, "mimeType": "image/jpeg"}

    def metadata(self, size=2_400_000, md5="a" * 32, **extra):
        return {"captureId": self.cid, "sequenceId": self.qid, "sessionId": self.sid, "passId": self.pid,
                "lateralCode": "LATERAL_A", "deviceId": self.device_id, "cameraRole": "CAMERA_1",
                "cameraUserId": str(self.w.op.pk), "operatorUserId": str(self.w.op.pk), "capturedAt": ahora(-20),
                "width": 3000, "height": 4000, "sizeBytes": size, "md5": md5,
                "quality": {"status": "UTILIZABLE", "reasons": [], "profileVersion": "Q0",
                            "metrics": {"luminanceMean": 120.5, "darkRatio": 0.01, "brightRatio": 0.02,
                                        "laplacianVariance": 410.2, "analyzedRegions": 4, "durationMs": 85}},
                "replacesCaptureId": None, "retakeContext": None, "appVersion": "0.4.0", **extra}

    def resultado_cloudinary(self, public_id, size=2_400_000, version=1759500000, firma=None):
        secreto = cloudinary.config().api_secret
        return {"publicId": public_id, "version": version, "bytes": size, "format": "jpg", "width": 3000,
                "height": 4000, "etag": "e" * 32,
                "signature": firma or cloudinary.utils.api_sign_request({"public_id": public_id, "version": version},
                                                                        secreto, signature_version=1)}


class Sincronizacion(SyncMixin, Base):
    def setUp(self):
        super().setUp()
        self.preparar_ids()

    def test_bootstrap_con_catalogos_y_version_estable(self):
        a = self.c.get(f"{API}/mobile/bootstrap").json()
        b = self.c.get(f"{API}/mobile/bootstrap").json()
        self.assertEqual(a["catalogVersion"], b["catalogVersion"])
        self.assertEqual([x["id"] for x in a["lots"]], ["SWG1", "SWG2"])
        self.assertEqual(a["rows"][0], {"id": "SWG1-H05", "lotId": "SWG1", "number": 5, "plantCount": 385,
                                        "active": True})
        self.assertEqual(a["lateralCodes"], ["LATERAL_A", "LATERAL_B"])
        self.assertEqual(a["markers"][0]["segmentId"], "SWG1-S1")

    def test_sesion_idempotente_que_nunca_se_reabre(self):
        self.assertEqual(self.c.post(f"{API}/sessions", self.sesion(), format="json").status_code, 201)
        r = self.c.post(f"{API}/sessions", self.sesion(), format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "ACTIVE"))
        self.c.post(f"{API}/sessions", self.sesion("CLOSED"), format="json")
        r = self.c.post(f"{API}/sessions", self.sesion("ACTIVE"), format="json")  # llegada tardía fuera de orden
        self.assertEqual(r.json()["status"], "CLOSED")
        self.assertEqual(MonitoringSession.objects.filter(pk=self.sid).count(), 1)
        acciones = set(AuditEvent.objects.filter(entity_id=self.sid).values_list("action", flat=True))
        self.assertEqual(acciones, {"SESION_RECIBIDA", "SESION_CERRADA"})

    def test_sesion_con_usuario_desconocido(self):
        body = self.assertError(self.c.post(f"{API}/sessions", self.sesion(operatorUserId=str(uuid.uuid4())),
                                            format="json"), 400, "VALIDATION_ERROR")
        self.assertEqual(body["fieldErrors"][0]["field"], "operatorUserId")

    def test_pasada_idempotente_y_validada_contra_catalogos(self):
        self.assertError(self.c.post(f"{API}/sessions/{self.sid}/passes", self.pasada(), format="json"), 404,
                         "SESSION_NOT_FOUND")
        self.c.post(f"{API}/sessions", self.sesion(), format="json")
        self.assertEqual(self.c.post(f"{API}/sessions/{self.sid}/passes", self.pasada(), format="json").status_code, 201)
        r = self.c.post(f"{API}/sessions/{self.sid}/passes", self.pasada(status="COMPLETED", endedAt=ahora()),
                        format="json")
        self.assertEqual((r.status_code, r.json()["status"]), (200, "COMPLETED"))
        self.assertEqual(MonitoringPass.objects.get(pk=self.pid).marker_changes.count(), 1)  # no duplica cambios
        body = self.assertError(self.c.post(f"{API}/sessions/{self.sid}/passes",
                                            self.pasada(passId=str(uuid.uuid4()), rowId="SWG2-H01"), format="json"),
                                400, "VALIDATION_ERROR")
        self.assertEqual(body["fieldErrors"][0]["field"], "rowId")

    def test_secuencias_e_incidencias_por_lote_sin_duplicar(self):
        self.preparar()
        r = self.c.post(f"{API}/sessions/{self.sid}/sequences/batch",
                        {"sessionId": self.sid, "sequences": [self.secuencia()]}, format="json")
        self.assertEqual(r.json(), {"accepted": 0, "duplicates": 1})
        self.assertEqual(CaptureSequence.objects.filter(pk=self.qid).count(), 1)
        inc = {"incidentId": str(uuid.uuid4()), "passId": self.pid, "sequenceId": None, "captureId": None,
               "deviceId": self.device_id, "type": "OPERADOR", "severity": "AVISO", "detail": "Riego en la hilera",
               "occurredAt": ahora(-10), "createdBy": "OPERADOR"}
        for _ in range(2):
            r = self.c.post(f"{API}/sessions/{self.sid}/incidents/batch", {"sessionId": self.sid, "incidents": [inc]},
                            format="json")
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Incident.objects.count(), 1)
        otro = str(uuid.uuid4())
        self.assertError(self.c.post(f"{API}/sessions/{self.sid}/incidents/batch", {"sessionId": otro, "incidents": []},
                                     format="json"), 400, "VALIDATION_ERROR")

    def test_flujo_de_foto_ticket_cloudinary_confirmacion(self):
        self.preparar()
        r = self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        t = r.json()
        self.assertFalse(t["alreadyConfirmed"])
        up = t["upload"]
        self.assertEqual(up["publicId"], f"riachuelo/{nube.settings.CLOUDINARY_ENV_PREFIX}/{self.sid}/{self.pid}/{self.cid}")
        self.assertTrue(up["url"].startswith("https://api.cloudinary.com/v1_1/"))
        self.assertEqual((up["fields"]["type"], up["fields"]["overwrite"]), ("authenticated", "false"))
        firmados = {k: v for k, v in up["fields"].items() if k not in ("api_key", "signature")}
        self.assertEqual(up["fields"]["signature"],
                         cloudinary.utils.api_sign_request(firmados, cloudinary.config().api_secret))
        self.assertNotIn(cloudinary.config().api_secret, r.content.decode())  # el secreto nunca sale (W-09)

        body = {"metadata": self.metadata(), "cloudinary": self.resultado_cloudinary(up["publicId"])}
        r = self.c.post(f"{API}/captures/upload", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json(), {"captureId": self.cid, "status": "SINCRONIZADO", "duplicate": False})
        cap = Capture.objects.get(pk=self.cid)
        self.assertEqual((cap.quality.status, cap.cloudinary_version), ("UTILIZABLE", 1759500000))
        self.assertEqual(AiTask.objects.get(capture=cap).status, AiStatus.PENDIENTE_DE_ANALISIS)  # misma transacción
        self.assertTrue(AuditEvent.objects.filter(action="CAPTURA_CONFIRMADA", entity_id=self.cid).exists())

        r = self.c.post(f"{API}/captures/upload", body, format="json")  # reintento de la app
        self.assertEqual((r.status_code, r.json()["duplicate"]), (200, True))
        r = self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(), format="json")
        self.assertEqual((r.json()["alreadyConfirmed"], r.json()["upload"]), (True, None))
        self.assertError(self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(md5="b" * 32),
                                     format="json"), 409, "CAPTURE_CONFLICT")
        r = self.c.get(f"{API}/captures/{self.cid}")
        self.assertEqual((r.status_code, r.json()["md5"]), (200, "a" * 32))
        self.assertError(self.c.get(f"{API}/captures/{uuid.uuid4()}"), 404, "NOT_FOUND")

    def test_confirmacion_rechaza_firma_o_recurso_ajeno(self):
        self.preparar()
        pid = nube.public_id_for(self.sid, self.pid, self.cid)
        self.assertError(self.c.post(f"{API}/captures/upload", {
            "metadata": self.metadata(), "cloudinary": self.resultado_cloudinary(pid, firma="0" * 40)}, format="json"),
            422, "UPLOAD_SIGNATURE_INVALID")
        self.assertError(self.c.post(f"{API}/captures/upload", {
            "metadata": self.metadata(), "cloudinary": self.resultado_cloudinary(pid + "-otro")}, format="json"),
            409, "UPLOAD_MISMATCH")
        self.assertError(self.c.post(f"{API}/captures/upload", {
            "metadata": self.metadata(), "cloudinary": self.resultado_cloudinary(pid, size=1)}, format="json"),
            409, "UPLOAD_MISMATCH")
        body = self.assertError(self.c.post(f"{API}/captures/upload", {
            "metadata": self.metadata(lateralCode="LATERAL_B"), "cloudinary": self.resultado_cloudinary(pid)},
            format="json"), 400, "VALIDATION_ERROR")
        self.assertEqual(body["fieldErrors"][0]["field"], "metadata.lateralCode")
        self.assertFalse(Capture.objects.exists())

    def test_ticket_valida_tamano_y_padres(self):
        self.assertError(self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(), format="json"),
                         404, "SESSION_NOT_FOUND")
        self.preparar()
        self.assertError(self.c.post(f"{API}/captures/{self.cid}/upload-ticket", self.ticket_body(size=50_000_000),
                                     format="json"), 413, "PAYLOAD_TOO_LARGE")
        otro = dict(self.ticket_body(), sequenceId=str(uuid.uuid4()))
        self.assertError(self.c.post(f"{API}/captures/{self.cid}/upload-ticket", otro, format="json"), 404,
                         "SEQUENCE_NOT_FOUND")
        distinto = dict(self.ticket_body(), captureId=str(uuid.uuid4()))
        self.assertError(self.c.post(f"{API}/captures/{self.cid}/upload-ticket", distinto, format="json"), 400,
                         "VALIDATION_ERROR")

    def test_respuestas_sin_urls_de_fotos_ni_datos_de_revision(self):
        self.preparar()
        for url in (f"{API}/mobile/bootstrap", f"{API}/auth/me"):
            texto = self.c.get(url).content.decode()
            self.assertNotIn("res.cloudinary.com", texto)
            self.assertNotIn("PENDIENTE_REVISION", texto)

    def test_campos_desconocidos_no_bloquean_la_sincronizacion(self):
        r = self.c.post(f"{API}/sessions", self.sesion(campoNuevoDeLaApp=True), format="json")
        self.assertEqual(r.status_code, 201)

    def test_md5_de_la_foto_se_guarda_en_minusculas(self):
        self.preparar()
        md5 = hashlib.md5(b"x").hexdigest().upper()
        pid = nube.public_id_for(self.sid, self.pid, self.cid)
        r = self.c.post(f"{API}/captures/upload", {"metadata": self.metadata(md5=md5),
                                                   "cloudinary": self.resultado_cloudinary(pid)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Capture.objects.get(pk=self.cid).md5, md5.lower())

    # ---------------------------------------------------------------- compatibilidad con la app v1 (multipart)
    def multipart(self, data, meta):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.c.post(f"{API}/captures/upload", {"metadata": json.dumps(meta),
                                                     "file": SimpleUploadedFile("foto.jpg", data, "image/jpeg")},
                           format="multipart")

    def test_subida_multipart_de_la_app_v1(self):
        self.preparar()
        data = b"\xff\xd8" + b"x" * 5000
        md5 = hashlib.md5(data).hexdigest()
        meta = self.metadata(len(data), md5)
        pid = nube.public_id_for(self.sid, self.pid, self.cid)
        respuesta = {"public_id": pid, "version": 1759600000, "bytes": len(data), "format": "jpg", "width": 3000,
                     "height": 4000, "etag": md5,
                     "signature": cloudinary.utils.api_sign_request({"public_id": pid, "version": 1759600000},
                                                                    cloudinary.config().api_secret, signature_version=1)}
        with mock.patch("cloudinary.uploader.upload", return_value=respuesta) as subir:
            r = self.multipart(data, meta)
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(r.json(), {"captureId": self.cid, "status": "SINCRONIZADO", "duplicate": False})
            self.assertEqual(subir.call_args.kwargs["public_id"], pid)
            self.assertEqual((subir.call_args.kwargs["type"], subir.call_args.kwargs["overwrite"]), ("authenticated", False))
            r = self.multipart(data, meta)  # reintento: no vuelve a subir
            self.assertEqual((r.status_code, r.json()["duplicate"], subir.call_count), (200, True, 1))
        self.assertEqual(AiTask.objects.get(capture_id=self.cid).status, AiStatus.PENDIENTE_DE_ANALISIS)

    def test_multipart_valida_archivo_y_metadata(self):
        self.preparar()
        data = b"\xff\xd8" + b"y" * 100
        with mock.patch("cloudinary.uploader.upload") as subir:
            body = self.assertError(self.multipart(data, self.metadata(len(data) + 1, "a" * 32)), 400, "VALIDATION_ERROR")
            self.assertEqual({e["field"] for e in body["fieldErrors"]}, {"file"})
            r = self.c.post(f"{API}/captures/upload", {"metadata": "{no es json"}, format="multipart")
            self.assertEqual(self.assertError(r, 400, "VALIDATION_ERROR")["fieldErrors"][0]["field"], "metadata")
            meta = self.metadata(len(data), hashlib.md5(data).hexdigest(), lateralCode="LATERAL_B")
            self.assertError(self.multipart(data, meta), 400, "VALIDATION_ERROR")
            self.assertFalse(subir.called)  # nada se sube a Cloudinary si la metadata no es válida

    def test_multipart_se_puede_desactivar(self):
        self.preparar()
        with override_settings(API_SUBIDA_MULTIPART=False):
            self.assertError(self.multipart(b"x", self.metadata(1, "a" * 32)), 400, "VALIDATION_ERROR")

