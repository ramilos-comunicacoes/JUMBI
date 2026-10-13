"""Real contact indicators must preserve tenant, confidentiality and filter scope."""
from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.contact_directory import age_band
from apps.legal.models import Contact, CourtCase, Matter


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ContactDirectoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = date(2026, 10, 13)
        cls.org = Organization.objects.create(name="Escritório Diretório", slug="directory-alpha", business_type="office", practice_areas=["civil", "familia"])
        cls.other = Organization.objects.create(name="Outro escritório", slug="directory-beta", business_type="office")
        for name, role, org in [("owner", "owner", cls.org), ("viewer", "viewer", cls.org), ("portal", "client", cls.org), ("outsider", "owner", cls.other)]:
            user = get_user_model().objects.create_user(email=f"directory-{name}@example.test", password="directory-test-only")
            setattr(cls, name, user)
            setattr(cls, name + "_membership", Membership.objects.create(user=user, organization=org, role=role))
        cls.ana = Contact.objects.create(organization=cls.org, name="Ana Horizonte", document="11122233344", phone="(88) 99274-5456", email="ana@example.test", city="Fortaleza", state="Ceará", country="BR", profession="Engenheira civil", birth_date=date(1981, 10, 13), notes="OBSERVAÇÃO PRIVADA NÃO MOSTRAR", representatives="REPRESENTANTE PRIVADO NÃO MOSTRAR")
        cls.bruna = Contact.objects.create(organization=cls.org, name="Bruna Costa", profession="engenheira   civil", birth_date=date(1999, 12, 20), state="SP", country="Brasil", status="prospect")
        cls.caio = Contact.objects.create(organization=cls.org, name="Caio Antunes", phone="123", status="inactive")
        cls.diana = Contact.objects.create(organization=cls.org, name="Diana Luz", profession="Advogada")
        # Old imported records can contain a future birth date; the chart must not invent an age.
        Contact.objects.filter(pk=cls.diana.pk).update(birth_date=cls.today + timedelta(days=1))
        cls.company = Contact.objects.create(organization=cls.org, name="Empresa Quasar", trade_name="Marca Quasar", kind="company", state=" CE ", country="Brazil", profession="CAMPO LEGADO DE EMPRESA")
        cls.eric = Contact.objects.create(organization=cls.org, name="Eric Vale", state="CE", country="Brasil", birth_date=date(1989, 1, 1))
        cls.fabi = Contact.objects.create(organization=cls.org, name="Fabi Mar", state="SP", country="Espanha", birth_date=date(2009, 10, 14), profession="Designer")
        cls.gil = Contact.objects.create(organization=cls.org, name="Gil Fontes", state="SP ou RJ", country="Brasil", birth_date=date(1960, 2, 29), profession="Professor")
        cls.foreign = Contact.objects.create(organization=cls.other, name="SEGREDO OUTRO ESCRITÓRIO", profession="PROFISSÃO DE OUTRO ESCRITÓRIO")
        cls.active = Matter.objects.create(organization=cls.org, title="Atendimento Ana", client=cls.ana, owner=cls.owner, area="civil")
        cls.secret = Matter.objects.create(organization=cls.org, title="PROCESSO SIGILOSO BRUNA", client=cls.bruna, owner=cls.owner, area="familia", confidential=True)
        cls.closed = Matter.objects.create(organization=cls.org, title="Atendimento encerrado", client=cls.caio, owner=cls.owner, area="Direito Civil", status="closed")
        cls.waiting = Matter.objects.create(organization=cls.org, title="Atendimento aguardando", client=cls.company, owner=cls.owner, status="waiting")
        Matter.objects.create(organization=cls.org, title="Pasta sem processo", client=cls.diana, owner=cls.owner, area="civil")
        for number, matter in [("ANA-1", cls.active), ("ANA-2", cls.active), ("BRUNA-SIGILOSO", cls.secret), ("CAIO-ENCERRADO", cls.closed), ("EMPRESA-AGUARDANDO", cls.waiting)]:
            CourtCase.objects.create(organization=cls.org, matter=matter, number=number)

    def setUp(self):
        self.client.force_login(self.owner)
        self.today_patch = patch("apps.legal.contact_directory.timezone.localdate", return_value=self.today)
        self.today_patch.start()
        self.addCleanup(self.today_patch.stop)

    def screen(self, **params):
        return self.client.get(reverse("legal:list", args=["contacts"]), params)

    def ids(self, response):
        return {row["record"].pk for row in response.context["rows"]}

    def test_cards_count_people_once_only_with_a_case_in_a_visible_active_matter(self):
        response = self.screen()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["module_template"], "legal/contact_directory.html")
        self.assertEqual(response.context["counts"], {"total": 8, "with_case": 2, "without_case": 6})
        self.assertContains(response, "Eles não confirmam a situação do processo no tribunal.")
        self.assertEqual(self.ids(self.screen(case="with")), {self.ana.pk, self.bruna.pk})
        self.assertEqual(len(self.ids(self.screen(case="without"))), 6)
        self.assertNotContains(response, self.secret.title)
        self.assertNotContains(response, "BRUNA-SIGILOSO")
        self.assertNotContains(response, self.foreign.name)

    def test_confidential_process_does_not_inflate_viewer_count_or_case_filter(self):
        self.client.force_login(self.viewer)
        response = self.screen()
        self.assertEqual(response.context["counts"], {"total": 8, "with_case": 1, "without_case": 7})
        self.assertEqual(self.ids(self.screen(case="with")), {self.ana.pk})
        self.assertIn(self.bruna.pk, self.ids(self.screen(case="without")))
        self.secret.members.add(self.viewer)
        self.assertEqual(self.screen().context["counts"]["with_case"], 2)

    def test_cards_preserve_other_filters_and_only_change_process_selection(self):
        response = self.screen(q="Ana", kind="person", status="active", state="CE", niche="civil", case="with", sort="newest", per_page=50, page=4)
        self.assertEqual(response.context["counts"], {"total": 1, "with_case": 1, "without_case": 0})
        for card in response.context["directory_cards"]:
            target = urlsplit(card["url"])
            query = parse_qs(target.query)
            self.assertEqual(target.fragment, "directory-results")
            self.assertEqual(query["q"], ["Ana"])
            self.assertEqual(query["kind"], ["person"])
            self.assertEqual(query["status"], ["active"])
            self.assertEqual(query["state"], ["CE"])
            self.assertEqual(query["niche"], ["civil"])
            self.assertEqual(query["sort"], ["newest"])
            self.assertEqual(query["per_page"], ["50"])
            self.assertNotIn("page", query)
            self.assertEqual(query.get("case", [""])[0], "" if card["key"] == "all" else card["key"])

    def test_demographics_use_real_pf_data_merge_professions_and_expose_missing_values(self):
        response = self.screen()
        self.assertEqual(response.context["people_count"], 7)
        self.assertEqual(response.context["profession_known"], 5)
        self.assertEqual(response.context["birth_known"], 5)
        professions = {item["key"]: item["count"] for item in response.context["profession_rows"]}
        self.assertEqual(professions["engenheira civil"], 2)
        self.assertEqual(professions["unknown"], 2)
        self.assertNotIn("campo legado de empresa", professions)
        ages = {item["key"]: item["count"] for item in response.context["age_rows"]}
        self.assertEqual(ages, {"under18": 1, "18_29": 1, "30_44": 1, "45_59": 1, "60plus": 1, "unknown": 2})
        self.assertContains(response, "Profissão não informada")
        self.assertContains(response, "Sem nascimento válido")
        self.assertNotContains(response, "PROFISSÃO DE OUTRO ESCRITÓRIO")

    def test_top_professions_preserve_remaining_counts_in_other_group(self):
        for index in range(8):
            Contact.objects.create(organization=self.org, name=f"Nova profissão {index}", profession=f"Profissão {index}")
        response = self.screen()
        rows = response.context["profession_rows"]
        self.assertEqual(len(rows), 7)  # five named groups, others and unknown
        self.assertEqual(sum(row["count"] for row in rows), response.context["people_count"])
        self.assertEqual(next(row["count"] for row in rows if row["key"] == "other"), 7)

    def test_age_bands_use_the_birthday_boundary_and_missing_or_future_dates(self):
        for years, key_before, key_on in [(18, "under18", "18_29"), (30, "18_29", "30_44"), (45, "30_44", "45_59"), (60, "45_59", "60plus")]:
            birth = date(self.today.year - years, self.today.month, self.today.day)
            self.assertEqual(age_band(birth, self.today - timedelta(days=1)), key_before)
            self.assertEqual(age_band(birth, self.today), key_on)
        self.assertEqual(age_band(None, self.today), "unknown")
        self.assertEqual(age_band(self.today + timedelta(days=1), self.today), "unknown")
        self.assertEqual(age_band(date(2008, 2, 29), date(2026, 2, 28)), "under18")
        self.assertEqual(age_band(date(2008, 2, 29), date(2026, 3, 1)), "18_29")

    def test_search_combines_words_across_fields_and_supports_trade_name(self):
        for query in ["Ana Fortaleza", "11122233344", "ana@example.test", "99274"]:
            self.assertEqual(self.ids(self.screen(q=query)), {self.ana.pk})
        self.assertEqual(self.ids(self.screen(q="Marca Quasar")), {self.company.pk})
        self.assertEqual(self.ids(self.screen(q="Ana Quasar")), set())

    def test_kind_and_relationship_are_separate_and_old_kind_bookmarks_work(self):
        self.assertEqual(self.ids(self.screen(kind="company")), {self.company.pk})
        self.assertEqual(self.ids(self.screen(status="prospect")), {self.bruna.pk})
        self.assertEqual(self.ids(self.screen(status="inactive")), {self.caio.pk})
        self.assertEqual(self.ids(self.screen(status="company")), {self.company.pk})
        self.assertEqual(self.screen(kind="company").context["people_count"], 0)
        self.assertContains(self.screen(kind="company"), "Nenhuma pessoa física nesta seleção.")

    def test_region_filter_normalizes_legacy_states_without_guessing_missing_or_foreign_data(self):
        expectations = {"CE": {self.ana.pk, self.company.pk, self.eric.pk}, "SP": {self.bruna.pk}, "outside": {self.fabi.pk}, "unknown": {self.gil.pk}, "missing": {self.caio.pk, self.diana.pk}}
        for region, ids in expectations.items():
            with self.subTest(region=region):
                self.assertEqual(self.ids(self.screen(state=region)), ids)

    def test_niche_matches_visible_pastas_and_never_exposes_secret_associations(self):
        self.assertEqual(self.ids(self.screen(niche="civil")), {self.ana.pk, self.caio.pk, self.diana.pk})
        self.assertEqual(self.ids(self.screen(niche="familia")), {self.bruna.pk})
        self.client.force_login(self.viewer)
        response = self.screen(niche="familia")
        self.assertEqual(response.context["counts"]["total"], 0)
        self.assertEqual(self.ids(response), set())

    def test_invalid_filters_return_400_without_widening_to_any_contacts(self):
        for params in [{"kind": "invalid"}, {"status": "invalid"}, {"case": "secret"}, {"state": "Ceará"}, {"niche": "criminal"}, {"sort": "email"}, {"per_page": "5000"}, {"per_page": "-1"}, {"q": "x" * 161}, {"q": "one two three four five six seven eight nine"}]:
            with self.subTest(params=params):
                response = self.screen(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["filtered_count"], 0)
                self.assertFalse(response.context["filter_valid"])
                self.assertNotContains(response, self.ana.name, status_code=400)

    def test_pagination_uses_full_filtered_totals_and_preserves_all_filters(self):
        for index in range(53):
            Contact.objects.create(organization=self.org, name=f"Página {index:02}", profession="Teste", state="CE", country="BR")
        response = self.screen(q="Página", kind="person", state="CE", status="active", case="without", per_page=25, page=2, sort="name")
        self.assertEqual(len(response.context["rows"]), 25)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(response.context["filtered_count"], 53)
        self.assertEqual(response.context["counts"]["total"], 53)
        self.assertEqual(response.context["people_count"], 53)
        query = parse_qs(response.context["pagination_query"])
        self.assertEqual(query, {"q": ["Página"], "kind": ["person"], "state": ["CE"], "status": ["active"], "case": ["without"], "sort": ["name"], "per_page": ["25"]})
        self.assertContains(response, "&amp;page=3#directory-results")
        larger = self.screen(q="Página", per_page=50)
        self.assertEqual(len(larger.context["rows"]), 50)
        self.assertEqual(larger.context["people_count"], 53)

    def test_ordering_is_stable_by_name_or_newest_and_empty_results_are_honest(self):
        self.assertEqual(self.screen().context["rows"][0]["record"].pk, self.ana.pk)
        Contact.objects.filter(pk=self.ana.pk).update(created_at=timezone.now() + timedelta(minutes=1))
        self.assertEqual(self.screen(sort="newest").context["rows"][0]["record"].pk, self.ana.pk)
        empty = self.screen(q="DOES-NOT-EXIST")
        self.assertEqual(empty.context["filtered_count"], 0)
        self.assertEqual(empty.context["people_count"], 0)
        self.assertContains(empty, "Nenhum resultado com estes filtros")
        self.assertNotContains(empty, "directory-donut")

    def test_links_open_authorized_profiles_and_only_valid_manual_whatsapp(self):
        response = self.screen()
        rows = {row["record"].pk: row for row in response.context["rows"]}
        self.assertEqual(rows[self.caio.pk]["whatsapp_url"], "")
        target = urlsplit(rows[self.ana.pk]["whatsapp_url"])
        self.assertEqual((target.scheme, target.netloc, target.path), ("https", "wa.me", "/5588992745456"))
        self.assertIn(self.ana.name, parse_qs(target.query)["text"][0])
        self.assertIn(self.org.name, parse_qs(target.query)["text"][0])
        self.assertContains(response, "A mensagem abre para você revisar e enviar.")
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertEqual(self.client.get(rows[self.ana.pk]["detail_url"]).status_code, 200)
        self.assertEqual(self.client.get(rows[self.ana.pk]["edit_url"]).status_code, 200)
        self.assertNotContains(response, self.ana.notes)
        self.assertNotContains(response, self.ana.representatives)

    def test_viewer_reads_directory_but_has_no_write_actions_and_portal_is_denied(self):
        self.client.force_login(self.viewer)
        response = self.screen()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_create"])
        self.assertNotContains(response, "Nova pessoa")
        self.assertNotContains(response, "Editar cadastro")
        self.assertEqual(self.client.get(reverse("legal:edit", args=["contacts", self.ana.pk])).status_code, 403)
        self.client.force_login(self.portal)
        self.assertEqual(self.screen().status_code, 403)

    def test_other_tenant_authentication_revocation_and_method_are_enforced(self):
        self.client.force_login(self.outsider)
        response = self.screen()
        self.assertEqual(response.context["counts"]["total"], 1)
        self.assertEqual(self.ids(response), {self.foreign.pk})
        self.assertNotContains(response, self.ana.name)
        self.client.force_login(self.viewer)
        self.viewer_membership.is_active = False
        self.viewer_membership.save()
        self.assertEqual(self.screen().status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("legal:list", args=["contacts"]), {}).status_code, 405)
        self.client.logout()
        self.assertEqual(self.screen().status_code, 302)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_both_plans_allow_directory_and_get_does_not_consume_resource_quotas(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        before = (Contact.objects.count(), Matter.objects.count(), CourtCase.objects.count())
        for plan in ["start", "max"]:
            subscription.plan = plan
            subscription.save()
            response = self.screen()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(before, (Contact.objects.count(), Matter.objects.count(), CourtCase.objects.count()))

    def test_query_count_does_not_grow_for_each_contact_on_the_page(self):
        with CaptureQueriesContext(connection) as initial:
            self.assertEqual(self.screen().status_code, 200)
        for index in range(43):
            Contact.objects.create(organization=self.org, name=f"Pessoa extra {index:02}", phone="(88) 99274-5456")
        with CaptureQueriesContext(connection) as expanded:
            response = self.screen(per_page=50)
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 50)
        self.assertLessEqual(len(expanded), len(initial) + 1)

    def test_contact_data_is_escaped_in_chart_labels_names_and_urls(self):
        Contact.objects.create(organization=self.org, name='<script>alert("unsafe")</script>', profession='<img src=x onerror="unsafe">', phone="(88) 99274-5456")
        response = self.screen(q="unsafe")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<script>alert("unsafe")</script>')
        self.assertNotContains(response, '<img src=x onerror="unsafe">')
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "%3Cscript%3E")
