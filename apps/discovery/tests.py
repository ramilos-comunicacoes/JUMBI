from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import Contact, CourtCase, Deadline, Document, Matter, Task
from .models import SavedSearch


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Busca Aurora", slug="search-aurora", business_type="office", practice_areas=["familia", "trabalhista"])
        cls.other_org = Organization.objects.create(name="Outro", slug="search-other", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="search-owner@example.test", password="search-test-password")
        cls.viewer = get_user_model().objects.create_user(email="search-viewer@example.test", password="search-test-password")
        cls.other = get_user_model().objects.create_user(email="search-other@example.test", password="search-test-password")
        cls.portal = get_user_model().objects.create_user(email="search-client@example.test", password="search-test-password")
        Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        cls.viewer_member = Membership.objects.create(organization=cls.org, user=cls.viewer, role="viewer")
        Membership.objects.create(organization=cls.other_org, user=cls.other, role="owner")
        Membership.objects.create(organization=cls.org, user=cls.portal, role="client")
        cls.contact = Contact.objects.create(organization=cls.org, name="Silva Carvalho", email="silva@example.test")
        cls.matter = Matter.objects.create(organization=cls.org, title="Silva inventário", client=cls.contact, owner=cls.owner, area="familia")
        cls.secret = Matter.objects.create(organization=cls.org, title="Silva sigilosa", owner=cls.owner, confidential=True, area="trabalhista")
        cls.external = Matter.objects.create(organization=cls.other_org, title="Silva externa", owner=cls.other)
        cls.case = CourtCase.objects.create(organization=cls.org, matter=cls.matter, number="000001-Silva", court="Tribunal de teste")
        cls.document = Document.objects.create(organization=cls.org, matter=cls.matter, title="Silva procuração", created_by=cls.owner)
        Document.objects.create(organization=cls.org, matter=cls.secret, title="Silva documento restrito", created_by=cls.owner)
        Task.objects.create(organization=cls.org, matter=cls.matter, title="Silva conferir", owner=cls.owner, due_date=timezone.localdate())
        Deadline.objects.create(organization=cls.org, matter=cls.secret, title="Silva prazo restrito", source="Teste", owner=cls.owner, due_date=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.viewer)

    def test_search_respects_tenant_and_confidential_records_in_all_modules(self):
        response = self.client.get(reverse("discovery:search"), {"q": "Silva"})
        self.assertEqual(response.status_code, 200)
        for visible in ["Silva Carvalho", "Silva inventário", "000001-Silva", "Silva procuração", "Silva conferir"]:
            self.assertContains(response, visible)
        for hidden in ["Silva sigilosa", "Silva externa", "Silva documento restrito", "Silva prazo restrito"]:
            self.assertNotContains(response, hidden)
        self.assertEqual(response.context["total"], 5)

    def test_filters_and_words_intersect_and_invalid_filters_do_not_search(self):
        response = self.client.get(reverse("discovery:search"), {"q": "Silva inventário", "kind": "matters", "niche": "familia"})
        self.assertEqual(response.context["total"], 1)
        for data in [{"q": "Silva", "niche": "not-configured"}, {"q": "Silva", "kind": "finance"}, {"q": "S"}, {"q": "one two three four five six seven eight nine"}]:
            response = self.client.get(reverse("discovery:search"), data)
            self.assertFalse(response.context["searched"])
            self.assertEqual(response.context["total"], 0)

    def test_paginated_counts_and_pages_have_no_duplicates(self):
        for i in range(23):
            Contact.objects.create(organization=self.org, name=f"Contato Paginação {i:02}")
        first = self.client.get(reverse("discovery:search"), {"q": "Paginação", "kind": "contacts"})
        second = self.client.get(reverse("discovery:search"), {"q": "Paginação", "kind": "contacts", "page": 2})
        first_ids = {item["id"] for group in first.context["result_groups"] for item in group["items"]}
        second_ids = {item["id"] for group in second.context["result_groups"] for item in group["items"]}
        self.assertEqual(len(first_ids), 20)
        self.assertEqual(len(second_ids), 3)
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(first.context["total"], 23)

    def test_saved_searches_are_personal_and_current_permissions_are_rechecked(self):
        self.client.post(reverse("discovery:save"), {"q": "Silva", "kind": "documents", "niche": "", "name": "Documentos Silva"})
        saved = SavedSearch.objects.get(user=self.viewer)
        self.assertEqual(self.client.get(reverse("discovery:open_saved", args=[saved.pk])).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("discovery:open_saved", args=[saved.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("discovery:delete", args=[saved.pk])).status_code, 404)
        self.secret.members.add(self.viewer)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("discovery:open_saved", args=[saved.pk]), follow=True), "Silva documento restrito")
        self.secret.members.remove(self.viewer)
        self.assertNotContains(self.client.get(reverse("discovery:open_saved", args=[saved.pk]), follow=True), "Silva documento restrito")
        self.assertEqual(self.client.get(reverse("discovery:delete", args=[saved.pk])).status_code, 405)
        self.client.post(reverse("discovery:delete", args=[saved.pk]))
        self.assertFalse(SavedSearch.objects.filter(pk=saved.pk).exists())

    def test_saved_queries_cannot_be_read_from_another_active_workspace(self):
        saved = SavedSearch.objects.create(user=self.viewer, organization=self.other_org, name="Outro escritório", query="Silva")
        self.assertEqual(self.client.get(reverse("discovery:open_saved", args=[saved.pk])).status_code, 404)

    def test_client_and_revoked_members_cannot_search_or_save(self):
        self.client.force_login(self.portal)
        for route in ["discovery:search", "discovery:save"]:
            self.assertEqual(self.client.post(reverse(route), {"q": "Silva", "name": "Atalho"}).status_code, 403)
        self.client.force_login(self.viewer)
        self.viewer_member.is_active = False
        self.viewer_member.save()
        self.assertEqual(self.client.get(reverse("discovery:search"), {"q": "Silva"}).status_code, 403)

    def test_save_limit_and_case_insensitive_duplicate_name(self):
        self.client.post(reverse("discovery:save"), {"q": "Silva", "name": "Família"})
        self.client.post(reverse("discovery:save"), {"q": "Silva", "name": "família"})
        self.assertEqual(SavedSearch.objects.filter(user=self.viewer).count(), 1)
        for i in range(11):
            SavedSearch.objects.create(user=self.viewer, organization=self.org, query="Silva", name=f"Busca {i}")
        self.client.post(reverse("discovery:save"), {"q": "Silva", "name": "Décima terceira"})
        self.assertEqual(SavedSearch.objects.filter(user=self.viewer).count(), 12)

    def test_viewer_links_are_readable_and_never_edit_forms(self):
        response = self.client.get(reverse("discovery:search"), {"q": "Silva"})
        for group in response.context["result_groups"]:
            for item in group["items"]:
                self.assertNotIn("/editar/", item["url"])
                self.assertEqual(self.client.get(item["url"]).status_code, 200)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_subscription_gate_covers_search_and_personal_writes(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        self.assertEqual(self.client.get(reverse("discovery:search"), {"q": "Silva"}).status_code, 200)
        subscription.expires_at = timezone.now() - timedelta(hours=1)
        subscription.save()
        for route in ["discovery:search", "discovery:save"]:
            self.assertRedirects(self.client.post(reverse(route), {"q": "Silva", "name": "Bloqueada"}), reverse("billing:subscription"), fetch_redirect_response=False)
        self.assertFalse(SavedSearch.objects.exists())
