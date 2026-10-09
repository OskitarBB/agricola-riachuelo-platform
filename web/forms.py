# web/forms.py — Formularios de la web. Validan forma; las reglas de negocio están en los servicios.
from django import forms
from django.conf import settings
from django.core.cache import cache

from campo.models import MarkerPosition
from cuentas.models import AccountStatus, Role, User
from notificaciones.models import NotificationRecipient
from revision.models import DECISIONS, ReviewStatus
from web import messages as M

DECISION_CHOICES = [(d.value, d.label) for d in DECISIONS]


def _lock_key(email):
    return f"web-login-fallos:{email.lower()}"


class LoginForm(forms.Form):
    email = forms.EmailField(label="Correo", widget=forms.EmailInput(attrs={
        "autocomplete": "username", "autofocus": True, "placeholder": "tu.correo@riachuelo.pe"}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={
        "autocomplete": "current-password", "placeholder": "••••••••"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None

    def clean(self):
        data = super().clean()
        email, password = data.get("email"), data.get("password")
        if not email or not password:
            return data
        key = _lock_key(email)
        fails = cache.get(key, 0)
        if fails >= settings.WEB["LOGIN_MAX_FAILED"]:
            raise forms.ValidationError(M.LOGIN_BLOQUEADO.format(minutos=settings.WEB["LOGIN_LOCKOUT_MINUTES"]))
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            User().set_password(password)  # mismo tiempo de respuesta exista o no la cuenta
            ok = False
        else:
            ok = user.check_password(password)
        if not ok:
            cache.set(key, fails + 1, settings.WEB["LOGIN_LOCKOUT_MINUTES"] * 60)
            raise forms.ValidationError(M.LOGIN_INVALIDO)
        cache.delete(key)
        # El estado solo se revela después de comprobar la contraseña (no permite averiguar qué correos existen).
        if user.status == AccountStatus.PENDIENTE_APROBACION:
            raise forms.ValidationError(M.CUENTA_PENDIENTE)
        if user.status == AccountStatus.RECHAZADO:
            raise forms.ValidationError(M.CUENTA_RECHAZADA)
        if user.status == AccountStatus.BLOQUEADO:
            raise forms.ValidationError(M.CUENTA_BLOQUEADA)
        if not user.can_use_web:
            raise forms.ValidationError(M.SIN_ACCESO_WEB)
        self.user = user
        return data


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    observation = forms.CharField(required=False, widget=forms.Textarea(attrs={
        "rows": 4, "placeholder": "Qué se observa en la evidencia (sin tratamientos ni dosis)…"}),
        max_length=settings.WEB["OBSERVATION_MAX_LENGTH"])
    confirmed_class = forms.ChoiceField(required=False, choices=[])
    rejected_detection_ids = forms.MultipleChoiceField(required=False, choices=[], widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        task = case.ai_task if case else None
        classes = (task.model_config.classes if task else []) or []
        self.fields["confirmed_class"].choices = [("", "— Sin especificar —")] + [(c, c) for c in classes]
        dets = list(task.detections.all()) if task else []
        self.fields["rejected_detection_ids"].choices = [(str(d.id), f"Caja {i}") for i, d in enumerate(dets, 1)]


class CorrectionForm(DecisionForm):
    correction_reason = forms.CharField(widget=forms.Textarea(attrs={
        "rows": 2, "placeholder": "Por qué cambias la decisión…"}), max_length=1000)
    expected_review_id = forms.UUIDField(widget=forms.HiddenInput)


class ApproveForm(forms.Form):
    roles = forms.MultipleChoiceField(choices=Role.choices, widget=forms.CheckboxSelectMultiple)


class NuevaCuentaForm(forms.Form):
    """v1.1 (ADR-W-005): alta de una cuenta por el administrador. Valida forma; las reglas (combinación de roles,
    correo único, contraseña temporal) están en cuentas.services.create_account."""

    WEB, APP = "WEB", "APP"
    TIPOS = [(WEB, "Plataforma web"), (APP, "App móvil")]
    ROLES_WEB = [(r.value, r.label) for r in (Role.ESPECIALISTA_FITOSANITARIO, Role.SUPERVISOR, Role.ADMINISTRADOR)]

    tipo = forms.ChoiceField(label="Tipo de cuenta", choices=TIPOS, initial=WEB, widget=forms.RadioSelect)
    full_name = forms.CharField(label="Nombre completo", max_length=150, widget=forms.TextInput(attrs={
        "autocomplete": "off", "placeholder": "Nombres y apellidos"}))
    email = forms.EmailField(label="Correo", max_length=254, widget=forms.EmailInput(attrs={
        "autocomplete": "off", "placeholder": "nombre@riachuelo.pe"}))
    phone = forms.CharField(label="Celular", max_length=20, required=False, widget=forms.TextInput(attrs={
        "inputmode": "tel", "placeholder": "987654321"}))
    employee_code = forms.CharField(label="Código de trabajador", max_length=30, required=False)
    roles = forms.MultipleChoiceField(label="Roles en la web", choices=ROLES_WEB, required=False,
                                      widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""

    def clean(self):
        data = super().clean()
        tipo, roles = data.get("tipo"), data.get("roles") or []
        if tipo == self.APP:
            if roles:  # los roles de la web no se combinan con el de operador (cuentas.services.validate_roles)
                self.add_error("roles", "Una cuenta de la app móvil no lleva roles de la web: desmárcalos o elige "
                                        "«Plataforma web».")
            data["roles"] = [Role.OPERADOR_CAMPO]
        elif tipo == self.WEB and not roles:
            self.add_error("roles", "Elige al menos un rol de la web.")
        return data

    def datos(self):
        d = self.cleaned_data
        return {"full_name": d["full_name"], "email": d["email"], "roles": d["roles"], "phone": d.get("phone", ""),
                "employee_code": d.get("employee_code", "")}


class EditarCuentaForm(forms.Form):
    """v1.3 (ADR-W-007): datos de ingreso y contacto que solo el administrador corrige (cuentas.update_account)."""

    full_name = forms.CharField(label="Nombre completo", max_length=150)
    email = forms.EmailField(label="Correo (usuario de ingreso)", max_length=254,
                             widget=forms.EmailInput(attrs={"autocomplete": "off"}))
    phone = forms.CharField(label="Celular", max_length=20, required=False,
                            widget=forms.TextInput(attrs={"inputmode": "tel"}))
    employee_code = forms.CharField(label="Código de trabajador", max_length=30, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""


class AsignarContrasenaForm(forms.Form):
    """v1.3 (ADR-W-007): el administrador escribe una contraseña para otra cuenta (cuentas.set_password_by_admin)."""

    password1 = forms.CharField(label="Nueva contraseña", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repite la contraseña", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    must_change = forms.BooleanField(label="Pedir que la cambie al ingresar (recomendado)", required=False,
                                     initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""

    def clean(self):
        data = super().clean()
        if data.get("password1") and data.get("password1") != data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        return data


class RecipientForm(forms.ModelForm):
    opt_in = forms.BooleanField(required=False, label="Aceptó recibir avisos por WhatsApp")

    class Meta:
        model = NotificationRecipient
        fields = ["full_name", "phone_e164", "role_label", "user", "lots", "active"]
        widgets = {"lots": forms.CheckboxSelectMultiple,
                   "phone_e164": forms.TextInput(attrs={"placeholder": "+51987654321", "inputmode": "tel"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(
            status=AccountStatus.ACTIVO,
            user_roles__role__in=[Role.SUPERVISOR, Role.ADMINISTRADOR, Role.ESPECIALISTA_FITOSANITARIO]).distinct()
        self.fields["user"].required = False
        self.fields["user"].empty_label = "— Sin cuenta de la web —"
        self.fields["role_label"].choices = [("", "Elige la función")] + list(NotificationRecipient.RoleLabel.choices)
        self.label_suffix = ""
        if self.instance.pk:
            self.fields["opt_in"].initial = self.instance.opt_in_at is not None


class FiltroCasosForm(forms.Form):
    POR_REVISAR = "POR_REVISAR"  # v1.3: pendientes + confirmados por IA (los que el especialista aún decide)
    ESTADOS = [("", "Todos"), (POR_REVISAR, "Por revisar (pendientes y confirmados por IA)")] + list(ReviewStatus.choices)
    ORDEN = [("antiguos", "Más antiguos primero"), ("recientes", "Más recientes primero"),
             ("confianza", "Mayor confianza de la IA")]
    estado = forms.ChoiceField(required=False, choices=ESTADOS)
    lote = forms.CharField(required=False)
    origen = forms.ChoiceField(required=False, choices=[("", "Todos"), ("IA", "IA"), ("MANUAL", "Manual")])
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    orden = forms.ChoiceField(required=False, choices=ORDEN)


# ------------------------------------------------------------------ v1.2 (ADR-W-006): catálogos del fundo
# Validan forma; las reglas (rangos, solapes, códigos únicos, IDs) están en campo/services.py.
class _Catalogo(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.label_suffix = ""


def _entero(label, minimo=1, **kw):
    return forms.IntegerField(label=label, min_value=minimo, widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
                              **kw)


class LoteForm(_Catalogo):
    code = forms.CharField(label="Código", max_length=20, widget=forms.TextInput(attrs={"placeholder": "SWG 4"}))
    name = forms.CharField(label="Nombre", max_length=80, widget=forms.TextInput(attrs={"placeholder": "Lote 4 (Norte)"}))


class HilerasForm(_Catalogo):
    desde = _entero("Desde la hilera")
    hasta = _entero("Hasta la hilera")
    plantas = _entero("Plantas por hilera")
    segmento_completo = forms.BooleanField(label="Crear segmento de hilera completa con marcadores de inicio y fin",
                                           required=False, initial=True)


class HileraForm(_Catalogo):
    plant_count = _entero("Plantas de la hilera")


class SegmentoForm(_Catalogo):
    code = forms.CharField(label="Código", max_length=40, widget=forms.TextInput(attrs={"placeholder": "H05 S1"}))
    start_plant = _entero("Planta inicial")
    end_plant = _entero("Planta final")
    is_pilot = forms.BooleanField(label="Segmento del piloto", required=False)


class DividirForm(_Catalogo):
    PARTES, CADA = "partes", "cada"
    modo = forms.ChoiceField(label="Cómo dividir", initial=PARTES, widget=forms.RadioSelect,
                             choices=[(PARTES, "En partes iguales"), (CADA, "Cada cierto número de plantas")])
    valor = _entero("Cantidad")
    con_marcadores = forms.BooleanField(label="Crear un marcador al inicio de cada segmento y uno al final de la hilera",
                                        required=False, initial=True)


class MarcadorForm(_Catalogo):
    code = forms.CharField(label="Código", max_length=40, widget=forms.TextInput(attrs={"placeholder": "M1"}))
    position = forms.ChoiceField(label="Posición", choices=MarkerPosition.choices)
    segment = forms.ChoiceField(label="Segmento", required=False)
    description = forms.CharField(label="Descripción", max_length=200, required=False,
                                  widget=forms.TextInput(attrs={"placeholder": "Poste con cinta roja"}))
    lat = forms.FloatField(label="Latitud", required=False, widget=forms.NumberInput(attrs={
        "step": "any", "inputmode": "decimal", "placeholder": "-14.0600"}))
    lon = forms.FloatField(label="Longitud", required=False, widget=forms.NumberInput(attrs={
        "step": "any", "inputmode": "decimal", "placeholder": "-75.7300"}))

    def __init__(self, *args, segmentos=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["segment"].choices = [("", "— Sin segmento —")] + [
            (s.pk, f"{s.code} (plantas {s.start_plant}–{s.end_plant})") for s in segmentos]
