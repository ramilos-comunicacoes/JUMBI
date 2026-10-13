from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.client_map_views import BRAZIL_STATES, MapFilterForm, client_map, contact_region, map_context
from apps.legal.forms import ContactForm
from apps.legal.models import Contact, Matter


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ClientMapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Mapa Alfa", slug="mapa-alfa", business_type="office")
        cls.other = Organization.objects.create(name="Mapa Beta", slug="mapa-beta", business_type="office")
        for name, role, org in [("owner", "owner", cls.org), ("viewer", "viewer", cls.org), ("client_user", "client", cls.org), ("outsider", "owner", cls.other)]:
            user = get_user_model().objects.create_user(email=f"{name}-map@example.test", password="map-test-only")
            setattr(cls, name, user)
            setattr(cls, name + "_membership", Membership.objects.create(organization=org, user=user, role=role))
        cls.ce = Contact.objects.create(organization=cls.org, name="Ana Ceará", state="  CE  ", country="BR", city="Fortaleza")
        cls.ce_company = Contact.objects.create(organization=cls.org, name="Empresa Horizonte", kind="company", state="Ceará", country="Brasil", trade_name="Horizonte", city="Fortaleza")
        cls.sp = Contact.objects.create(organization=cls.org, name="Sônia Paulista", state="  são  paulo  ", country="Brazil")
        cls.ro = Contact.objects.create(organization=cls.org, name="Cliente Rondônia", state="Rondônia", country="")
        cls.missing = Contact.objects.create(organization=cls.org, name="Sem UF", postal_code="60000000", city="Fortaleza", country="Brasil")
        cls.unknown = Contact.objects.create(organization=cls.org, name="Estado a corrigir", state="SP ou RJ", country="BRA")
        cls.outside = Contact.objects.create(organization=cls.org, name="Exterior declarado", state="SP", country="Portugal")
        cls.foreign = Contact.objects.create(organization=cls.other, name="Outro escritório", state="BA", country="Brasil")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta visível", client=cls.ce, owner=cls.owner)
        Matter.objects.create(organization=cls.org, title="Outra pasta do mesmo cliente", client=cls.ce, owner=cls.owner)
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta restrita", client=cls.sp, owner=cls.owner, confidential=True)

    def request(self, user=None, **params):
        request = RequestFactory().get("/juridico/mapa-clientes/", params)
        request.user = user or self.owner
        request.organization = self.org
        request.membership = Membership.objects.get(user=request.user, organization=self.org)
        return request

    def context(self, user=None, **params):
        request = self.request(user, **params)
        form = MapFilterForm(request.GET)
        self.assertTrue(form.is_valid(), form.errors)
        with patch("apps.legal.client_map_views.reverse", return_value="/juridico/mapa-clientes/"):
            return map_context(request, form.cleaned_data)

    def test_all_states_accept_uf_full_name_accents_case_and_spacing(self):
        self.assertEqual(len(BRAZIL_STATES), 27)
        for uf, name in BRAZIL_STATES:
            for state in [uf, uf.lower(), name, "  " + name.upper().replace(" ", "  ") + " "]:
                with self.subTest(uf=uf, state=state):
                    self.assertEqual(contact_region(state, "BrAsIl"), uf)
        self.assertEqual(contact_region("Espirito Santo", "BRA"), "ES")
        self.assertEqual(contact_region("Distrito Federal", "República Federativa do Brasil"), "DF")

    def test_missing_unknown_and_foreign_are_separate_and_never_inferred(self):
        for state, country, expected in [("", "", "missing"), ("", "Brasil", "missing"), ("SP ou RJ", "BR", "unknown"), ("CE", "Portugal", "outside"), ("", "France", "outside"), ("SP", "", "SP")]:
            self.assertEqual(contact_region(state, country), expected)
        context = self.context()
        self.assertEqual(context["totals"], {"clients": 7, "mapped": 4, "missing": 1, "unknown": 1, "outside": 1, "states": 3})
        self.assertEqual(context["state_counts"]["CE"], 2)
        self.assertEqual(context["state_counts"]["SP"], 1)
        self.assertEqual(context["state_counts"]["BA"], 0)

    def test_selected_region_filters_list_but_keeps_comparable_map_totals(self):
        context = self.context(state="CE")
        self.assertEqual({obj.pk for obj in context["client_page"]}, {self.ce.pk, self.ce_company.pk})
        self.assertEqual(context["filtered_count"], 2)
        self.assertEqual(context["totals"]["clients"], 7)
        self.assertEqual(context["selected_label"], "Ceará")
        for obj in context["client_page"]:
            self.assertEqual(obj.map_state_label, "Ceará")
            self.assertEqual(obj.map_state_code, "CE")
        self.assertEqual(len([row for row in context["state_rows"] if row["selected"]]), 1)

    def test_unmatched_filter_links_select_only_the_matching_records(self):
        for key, contact in [("missing", self.missing), ("unknown", self.unknown), ("outside", self.outside)]:
            context = self.context(state=key)
            self.assertEqual([obj.pk for obj in context["client_page"]], [contact.pk])
            self.assertEqual(context["client_page"][0].map_region, key)
            self.assertEqual(context["client_page"][0].map_state_code, "")

    def test_with_matter_honors_confidentiality_and_does_not_double_count_clients(self):
        owner = self.context(scope="with_matter")
        viewer = self.context(self.viewer, scope="with_matter")
        self.assertEqual(owner["totals"]["clients"], 2)
        self.assertEqual(viewer["totals"]["clients"], 1)
        self.assertEqual(viewer["state_counts"]["CE"], 1)
        self.assertEqual(viewer["state_counts"]["SP"], 0)
        self.secret.members.add(self.viewer)
        self.assertEqual(self.context(self.viewer, scope="with_matter")["totals"]["clients"], 2)

    def test_default_includes_contacts_even_without_a_matter_and_remains_read_only_for_viewer(self):
        context = self.context(self.viewer)
        self.assertEqual(context["totals"]["clients"], 7)
        self.assertFalse(context["can_edit"])
        self.assertIn(self.missing.pk, {obj.pk for obj in context["client_page"]})

    def test_person_type_and_search_apply_to_list_counts_and_links(self):
        context = self.context(kind="company", q="Horizonte Fortaleza", state="CE")
        self.assertEqual(context["totals"]["clients"], 1)
        self.assertEqual([obj.pk for obj in context["client_page"]], [self.ce_company.pk])
        self.assertIn("kind=company", context["clear_state_url"])
        self.assertIn("q=Horizonte+Fortaleza", context["state_rows"][0]["url"])
        self.assertIn("state=CE", context["pagination_query"])

    def test_invalid_filters_do_not_silently_expand_scope(self):
        for params in [{"state": "XX"}, {"scope": "all-offices"}, {"kind": "secret"}, {"q": "a" * 121}, {"q": "a b c d e f g h i"}]:
            with self.subTest(params=params):
                with patch("apps.legal.client_map_views.reverse", return_value="/map/"), patch("apps.legal.client_map_views.render", return_value=HttpResponse()) as render:
                    client_map(self.request(**params))
                    context = render.call_args.args[2]
                    self.assertEqual(render.call_args.kwargs["status"], 400)
                    self.assertEqual(context["totals"]["clients"], 0)
                    self.assertTrue(context["filter_form"].errors)

    def test_pagination_preserves_state_and_returns_only_twelve_records(self):
        for index in range(15):
            Contact.objects.create(organization=self.org, name=f"Pessoa CE {index:02}", state="CE", country="BR")
        first = self.context(state="CE")
        second = self.context(state="CE", page="2")
        self.assertEqual(first["filtered_count"], 17)
        self.assertEqual(len(first["client_page"]), 12)
        self.assertEqual(len(second["client_page"]), 5)
        self.assertFalse({obj.pk for obj in first["client_page"]} & {obj.pk for obj in second["client_page"]})
        self.assertNotIn("page=", second["pagination_query"])

    def test_revoked_member_and_portal_client_cannot_load_map(self):
        with self.assertRaises(PermissionDenied):
            client_map(self.request(self.client_user))
        self.viewer_membership.is_active = False
        self.viewer_membership.save()
        with self.assertRaises(PermissionDenied):
            client_map(self.request(self.viewer))

    def test_map_route_allows_both_paid_plans_and_denies_client(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            for plan in ["start", "max"]:
                subscription.plan = plan
                subscription.save()
                self.client.force_login(self.viewer)
                response = self.client.get(reverse("legal:client_map"))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            self.client.force_login(self.client_user)
            self.assertEqual(self.client.get(reverse("legal:client_map")).status_code, 403)
            OrganizationSubscription.objects.create(organization=self.other, plan="start", status="active")
            self.client.force_login(self.outsider)
            other = self.client.get(reverse("legal:client_map"))
            self.assertEqual(other.status_code, 200)
            self.assertEqual(other.context["totals"]["clients"], 1)
            self.assertEqual(other.context["state_counts"]["BA"], 1)
            self.assertEqual(other.context["state_counts"]["CE"], 0)

    def test_legend_and_ranking_are_consistent_with_counts(self):
        context = self.context()
        self.assertEqual(context["max_state_count"], 2)
        self.assertEqual(context["ranking_rows"][0]["uf"], "CE")
        rows = {row["uf"]: row for row in context["state_rows"]}
        self.assertEqual(rows["CE"]["level"], 4)
        self.assertEqual(rows["SP"]["level"], 2)
        self.assertEqual(rows["AC"]["level"], 0)
        self.assertEqual(rows["CE"]["share"], 50)
        empty = self.context(q="NOME-QUE-NAO-EXISTE")
        self.assertEqual(empty["max_state_count"], 0)
        self.assertFalse(empty["ranking_rows"])

    def test_aggregation_query_count_does_not_grow_per_contact(self):
        with CaptureQueriesContext(connection) as baseline:
            self.context()
        for index in range(30):
            Contact.objects.create(organization=self.org, name=f"Mais clientes {index}", state="SP")
        with CaptureQueriesContext(connection) as expanded:
            self.context()
        self.assertLessEqual(len(expanded), len(baseline) + 1)

    def test_foreign_and_legacy_state_names_are_preserved_by_contact_form(self):
        form = ContactForm({"name": "Endereço internacional", "kind": "person", "state": "Ontario", "country": "Canada"}, organization=self.org, user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(obj.state, "Ontario")
        self.assertEqual(contact_region(obj.state, obj.country), "outside")
        self.assertIn("mapa", form.fields["state"].help_text)
