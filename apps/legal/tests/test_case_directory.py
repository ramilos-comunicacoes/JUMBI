from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import Contact, CourtCase, Matter


@override_settings(
    JUMBI_ENFORCE_SUBSCRIPTIONS=False, SECURE_SSL_REDIRECT=False,
    STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class CaseDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Diretório de processos", slug="case-directory", business_type="office", practice_areas=["civil", "familia"])
        cls.other_org = Organization.objects.create(name="Outro escritório", slug="case-directory-other", business_type="office")
        for name, role in (("owner", "owner"), ("operator", "operator"), ("viewer", "viewer"), ("manager", "manager"), ("client_user", "client")):
            user = get_user_model().objects.create_user(email=f"case-{name}@example.test", first_name=f"Equipe {name}")
            setattr(cls, name, user)
            Membership.objects.create(organization=cls.org, user=user, role=role)
        cls.outsider = get_user_model().objects.create_user(email="case-outsider@example.test", first_name="Responsável externo")
        Membership.objects.create(organization=cls.other_org, user=cls.outsider, role="owner")
        cls.client_contact = Contact.objects.create(organization=cls.org, name="Cliente Ágata", kind="person")
        cls.active = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Revisão acessível", client=cls.client_contact, area="civil", status="active")
        cls.waiting = Matter.objects.create(organization=cls.org, owner=cls.operator, title="Pasta de espera", client=cls.client_contact, area="Direito Civil", status="waiting")
        cls.closed = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Pasta concluída", client=cls.client_contact, area="familia", status="closed")
        cls.no_niche = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Pasta sem nicho", status="active")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.manager, title="Pasta confidencial oculta", area="Área industrial sigilosa", confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other_org, owner=cls.outsider, title="Pasta externa", area="Nicho externo")
        cls.first = CourtCase.objects.create(organization=cls.org, matter=cls.active, number="002-ACESSÍVEL", court="Tribunal Aurora", opposing_party="Empresa Delta", notes="Primeira anotação.\n<script>nunca executar</script>")
        cls.second = CourtCase.objects.create(organization=cls.org, matter=cls.waiting, number="001-ESPERA", court="Órgão Boreal", opposing_party="Empresa Eco")
        cls.third = CourtCase.objects.create(organization=cls.org, matter=cls.closed, number="003-CONCLUÍDO")
        cls.fourth = CourtCase.objects.create(organization=cls.org, matter=cls.no_niche, number="004-SEM-NICHO")
        cls.secret_case = CourtCase.objects.create(organization=cls.org, matter=cls.secret, number="099-CONFIDENCIAL", court="Tribunal oculto", opposing_party="Contraparte secreta")
        cls.other_case = CourtCase.objects.create(organization=cls.other_org, matter=cls.other_matter, number="999-EXTERNO", court="Tribunal estrangeiro")
        today = timezone.now()
        for offset, case in enumerate((cls.first, cls.second, cls.third, cls.fourth)):
            CourtCase.objects.filter(pk=case.pk).update(created_at=today + timedelta(minutes=offset))

    def setUp(self):
        self.client.force_login(self.viewer)
        self.url = reverse("legal:list", args=["cases"])

    def screen(self, **params):
        return self.client.get(self.url, params)

    def ids(self, response):
        return [row["record"].pk for row in response.context["case_rows"]]

    def test_counts_rows_and_choices_respect_tenant_and_confidentiality(self):
        response = self.screen()
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "legal/case_directory.html")
        self.assertEqual(response.context["result_total"], 4)
        self.assertEqual(response.context["matter_total"], 4)
        self.assertEqual({s["key"]: s["value"] for s in response.context["case_stats"]}, {"total": 4, "active": 2, "waiting": 1, "closed": 1})
        self.assertEqual({d["key"]: d["count"] for d in response.context["case_distribution"]}, {"civil": 2, "familia": 1, "unassigned": 1})
        self.assertEqual(set(response.context["filter_form"].fields["owner"].queryset), {self.owner, self.operator})
        for text in (self.secret_case.number, self.secret.title, self.secret.area, self.other_case.number, self.other_matter.area, self.outsider.email):
            self.assertNotContains(response, text)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_confidential_membership_is_explicit_even_for_office_owner(self):
        self.client.force_login(self.owner)
        self.assertNotIn(self.secret_case.pk, self.ids(self.screen()))
        self.secret.members.add(self.owner)
        response = self.screen()
        self.assertIn(self.secret_case.pk, self.ids(response))
        self.assertIn(self.manager, response.context["filter_form"].fields["owner"].queryset)
        self.assertContains(response, "Pasta sigilosa")

    def test_each_searchable_field_and_missing_client(self):
        for text, expected in (
            ("002-ACESSÍVEL", [self.first.pk]), ("Ágata", [self.third.pk, self.second.pk, self.first.pk]),
            ("Revisão acessível", [self.first.pk]), ("Aurora", [self.first.pk]), ("Delta", [self.first.pk]),
            ("NÃO EXISTE", []), ("CONFIDENCIAL", []), ("EXTERNO", []),
        ):
            with self.subTest(text=text):
                response = self.screen(q=text)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.ids(response), expected)
        self.assertContains(self.screen(q="SEM-NICHO"), "Não vinculado")

    def test_status_navigation_preserves_scope_and_chart_matches_filtered_results(self):
        response = self.screen(niche="civil", status="waiting", q="Ágata", sort="number", per_page="50")
        self.assertEqual(self.ids(response), [self.second.pk])
        stats = {s["key"]: s for s in response.context["case_stats"]}
        self.assertEqual({key: item["value"] for key, item in stats.items()}, {"total": 2, "active": 1, "waiting": 1, "closed": 0})
        self.assertTrue(stats["waiting"]["selected"])
        params = parse_qs(urlparse(stats["active"]["url"]).query)
        self.assertEqual(params, {"q": ["Ágata"], "niche": ["civil"], "status": ["active"], "sort": ["number"], "per_page": ["50"]})
        self.assertEqual(response.context["case_distribution"][0]["count"], 1)
        self.assertEqual(response.context["case_distribution"][0]["percent"], 100)
        self.assertContains(response, "Situação da pasta jurídica")
        self.assertContains(response, "Cadastro no JUMBI")
        self.assertNotContains(response, "Último andamento")

    def test_owner_filter_uses_matter_owner_and_cannot_enumerate_other_members(self):
        self.assertEqual(self.ids(self.screen(owner=self.operator.pk)), [self.second.pk])
        for owner in (self.outsider, self.manager, self.client_user):
            with self.subTest(owner=owner.email):
                response = self.screen(owner=owner.pk)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["case_rows"], [])
        Membership.objects.filter(organization=self.org, user=self.operator).update(is_active=False)
        self.assertEqual(self.screen(owner=self.operator.pk).status_code, 400)
        self.assertIn(self.second.pk, self.ids(self.screen()))  # Historical owner stays readable.

    def test_catalog_codes_legacy_labels_and_unassigned_are_real_filters(self):
        self.assertEqual(set(self.ids(self.screen(niche="civil"))), {self.first.pk, self.second.pk})
        self.assertEqual(self.ids(self.screen(niche="unassigned")), [self.fourth.pk])
        self.no_niche.area = "Área histórica própria"
        self.no_niche.save()
        response = self.screen()
        bucket = next(d for d in response.context["case_distribution"] if d["label"] == "Área histórica própria")
        self.assertEqual(self.ids(self.client.get(bucket["url"])), [self.fourth.pk])

    def test_invalid_and_duplicate_filters_return_400_without_results(self):
        for params in ({"status": "decidido"}, {"niche": "unknown"}, {"owner": "abc"}, {"sort": "matter__client__document"}, {"per_page": "1000"}, {"page": "0"}, {"page": "no"}, {"page": "999"}, {"q": "x" * 201}, {"sort": ""}, {"page": ""}):
            with self.subTest(params=params):
                response = self.screen(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["case_rows"], [])
                self.assertEqual(response.context["case_stats"], [])
                self.assertEqual(response.context["case_distribution"], [])
                self.assertNotContains(response, self.first.number, status_code=400)
        duplicate = self.client.get(self.url + "?status=active&status=waiting")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("única vez", str(duplicate.context["filter_form"].errors))

    def test_sort_whitelist_and_date_tie_breaker(self):
        self.assertEqual(self.ids(self.screen()), [self.fourth.pk, self.third.pk, self.second.pk, self.first.pk])
        self.assertEqual(self.ids(self.screen(sort="oldest")), [self.first.pk, self.second.pk, self.third.pk, self.fourth.pk])
        self.assertEqual(self.ids(self.screen(sort="number")), [self.second.pk, self.first.pk, self.third.pk, self.fourth.pk])
        CourtCase.objects.filter(organization=self.org).update(created_at=timezone.now())
        self.assertEqual(self.ids(self.screen(sort="oldest")), sorted([self.first.pk, self.second.pk, self.third.pk, self.fourth.pk]))

    def test_pagination_keeps_all_filters_and_charts_count_more_than_the_page(self):
        CourtCase.objects.bulk_create([CourtCase(organization=self.org, matter=self.active, number=f"PAG-{index:03}") for index in range(51)])
        params = {"q": "PAG-", "owner": self.owner.pk, "niche": "civil", "status": "active", "sort": "number", "per_page": 25}
        first = self.screen(**params)
        self.assertEqual(first.context["result_total"], 51)
        self.assertEqual(first.context["case_distribution"][0]["count"], 51)
        self.assertEqual(len(self.ids(first)), 25)
        query = parse_qs(urlparse(first.context["next_url"]).query)
        self.assertEqual(query, {**{key: [str(value)] for key, value in params.items()}, "page": ["2"]})
        second = self.client.get(first.context["next_url"])
        self.assertEqual(second.context["case_rows"][0]["record"].number, "PAG-025")
        last = self.client.get(second.context["next_url"])
        self.assertEqual(len(self.ids(last)), 1)
        fifty = self.screen(**{**params, "per_page": 50, "page": 2})
        self.assertEqual(len(self.ids(fifty)), 1)

    def test_read_only_viewer_operator_controls_and_safe_annotations(self):
        response = self.screen()
        self.assertNotContains(response, "Novo processo")
        self.assertFalse(any(row["edit_url"] for row in response.context["case_rows"]))
        self.assertContains(response, "case-table-scroll")
        self.assertContains(response, "case-mobile-cards")
        self.assertContains(response, "Anotações do processo")
        self.assertContains(response, "&lt;script&gt;nunca executar&lt;/script&gt;")
        self.assertNotContains(response, "<script>nunca executar</script>")
        self.client.force_login(self.operator)
        response = self.screen()
        self.assertContains(response, "Novo processo")
        self.assertTrue(all(row["edit_url"] for row in response.context["case_rows"]))
        count = CourtCase.objects.count()
        self.assertEqual(self.client.post(self.url, {"number": "NO-WRITE"}).status_code, 405)
        self.assertEqual(CourtCase.objects.count(), count)

    def test_anonymous_portal_and_revoked_membership_are_denied(self):
        self.client.logout()
        self.assertEqual(self.screen().status_code, 302)
        self.client.force_login(self.client_user)
        self.assertEqual(self.screen().status_code, 403)
        self.client.force_login(self.viewer)
        Membership.objects.filter(organization=self.org, user=self.viewer).update(is_active=False)
        self.assertEqual(self.screen().status_code, 403)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_start_plan_can_consult_process_directory(self):
        OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        self.assertEqual(self.screen().status_code, 200)

    def test_related_clients_matters_and_owners_do_not_add_queries_per_row(self):
        with CaptureQueriesContext(connection) as before:
            self.assertEqual(self.screen().status_code, 200)
        CourtCase.objects.bulk_create([CourtCase(organization=self.org, matter=self.active, number=f"MORE-{index:03}") for index in range(15)])
        with CaptureQueriesContext(connection) as after:
            self.assertEqual(self.screen().status_code, 200)
        self.assertLessEqual(len(after), len(before) + 1)
