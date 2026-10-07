from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import OrganizationBrandingForm
from .models import AuditLog, Membership, Organization, OrganizationRole, User
from apps.agro.models import AgroFinanceEntry, AgroPurchase, Farm, FarmOperation, Field, InventoryItem, StaffMember as AgroStaffMember, Supplier as AgroSupplier
from apps.engineering.models import Employee, FinanceEntry, Project, ProjectEvidence, ProjectTask, Purchase, Supplier
from apps.office.models import (
    Client,
    LegalCase,
    MatterType,
    OfficeFinanceEntry,
    OfficePurchase,
    PracticeArea,
    StaffMember,
    WorkItem,
)
from apps.pages.models import DemoRequest


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"], JUMBI_LEGAL_ONLY=False)
class AuthenticationFlowTests(TestCase):
    def test_owner_can_create_hierarchy_and_personal_login(self):
        owner = User.objects.create_user(email="owner-hierarchy@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Hierarquia",
            slug="escritorio-hierarquia-owner",
            business_type=Organization.BusinessType.OFFICE,
        )
        owner_membership = Membership.objects.create(
            user=owner,
            organization=organization,
            role=Membership.Role.OWNER,
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("office:section", args=["accesses"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hierarquia e acessos")
        self.assertEqual(OrganizationRole.objects.filter(organization=organization).count(), 5)
        owner_membership.refresh_from_db()
        self.assertIsNotNone(owner_membership.position)

        response = self.client.post(reverse("office:section", args=["accesses"]), {
            "action": "hierarchy_role",
            "hierarchy-name": "Coordenador jurídico",
            "hierarchy-hierarchy_level": "40",
            "hierarchy-permission_role": Membership.Role.MANAGER,
            "hierarchy-description": "Coordena equipes, processos e prazos.",
        })
        self.assertRedirects(response, reverse("office:section", args=["accesses"]))
        position = OrganizationRole.objects.get(
            organization=organization,
            name="Coordenador jurídico",
        )

        response = self.client.post(reverse("office:section", args=["accesses"]), {
            "action": "organization_member",
            "member-first_name": "Marina",
            "member-last_name": "Silva",
            "member-email": "marina.hierarquia@example.com",
            "member-position": position.id,
            "member-reports_to": owner_membership.id,
            "member-temporary_password": "Temp-Djumbi!2026#Marina",
        })
        self.assertRedirects(response, reverse("office:section", args=["accesses"]))
        membership = Membership.objects.select_related("user", "position", "reports_to").get(
            organization=organization,
            user__email="marina.hierarquia@example.com",
        )
        self.assertEqual(membership.position, position)
        self.assertEqual(membership.role, Membership.Role.MANAGER)
        self.assertEqual(membership.reports_to, owner_membership)
        self.assertTrue(membership.user.check_password("Temp-Djumbi!2026#Marina"))
        self.assertTrue(AuditLog.objects.filter(
            organization=organization,
            action="core.membership.created",
        ).exists())
        self.client.logout()
        response = self.client.post(reverse("core:login"), {
            "username": "marina.hierarquia@example.com",
            "password": "Temp-Djumbi!2026#Marina",
        })
        self.assertRedirects(response, reverse("office:workspace"))

    def test_operator_cannot_open_hierarchy_management(self):
        operator = User.objects.create_user(email="operator-hierarchy@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Fazenda Hierarquia",
            slug="fazenda-hierarquia",
            business_type=Organization.BusinessType.AGRO,
        )
        Membership.objects.create(
            user=operator,
            organization=organization,
            role=Membership.Role.OPERATOR,
        )
        self.client.force_login(operator)

        response = self.client.get(reverse("agro:section", args=["accesses"]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(OrganizationRole.objects.filter(organization=organization).exists())

    def test_manager_cannot_grant_or_change_direction_access(self):
        manager = User.objects.create_user(email="manager-hierarchy@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Hierarquia",
            slug="escritorio-hierarquia",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(
            user=manager,
            organization=organization,
            role=Membership.Role.MANAGER,
        )
        self.client.force_login(manager)
        self.client.get(reverse("office:section", args=["accesses"]))
        direction_role = OrganizationRole.objects.get(
            organization=organization,
            permission_role=Membership.Role.OWNER,
        )

        response = self.client.post(reverse("office:section", args=["accesses"]), {
            "action": "hierarchy_role",
            "hierarchy-name": "Direção paralela",
            "hierarchy-hierarchy_level": "10",
            "hierarchy-permission_role": Membership.Role.OWNER,
            "hierarchy-description": "Não deve ser criada.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(OrganizationRole.objects.filter(
            organization=organization,
            name="Direção paralela",
        ).exists())

        response = self.client.post(reverse("office:section", args=["accesses"]), {
            "action": "hierarchy_status",
            "role_id": direction_role.id,
            "is_active": "false",
        })
        self.assertEqual(response.status_code, 403)
        direction_role.refresh_from_db()
        self.assertTrue(direction_role.is_active)

    def test_public_home_exposes_the_legal_platform(self):
        response = self.client.get(reverse("pages:home"))
        self.assertContains(response, "Seu escritório sob controle.")
        self.assertContains(response, "JUMBI GESTÃO JURÍDICA")
        self.assertContains(response, "Cada informação no lugar certo. Cada decisão com contexto.")
        self.assertContains(response, 'class="legal-suite-layout"')
        self.assertNotContains(response, "Tudo o que move o escritório, em um só lugar.")
        self.assertNotContains(response, "DJUMBI ENGENHARIA")
        self.assertNotContains(response, "DJUMBI AGRO")
        self.assertContains(response, "nabiodev@gmail.com")
        self.assertContains(response, "5588993345111")
        self.assertContains(response, 'href="/entrar/"', count=2)

    def test_legacy_access_page_redirects_to_the_single_login(self):
        response = self.client.get(reverse("core:access"))
        self.assertRedirects(response, reverse("core:login"))

    def test_single_login_routes_user_to_the_legal_workspace(self):
        user = User.objects.create_user(email="segment@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Login", slug="escritorio-login-unico", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        response = self.client.post(reverse("core:login"), {
            "username": user.email,
            "password": "aH7$B1pQ!kL9zX",
        })
        self.assertRedirects(response, reverse("office:workspace"))
        self.assertEqual(self.client.session["active_organization_id"], organization.id)

    def test_superuser_login_always_routes_to_platform_control(self):
        user = User.objects.create_superuser(email="root@example.com", password="aH7$B1pQ!kL9zX")
        response = self.client.post(reverse("core:login"), {
            "username": user.email,
            "password": "aH7$B1pQ!kL9zX",
        })
        self.assertRedirects(response, reverse("core:control-panel"))

    def test_invalid_contextual_segment_is_not_available(self):
        response = self.client.get(reverse("core:segment-login", args=["desconhecido"]))
        self.assertEqual(response.status_code, 404)

    def test_demo_request_is_saved(self):
        response = self.client.post(reverse("pages:demo-request"), {
            "name": "Ana Silva",
            "work_email": "ana@empresa.test",
            "company": "Empresa Teste",
            "segment": "juridico",
            "message": "Preciso organizar os processos.",
        })
        self.assertRedirects(response, reverse("pages:demo-request"))
        self.assertEqual(DemoRequest.objects.count(), 1)

    def test_public_signup_redirects_to_the_guided_implementation_flow(self):
        response = self.client.get(reverse("core:signup"))
        self.assertRedirects(response, reverse("pages:demo-request"))
        self.assertEqual(User.objects.count(), 0)

    def test_dashboard_requires_authentication(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(response, f"{reverse('core:login')}?next={reverse('core:dashboard')}")

    def test_user_can_log_in_with_email(self):
        user = User.objects.create_user(email="login@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Login", slug="escritorio-login", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        response = self.client.post(reverse("core:login"), {"username": "login@example.com", "password": "aH7$B1pQ!kL9zX"})
        self.assertRedirects(response, reverse("office:workspace"))

    def test_authenticated_user_can_change_password(self):
        user = User.objects.create_user(email="security@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Segurança", slug="escritorio-seguranca", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)
        response = self.client.post(reverse("core:password-change"), {
            "old_password": "aH7$B1pQ!kL9zX", "new_password1": "S9!secure-Password-2026", "new_password2": "S9!secure-Password-2026",
        })
        user.refresh_from_db()
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertTrue(user.check_password("S9!secure-Password-2026"))

    def test_only_superuser_can_access_platform_control(self):
        user = User.objects.create_user(email="member@example.com", password="aH7$B1pQ!kL9zX")
        self.client.force_login(user)
        response = self.client.get(reverse("core:control-panel"))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_register_an_organization(self):
        user = User.objects.create_superuser(email="admin@example.com", password="aH7$B1pQ!kL9zX")
        self.client.force_login(user)
        response = self.client.post(reverse("core:control-panel"), {
            "action": "organization",
            "organization-name": "Advocacia Modelo",
            "organization-legal_name": "Advocacia Modelo Sociedade de Advogados",
            "organization-document": "12345678000199",
            "organization-business_type": Organization.BusinessType.OFFICE,
            "organization-contact_email": "contato@advocacia.test",
            "organization-contact_phone": "85999999999",
            "organization-city": "Fortaleza",
            "organization-state": "ce",
            "organization-status": Organization.Status.ACTIVE,
        })
        organization = Organization.objects.get(name="Advocacia Modelo")
        self.assertRedirects(response, reverse("core:control-section", args=["organizations"]))
        self.assertEqual(organization.slug, "advocacia-modelo")
        self.assertEqual(organization.state, "CE")

    def test_office_data_is_isolated_to_selected_organization(self):
        user = User.objects.create_user(email="ana@example.com", password="aH7$B1pQ!kL9zX")
        first = Organization.objects.create(name="Empresa A", slug="empresa-a", business_type=Organization.BusinessType.OFFICE)
        second = Organization.objects.create(name="Empresa B", slug="empresa-b", business_type=Organization.BusinessType.OFFICE)
        Membership.objects.create(user=user, organization=first, role=Membership.Role.OWNER)
        Membership.objects.create(user=user, organization=second, role=Membership.Role.OWNER)
        Client.objects.create(organization=first, name="Cliente A")
        Client.objects.create(organization=second, name="Cliente B")
        self.client.force_login(user)
        session = self.client.session
        session["active_organization_id"] = second.id
        session.save()
        response = self.client.get(reverse("office:section", args=["clients"]))
        self.assertContains(response, "Cliente B")
        self.assertNotContains(response, "Cliente A")

    def test_user_cannot_open_a_product_that_was_not_contracted(self):
        user = User.objects.create_user(email="advogado@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jurídico Exclusivo", slug="juridico-exclusivo", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("office:workspace")).status_code, 200)
        self.assertEqual(self.client.get(reverse("engineering:workspace")).status_code, 403)
        self.assertEqual(self.client.get(reverse("agro:workspace")).status_code, 403)

    def test_each_product_exposes_its_management_sections(self):
        user = User.objects.create_user(email="sections@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jurídico Seções", slug="juridico-secoes", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)
        for section in ("clients", "cases", "tasks", "documents", "finance", "staff", "purchases"):
            with self.subTest(section=section):
                self.assertEqual(self.client.get(reverse("office:section", args=[section])).status_code, 200)

    def test_inactive_membership_cannot_access_organization_data(self):
        user = User.objects.create_user(email="inactive@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Empresa Pausada", slug="empresa-pausada", business_type=Organization.BusinessType.ENGINEERING
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER, is_active=False)
        self.client.force_login(user)
        response = self.client.get(reverse("engineering:workspace"))
        self.assertEqual(response.status_code, 403)

    def test_engineering_status_transition_is_scoped_and_audited(self):
        user = User.objects.create_user(email="obra@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Construtora A", slug="construtora-a", business_type=Organization.BusinessType.ENGINEERING)
        other_organization = Organization.objects.create(name="Construtora B", slug="construtora-b", business_type=Organization.BusinessType.ENGINEERING)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        project = Project.objects.create(organization=organization, name="Edificio Norte")
        other_project = Project.objects.create(organization=other_organization, name="Galpao Sul")
        self.client.force_login(user)

        response = self.client.post(reverse("engineering:project-status", args=[project.id]), {"status": Project.Status.ACTIVE})
        project.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(project.status, Project.Status.ACTIVE)
        self.assertEqual(AuditLog.objects.filter(organization=organization, action="engineering.project.status_changed").count(), 1)

        response = self.client.post(reverse("engineering:project-status", args=[other_project.id]), {"status": Project.Status.ACTIVE})
        self.assertEqual(response.status_code, 400)
        other_project.refresh_from_db()
        self.assertEqual(other_project.status, Project.Status.PLANNING)

    def test_engineering_workspace_creates_task_and_evidence(self):
        user = User.objects.create_user(email="campo@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Construtora Campo", slug="construtora-campo", business_type=Organization.BusinessType.ENGINEERING)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        project = Project.objects.create(organization=organization, name="Obra Campo")
        self.client.force_login(user)

        response = self.client.get(reverse("engineering:section", args=["tasks"]))
        self.assertContains(response, "Tarefas e Kanban")

        response = self.client.post(reverse("engineering:workspace"), {
            "action": "task",
            "task-project": project.id,
            "task-title": "Conferir concretagem",
            "task-description": "Validar equipe e fotos do campo.",
            "task-priority": ProjectTask.Priority.HIGH,
            "task-due_date": "2026-08-01",
            "task-assignee": user.id,
        })
        self.assertRedirects(response, reverse("engineering:workspace"))
        task = ProjectTask.objects.get(title="Conferir concretagem")
        self.assertEqual(task.organization, organization)
        self.assertEqual(task.created_by, user)

        response = self.client.post(reverse("engineering:workspace"), {
            "action": "evidence",
            "evidence-project": project.id,
            "evidence-task": task.id,
            "evidence-title": "Fotos da concretagem",
            "evidence-notes": "Registro operacional de teste.",
        })
        self.assertRedirects(response, reverse("engineering:workspace"))
        self.assertEqual(ProjectEvidence.objects.filter(project=project, task=task).count(), 1)

    def test_engineering_workspace_creates_management_records(self):
        user = User.objects.create_user(email="gestao-obra@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Construtora Gestao", slug="construtora-gestao", business_type=Organization.BusinessType.ENGINEERING)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        project = Project.objects.create(organization=organization, name="Torre Central")
        supplier = Supplier.objects.create(organization=organization, name="Aco Premium")
        self.client.force_login(user)

        response = self.client.post(reverse("engineering:workspace"), {
            "action": "employee",
            "employee-name": "Carlos Engenharia",
            "employee-role": Employee.Role.ENGINEER,
            "employee-email": "carlos@example.com",
            "employee-phone": "(85) 99999-0001",
            "employee-project": project.id,
        })
        self.assertRedirects(response, reverse("engineering:workspace"))

        response = self.client.post(reverse("engineering:workspace"), {
            "action": "finance",
            "finance-project": project.id,
            "finance-kind": FinanceEntry.Kind.EXPENSE,
            "finance-description": "Compra de aco",
            "finance-amount": "25000.00",
            "finance-status": FinanceEntry.Status.OPEN,
        })
        self.assertRedirects(response, reverse("engineering:workspace"))

        response = self.client.post(reverse("engineering:workspace"), {
            "action": "purchase",
            "purchase-project": project.id,
            "purchase-supplier": supplier.id,
            "purchase-item": "Vergalhao CA-50",
            "purchase-quantity": "100.00",
            "purchase-total_amount": "25000.00",
            "purchase-status": Purchase.Status.APPROVED,
        })
        self.assertRedirects(response, reverse("engineering:workspace"))
        self.assertEqual(Employee.objects.filter(organization=organization).count(), 1)
        self.assertEqual(FinanceEntry.objects.filter(organization=organization).count(), 1)
        self.assertEqual(Purchase.objects.filter(organization=organization).count(), 1)

    def test_office_workspace_creates_core_management_records(self):
        user = User.objects.create_user(email="juridico@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Escritorio Juridico", slug="escritorio-juridico", business_type=Organization.BusinessType.OFFICE)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        client = Client.objects.create(organization=organization, name="Cliente Juridico")
        self.client.force_login(user)

        response = self.client.post(reverse("office:workspace"), {
            "action": "staff",
            "staff-name": "Dra. Paula",
            "staff-role": StaffMember.Role.LAWYER,
            "staff-email": "paula@example.com",
            "staff-phone": "(85) 99999-0002",
        })
        self.assertRedirects(response, reverse("office:workspace"))
        staff = StaffMember.objects.get(organization=organization)

        response = self.client.post(reverse("office:workspace"), {
            "action": "case",
            "case-client": client.id,
            "case-title": "Acao de cobranca",
            "case-case_number": "0001234-00.2026.8.06.0001",
            "case-court": "TJCE",
            "case-status": LegalCase.Status.ACTIVE,
            "case-responsible": staff.id,
        })
        self.assertRedirects(response, reverse("office:workspace"))
        legal_case = LegalCase.objects.get(organization=organization)

        response = self.client.post(reverse("office:workspace"), {
            "action": "finance",
            "finance-client": client.id,
            "finance-case": legal_case.id,
            "finance-kind": OfficeFinanceEntry.Kind.REVENUE,
            "finance-description": "Honorarios iniciais",
            "finance-amount": "3500.00",
        })
        self.assertRedirects(response, reverse("office:workspace"))

        response = self.client.post(reverse("office:workspace"), {
            "action": "purchase",
            "purchase-supplier_name": "Papelaria Central",
            "purchase-item": "Material de escritorio",
            "purchase-amount": "420.00",
        })
        self.assertRedirects(response, reverse("office:workspace"))
        self.assertEqual(OfficeFinanceEntry.objects.filter(organization=organization).count(), 1)
        self.assertEqual(OfficePurchase.objects.filter(organization=organization).count(), 1)

    def test_agro_workspace_creates_operations_inventory_and_finance(self):
        user = User.objects.create_user(email="agro@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Fazenda Teste", slug="fazenda-teste", business_type=Organization.BusinessType.AGRO)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        farm = Farm.objects.create(organization=organization, name="Fazenda Sede", total_area_hectares="300.00")
        field = Field.objects.create(farm=farm, name="Talhao 1", crop="Milho", area_hectares="80.00")
        self.client.force_login(user)

        response = self.client.post(reverse("agro:workspace"), {
            "action": "staff",
            "staff-name": "Ana Agronoma",
            "staff-role": AgroStaffMember.Role.AGRONOMIST,
            "staff-email": "ana@example.com",
            "staff-phone": "(85) 99999-0003",
            "staff-farm": farm.id,
        })
        self.assertRedirects(response, reverse("agro:workspace"))
        staff = AgroStaffMember.objects.get(organization=organization)

        response = self.client.post(reverse("agro:workspace"), {
            "action": "supplier",
            "supplier-name": "Agro Insumos",
            "supplier-document": "11.222.333/0001-44",
            "supplier-email": "comercial@agro.test",
            "supplier-phone": "(85) 99999-0004",
        })
        self.assertRedirects(response, reverse("agro:workspace"))
        supplier = AgroSupplier.objects.get(organization=organization)

        response = self.client.post(reverse("agro:workspace"), {
            "action": "inventory",
            "inventory-name": "Fertilizante NPK",
            "inventory-category": "Fertilizantes",
            "inventory-unit": InventoryItem.Unit.BAG,
            "inventory-stock": "20.00",
            "inventory-minimum_stock": "30.00",
        })
        self.assertRedirects(response, reverse("agro:workspace"))
        item = InventoryItem.objects.get(organization=organization)

        response = self.client.post(reverse("agro:workspace"), {
            "action": "operation",
            "operation-farm": farm.id,
            "operation-field": field.id,
            "operation-kind": FarmOperation.Kind.SOIL,
            "operation-title": "Correcao de solo",
            "operation-status": FarmOperation.Status.RUNNING,
            "operation-responsible": staff.id,
            "operation-notes": "Aplicacao inicial.",
        })
        self.assertRedirects(response, reverse("agro:workspace"))

        response = self.client.post(reverse("agro:workspace"), {
            "action": "finance",
            "finance-farm": farm.id,
            "finance-field": field.id,
            "finance-kind": AgroFinanceEntry.Kind.EXPENSE,
            "finance-description": "Compra de fertilizante",
            "finance-amount": "7400.00",
        })
        self.assertRedirects(response, reverse("agro:workspace"))

        response = self.client.post(reverse("agro:workspace"), {
            "action": "purchase",
            "purchase-supplier": supplier.id,
            "purchase-item": item.id,
            "purchase-description": "Compra NPK",
            "purchase-quantity": "40.00",
            "purchase-total_amount": "7400.00",
        })
        self.assertRedirects(response, reverse("agro:workspace"))
        self.assertEqual(FarmOperation.objects.filter(organization=organization).count(), 1)
        self.assertEqual(AgroFinanceEntry.objects.filter(organization=organization).count(), 1)
        self.assertEqual(AgroPurchase.objects.filter(organization=organization).count(), 1)

    def test_office_task_status_transition_is_audited(self):
        user = User.objects.create_user(email="office-status@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jurídico Status", slug="juridico-status", business_type=Organization.BusinessType.OFFICE
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        task = WorkItem.objects.create(organization=organization, title="Protocolar petição")
        self.client.force_login(user)

        response = self.client.post(
            reverse("office:task-status", args=[task.id]),
            {"status": WorkItem.Status.IN_PROGRESS},
        )
        task.refresh_from_db()
        self.assertRedirects(response, reverse("office:section", args=["tasks"]))
        self.assertEqual(task.status, WorkItem.Status.IN_PROGRESS)
        self.assertEqual(
            AuditLog.objects.filter(organization=organization, action="office.workitem.status_changed").count(),
            1,
        )

    def test_agro_operation_status_transition_is_audited(self):
        user = User.objects.create_user(email="agro-status@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Agro Status", slug="agro-status", business_type=Organization.BusinessType.AGRO
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        farm = Farm.objects.create(organization=organization, name="Fazenda Status")
        operation = FarmOperation.objects.create(
            organization=organization,
            farm=farm,
            title="Preparar solo",
            status=FarmOperation.Status.PLANNED,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("agro:operation-status", args=[operation.id]),
            {"status": FarmOperation.Status.RUNNING},
        )
        operation.refresh_from_db()
        self.assertRedirects(response, reverse("agro:section", args=["operations"]))
        self.assertEqual(operation.status, FarmOperation.Status.RUNNING)
        self.assertEqual(
            AuditLog.objects.filter(organization=organization, action="agro.farmoperation.status_changed").count(),
            1,
        )

    def test_superuser_can_create_a_login_already_bound_to_a_legal_office(self):
        admin = User.objects.create_superuser(email="provision@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Cliente Jurídico", slug="cliente-juridico", business_type=Organization.BusinessType.OFFICE
        )
        self.client.force_login(admin)
        response = self.client.post(reverse("core:control-section", args=["accesses"]), {
            "action": "access",
            "access-first_name": "Carlos",
            "access-last_name": "Advogado",
            "access-email": "carlos@cliente.test",
            "access-organization": organization.id,
            "access-role": Membership.Role.MANAGER,
            "access-temporary_password": "Temp-Djumbi!2026#Carlos",
        })
        self.assertRedirects(response, reverse("core:control-section", args=["accesses"]))
        user = User.objects.get(email="carlos@cliente.test")
        self.assertTrue(user.check_password("Temp-Djumbi!2026#Carlos"))
        self.assertTrue(Membership.objects.filter(
            user=user,
            organization=organization,
            role=Membership.Role.MANAGER,
            is_active=True,
        ).exists())

    def test_workspace_navigation_uses_htmx_and_responsive_brand_assets(self):
        user = User.objects.create_user(email="brand-owner@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Escritório Marca",
            slug="escritorio-marca",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)

        response = self.client.get(reverse("office:section", args=["settings"]))

        self.assertContains(response, 'id="sidebar-nav"')
        self.assertContains(response, 'hx-target="#app-main"')
        self.assertContains(response, 'hx-select="#app-main"')
        self.assertContains(response, 'hx-push-url="true"')
        self.assertContains(response, "js/htmx.min.js")
        self.assertContains(response, "sidebar-logo-mark")
        self.assertContains(response, "sidebar-logo-full")
        self.assertContains(response, "Personalização")
        self.assertNotContains(response, "organization-context")
        self.assertNotContains(response, "Conta ativa")

        htmx_response = self.client.get(
            reverse("office:section", args=["clients"]),
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(htmx_response, 'id="app-main"')
        self.assertContains(htmx_response, 'hx-swap-oob="outerHTML"')

    def test_manager_can_update_organization_branding_with_audit_log(self):
        user = User.objects.create_user(email="brand-manager@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Construtora Marca",
            slug="construtora-marca",
            business_type=Organization.BusinessType.ENGINEERING,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        self.client.force_login(user)

        response = self.client.post(reverse("engineering:section", args=["settings"]), {
            "action": "branding",
            "branding-brand_primary_color": "#22C55E",
            "branding-brand_accent_color": "#14532D",
            "branding-brand_sidebar_color": "#07140D",
        })

        self.assertRedirects(response, reverse("engineering:section", args=["settings"]))
        organization.refresh_from_db()
        self.assertEqual(organization.brand_primary_color, "#22C55E")
        self.assertEqual(organization.brand_accent_color, "#14532D")
        self.assertEqual(organization.brand_sidebar_color, "#07140D")
        self.assertTrue(AuditLog.objects.filter(
            organization=organization,
            actor=user,
            action="core.organization.branding_changed",
        ).exists())

    def test_operator_cannot_change_organization_branding(self):
        user = User.objects.create_user(email="brand-operator@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Fazenda Marca",
            slug="fazenda-marca",
            business_type=Organization.BusinessType.AGRO,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        self.client.force_login(user)

        response = self.client.post(reverse("agro:section", args=["settings"]), {
            "action": "branding",
            "branding-brand_primary_color": "#22C55E",
            "branding-brand_accent_color": "#14532D",
            "branding-brand_sidebar_color": "#07140D",
        })

        self.assertEqual(response.status_code, 403)
        organization.refresh_from_db()
        self.assertEqual(organization.brand_primary_color, "#F5A000")
        self.assertFalse(AuditLog.objects.filter(organization=organization).exists())

    def test_branding_form_rejects_a_fake_image(self):
        organization = Organization(
            name="Marca Segura",
            slug="marca-segura",
            business_type=Organization.BusinessType.OFFICE,
        )
        fake_logo = SimpleUploadedFile("logo.png", b"not-a-real-image", content_type="image/png")
        form = OrganizationBrandingForm(
            data={
                "brand_primary_color": "#F5A000",
                "brand_accent_color": "#0F4050",
                "brand_sidebar_color": "#0B1320",
            },
            files={"brand_logo": fake_logo},
            instance=organization,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("brand_logo", form.errors)

    def test_engineering_task_status_transition_is_audited(self):
        user = User.objects.create_user(email="task-status@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Construtora Task", slug="construtora-task", business_type=Organization.BusinessType.ENGINEERING)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        project = Project.objects.create(organization=organization, name="Obra Task")
        task = ProjectTask.objects.create(organization=organization, project=project, title="Acompanhar montagem")
        self.client.force_login(user)

        response = self.client.post(reverse("engineering:task-status", args=[task.id]), {"status": ProjectTask.Status.DOING})
        task.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(task.status, ProjectTask.Status.DOING)
        self.assertEqual(AuditLog.objects.filter(organization=organization, action="engineering.projecttask.status_changed").count(), 1)

    def test_viewer_cannot_change_engineering_project_status(self):
        user = User.objects.create_user(email="viewer@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(name="Construtora Viewer", slug="construtora-viewer", business_type=Organization.BusinessType.ENGINEERING)
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.VIEWER)
        project = Project.objects.create(organization=organization, name="Obra Restrita")
        self.client.force_login(user)

        response = self.client.post(reverse("engineering:project-status", args=[project.id]), {"status": Project.Status.ACTIVE})
        project.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(project.status, Project.Status.PLANNING)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_seed_command_creates_one_legal_demo_organization(self):
        output = StringIO()
        call_command("seed_demo", "--email", "demo@example.com", "--password", "aH7$B1pQ!kL9zX", stdout=output)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertTrue(User.objects.get(email="demo@example.com").is_superuser)
        self.assertEqual(LegalCase.objects.count(), 1)
        self.assertEqual(OfficePurchase.objects.count(), 1)
        self.assertEqual(LegalCase.objects.get().practice_area.slug, "contratos")
        self.assertEqual(LegalCase.objects.get().matter_type.slug, "revisao-negociacao")
        self.assertEqual(WorkItem.objects.get().case, LegalCase.objects.get())


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"], JUMBI_LEGAL_ONLY=True)
class LegalOnlyProductTests(TestCase):
    def test_legal_workspace_is_canonical(self):
        self.assertEqual(reverse("office:workspace"), "/juridico/")

    def test_legacy_products_redirect_to_jumbi_legal(self):
        user = User.objects.create_superuser(email="root-legal@example.com", password="aH7$B1pQ!kL9zX")
        self.client.force_login(user)

        for route in ("engineering:workspace", "agro:workspace"):
            with self.subTest(route=route):
                self.assertRedirects(
                    self.client.get(reverse(route)),
                    reverse("office:workspace"),
                    fetch_redirect_response=False,
                )

    def test_legacy_account_cannot_log_into_the_legal_only_product(self):
        user = User.objects.create_user(email="legacy@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Conta Legada",
            slug="conta-legada",
            business_type=Organization.BusinessType.ENGINEERING,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)

        response = self.client.post(reverse("core:login"), {
            "username": user.email,
            "password": "aH7$B1pQ!kL9zX",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ainda não possui um ambiente Jumbi Jurídico ativo")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_legal_workspace_exposes_the_new_operational_dashboard(self):
        user = User.objects.create_user(email="workspace-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Advocacia",
            slug="jumbi-advocacia",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)

        response = self.client.get(reverse("office:workspace"))

        self.assertContains(response, "legal-metric-strip")
        self.assertContains(response, "CARTEIRA JURÍDICA")
        self.assertContains(response, "Distribuição dos processos")
        self.assertNotContains(response, "Pousada")
        self.assertNotContains(response, "Reserva")

    def test_every_legal_module_has_a_clear_return_to_overview(self):
        user = User.objects.create_user(email="navigation-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Navegação",
            slug="jumbi-navegacao",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)

        for section in ("clients", "cases", "practice", "tasks", "documents", "finance", "staff", "purchases", "accesses", "settings"):
            with self.subTest(section=section):
                response = self.client.get(
                    reverse("office:section", args=[section]),
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="legal-section-return"')
                self.assertContains(response, 'data-app-home')
                self.assertContains(response, 'href="/juridico/"')
                self.assertContains(response, f'data-module="{section}"')

    def test_legal_catalog_covers_major_practice_areas_and_workflows(self):
        user = User.objects.create_user(email="catalog-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Multidisciplinar",
            slug="jumbi-multidisciplinar",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        self.client.force_login(user)

        response = self.client.get(reverse("office:section", args=["practice"]))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(PracticeArea.objects.filter(is_active=True).count(), 20)
        self.assertGreaterEqual(MatterType.objects.filter(is_active=True).count(), 60)
        self.assertContains(response, "Previdenciário")
        self.assertContains(response, "Registro de marca")
        self.assertContains(response, "Ação penal")
        self.assertContains(response, "Fluxo sugerido")
        self.assertContains(response, "Documentos iniciais")

    def test_case_template_creates_a_tenant_scoped_operational_checklist(self):
        user = User.objects.create_user(email="workflow-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Previdenciário",
            slug="jumbi-previdenciario",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        client = Client.objects.create(organization=organization, name="Maria Segurada")
        area = PracticeArea.objects.get(slug="previdenciario")
        matter_type = MatterType.objects.get(practice_area=area, slug="aposentadoria")
        self.client.force_login(user)

        response = self.client.post(reverse("office:section", args=["practice"]), {
            "action": "case",
            "case-client": client.id,
            "case-title": "Planejamento e aposentadoria de Maria",
            "case-practice_area": area.id,
            "case-matter_type": matter_type.id,
            "case-nature": LegalCase.Nature.ADMINISTRATIVE,
            "case-stage": LegalCase.Stage.INTAKE,
            "case-priority": LegalCase.Priority.HIGH,
            "case-status": LegalCase.Status.INTAKE,
            "case-create_initial_checklist": "on",
        })

        self.assertRedirects(response, reverse("office:section", args=["practice"]))
        legal_case = LegalCase.objects.get(organization=organization)
        checklist = WorkItem.objects.filter(organization=organization, case=legal_case)
        self.assertEqual(legal_case.practice_area, area)
        self.assertEqual(legal_case.matter_type, matter_type)
        self.assertEqual(checklist.count(), len(matter_type.workflow_steps))
        self.assertTrue(checklist.filter(client=client, owner=user).exists())
        self.assertTrue(AuditLog.objects.filter(
            organization=organization,
            actor=user,
            action="office.legalcase.created",
            metadata__checklist_items=len(matter_type.workflow_steps),
        ).exists())

    def test_case_form_rejects_a_matter_type_from_another_practice_area(self):
        user = User.objects.create_user(email="validation-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Validação",
            slug="jumbi-validacao",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        civil_area = PracticeArea.objects.get(slug="civil")
        criminal_type = MatterType.objects.get(practice_area__slug="criminal", slug="acao-penal")
        self.client.force_login(user)

        response = self.client.post(reverse("office:section", args=["cases"]), {
            "action": "case",
            "case-title": "Classificação inconsistente",
            "case-practice_area": civil_area.id,
            "case-matter_type": criminal_type.id,
            "case-nature": LegalCase.Nature.JUDICIAL,
            "case-stage": LegalCase.Stage.INTAKE,
            "case-priority": LegalCase.Priority.NORMAL,
            "case-status": LegalCase.Status.INTAKE,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "não pertence à área jurídica")
        self.assertFalse(LegalCase.objects.filter(organization=organization).exists())

    def test_operator_cannot_view_or_change_confidential_case_data(self):
        operator = User.objects.create_user(email="operator-confidential@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Sigilo",
            slug="jumbi-sigilo",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=operator, organization=organization, role=Membership.Role.OPERATOR)
        confidential_case = LegalCase.objects.create(
            organization=organization,
            title="Investigação interna reservada",
            confidential=True,
            status=LegalCase.Status.ACTIVE,
        )
        WorkItem.objects.create(
            organization=organization,
            case=confidential_case,
            title="Entrevista protegida",
        )
        OfficeFinanceEntry.objects.create(
            organization=organization,
            case=confidential_case,
            kind=OfficeFinanceEntry.Kind.EXPENSE,
            description="Perícia confidencial",
            amount="800.00",
        )
        self.client.force_login(operator)

        cases_response = self.client.get(reverse("office:section", args=["cases"]))
        tasks_response = self.client.get(reverse("office:section", args=["tasks"]))
        finance_response = self.client.get(reverse("office:section", args=["finance"]))
        status_response = self.client.post(
            reverse("office:case-status", args=[confidential_case.id]),
            {"status": LegalCase.Status.CLOSED},
        )

        self.assertNotContains(cases_response, "Investigação interna reservada")
        self.assertNotContains(tasks_response, "Entrevista protegida")
        self.assertNotContains(finance_response, "Perícia confidencial")
        self.assertEqual(status_response.status_code, 400)
        confidential_case.refresh_from_db()
        self.assertEqual(confidential_case.status, LegalCase.Status.ACTIVE)

    def test_task_form_rejects_a_case_from_another_organization(self):
        user = User.objects.create_user(email="tenant-task@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Jumbi Origem",
            slug="jumbi-origem",
            business_type=Organization.BusinessType.OFFICE,
        )
        other_organization = Organization.objects.create(
            name="Jumbi Outro Escritório",
            slug="jumbi-outro-escritorio",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.MANAGER)
        other_case = LegalCase.objects.create(
            organization=other_organization,
            title="Caso de outro escritório",
        )
        self.client.force_login(user)

        response = self.client.post(reverse("office:section", args=["tasks"]), {
            "action": "task",
            "task-title": "Vínculo indevido",
            "task-case": other_case.id,
            "task-kind": WorkItem.Kind.TASK,
            "task-priority": WorkItem.Priority.NORMAL,
            "task-status": WorkItem.Status.TODO,
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkItem.objects.filter(organization=organization).exists())

    def test_operator_can_update_legal_operational_statuses_with_audit(self):
        user = User.objects.create_user(email="operator-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Operação Jurídica",
            slug="operacao-juridica",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
        legal_case = LegalCase.objects.create(
            organization=organization,
            title="Ação de cobrança",
            status=LegalCase.Status.ACTIVE,
        )
        finance_entry = OfficeFinanceEntry.objects.create(
            organization=organization,
            kind=OfficeFinanceEntry.Kind.REVENUE,
            description="Honorários iniciais",
            amount="3500.00",
            paid=False,
        )
        purchase = OfficePurchase.objects.create(
            organization=organization,
            supplier_name="Certificadora",
            item="Certificado digital",
            amount="420.00",
            paid=False,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("office:case-status", args=[legal_case.id]),
            {"status": LegalCase.Status.WAITING},
        )
        self.assertRedirects(response, reverse("office:section", args=["cases"]))
        response = self.client.post(
            reverse("office:finance-paid", args=[finance_entry.id]),
            {"paid": "1"},
        )
        self.assertRedirects(response, reverse("office:section", args=["finance"]))
        response = self.client.post(
            reverse("office:purchase-paid", args=[purchase.id]),
            {"paid": "1"},
        )
        self.assertRedirects(response, reverse("office:section", args=["purchases"]))

        legal_case.refresh_from_db()
        finance_entry.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual(legal_case.status, LegalCase.Status.WAITING)
        self.assertTrue(finance_entry.paid)
        self.assertTrue(purchase.paid)
        self.assertEqual(
            AuditLog.objects.filter(organization=organization, action__contains="status_changed").count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(organization=organization, action__contains="payment_changed").count(),
            2,
        )

    def test_viewer_cannot_change_legal_finance_status(self):
        user = User.objects.create_user(email="viewer-jumbi@example.com", password="aH7$B1pQ!kL9zX")
        organization = Organization.objects.create(
            name="Consulta Jurídica",
            slug="consulta-juridica",
            business_type=Organization.BusinessType.OFFICE,
        )
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.VIEWER)
        finance_entry = OfficeFinanceEntry.objects.create(
            organization=organization,
            kind=OfficeFinanceEntry.Kind.EXPENSE,
            description="Despesa protegida",
            amount="100.00",
            paid=False,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("office:finance-paid", args=[finance_entry.id]),
            {"paid": "1"},
        )

        finance_entry.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(finance_entry.paid)
        self.assertFalse(AuditLog.objects.filter(organization=organization).exists())
