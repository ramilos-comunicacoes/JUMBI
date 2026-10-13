from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from .niches import PRACTICE_AREA_LABELS, validate_practice_areas


hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Informe uma cor hexadecimal no formato #RRGGBB.",
)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("O e-mail e obrigatorio.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("Superusuario deve ter is_staff=True e is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField("e-mail", unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email


class Organization(models.Model):
    class BusinessType(models.TextChoices):
        OFFICE = "office", "Jurídico"
        ENGINEERING = "engineering", "Engenharia"
        AGRO = "agro", "Agro"
        RETAIL = "retail", "Varejo"
        OTHER = "other", "Outro"

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        SUSPENDED = "suspended", "Suspensa"

    name = models.CharField("nome", max_length=150)
    slug = models.SlugField(unique=True)
    legal_name = models.CharField("razao social", max_length=200, blank=True)
    document = models.CharField("CNPJ/CPF", max_length=18, blank=True)
    business_type = models.CharField("segmento", max_length=20, choices=BusinessType.choices, default=BusinessType.OTHER)
    status = models.CharField("status", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    contact_email = models.EmailField("e-mail de contato", blank=True)
    contact_phone = models.CharField("telefone", max_length=30, blank=True)
    practice_areas = models.JSONField("áreas de atuação", default=list, db_default=[], blank=True, validators=[validate_practice_areas])
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    brand_logo = models.FileField(
        "logo da organização",
        upload_to="organization-logos/%Y/%m/",
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=("png", "jpg", "jpeg", "webp"))],
    )
    brand_primary_color = models.CharField(
        "cor principal",
        max_length=7,
        default="#F5A000",
        validators=[hex_color_validator],
    )
    brand_accent_color = models.CharField(
        "cor de destaque",
        max_length=7,
        default="#0F4050",
        validators=[hex_color_validator],
    )
    brand_sidebar_color = models.CharField(
        "cor do menu lateral",
        max_length=7,
        default="#0B1320",
        validators=[hex_color_validator],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def practice_area_labels(self):
        return [PRACTICE_AREA_LABELS[code] for code in self.practice_areas if code in PRACTICE_AREA_LABELS]


class OrganizationRole(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField("nome do cargo", max_length=100)
    description = models.CharField("responsabilidades", max_length=240, blank=True)
    hierarchy_level = models.PositiveSmallIntegerField(
        "nível hierárquico",
        help_text="Números menores representam cargos mais altos. Ex.: CEO e gerente 10, funcionário 70.",
    )
    permission_role = models.CharField(
        "perfil de permissões",
        max_length=20,
        choices=(
            ("owner", "Direção / controle total"),
            ("manager", "Gestão"),
            ("operator", "Operação"),
            ("viewer", "Somente consulta"),
        ),
        default="operator",
    )
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["hierarchy_level", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_organization_role_name"),
        ]

    def __str__(self):
        return f"{self.name} · {self.organization}"


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Proprietario"
        MANAGER = "manager", "Gestor"
        OPERATOR = "operator", "Operador"
        VIEWER = "viewer", "Consulta"
        CLIENT = "client", "Cliente · portal"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATOR)
    position = models.ForeignKey(
        OrganizationRole,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
        verbose_name="cargo",
    )
    reports_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_reports",
        verbose_name="gestor direto",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_organization_membership")]

    def __str__(self):
        return f"{self.user} em {self.organization}"


class AuditLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    action = models.CharField(max_length=140)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.action} em {self.organization}"


class WorkspaceInvitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="workspace_invitations")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Membership.Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_workspace_invitations")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
