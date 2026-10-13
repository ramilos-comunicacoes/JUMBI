from datetime import date, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.calendar_forms import CalendarFilterForm
from apps.legal.calendar_services import calendar_context
from apps.legal.models import Appointment, Contact, Deadline, Matter, Task


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False, TIME_ZONE="America/Fortaleza")
class CalendarRefinementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = date(2026, 10, 13)
        cls.now = timezone.make_aware(datetime(2026, 10, 13, 12))
        cls.org = Organization.objects.create(name="Agenda filtros", slug="agenda-filtros", business_type="office", practice_areas=["familia"])
        cls.other = Organization.objects.create(name="Externo", slug="agenda-externo", business_type="office")
        for name, role, org, active in [("owner", "owner", cls.org, True), ("operator", "operator", cls.org, True), ("viewer", "viewer", cls.org, True), ("revoked", "operator", cls.org, False), ("portal", "client", cls.org, True), ("outside", "owner", cls.other, True)]:
            user = get_user_model().objects.create_user(email=f"agenda-{name}@example.test", password="calendar-test")
            setattr(cls, name, user)
            Membership.objects.create(user=user, organization=org, role=role, is_active=active)
        cls.person = Contact.objects.create(organization=cls.org, name="Aniversariante visível", birth_date=date(1990, 10, 13))
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta acessível", area="familia", owner=cls.owner, client=cls.person)
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta reservada", area="familia", owner=cls.owner, confidential=True)
        for name, due, status, owner in [("Atrasada", 12, "todo", cls.owner), ("Hoje", 13, "doing", cls.owner), ("Concluída", 11, "done", cls.owner), ("Outra equipe", 14, "todo", cls.operator)]:
            Task.objects.create(organization=cls.org, matter=cls.matter, title=name, due_date=date(2026, 10, due), status=status, owner=owner, completion_note="Evidência de teste" if status == "done" else "")
        Task.objects.create(organization=cls.org, matter=cls.secret, title="Tarefa secreta", due_date=cls.today, owner=cls.owner)
        Deadline.objects.create(organization=cls.org, matter=cls.matter, title="Prazo atrasado", owner=cls.owner, source="Origem", due_date=date(2026, 10, 12))
        Deadline.objects.create(organization=cls.org, matter=cls.matter, title="Prazo cumprido", owner=cls.owner, source="Origem", due_date=date(2026, 10, 11), status="fulfilled", confirmed_by=cls.owner, confirmed_at=cls.now, evidence="Protocolo")
        for name, begin, end in [("Encerrado", 9, 10), ("Em andamento", 11, 13), ("Agendado", 14, 15)]:
            Appointment.objects.create(organization=cls.org, matter=cls.matter, owner=cls.owner, title=name, starts_at=cls.now.replace(hour=begin), ends_at=cls.now.replace(hour=end))

    def request(self, **params):
        request = RequestFactory().get("/juridico/calendario/", {"month": "2026-10", **params})
        request.user = self.viewer
        request.organization = self.org
        request.membership = Membership.objects.get(user=self.viewer, organization=self.org)
        return request

    def context(self, **params):
        with patch("apps.legal.calendar_services.timezone.now", return_value=self.now):
            return calendar_context(self.request(**params), today=self.today)

    def events(self, context):
        return {event["title"]: event for cell in context["calendar_days"] for event in cell["events"]}

    def test_responsible_choices_are_active_internal_members_only(self):
        form = CalendarFilterForm({}, request=self.request())
        self.assertEqual(set(form.fields["responsible"].queryset), {self.owner, self.operator, self.viewer})
        for user in [self.outside, self.portal, self.revoked]:
            self.assertFalse(CalendarFilterForm({"responsible": user.pk}, request=self.request()).is_valid())

    def test_responsible_filter_uses_event_owner_and_preserves_confidentiality(self):
        self.assertEqual(set(self.events(self.context(responsible=self.operator.pk))), {"Outra equipe"})
        events = self.events(self.context(responsible=self.owner.pk))
        self.assertNotIn("Tarefa secreta", events)
        self.assertNotIn("Outra equipe", events)

    def test_default_keeps_complete_history_and_no_dashboard_regression(self):
        context = self.context()
        self.assertEqual(context["calendar_view"], "month")
        self.assertEqual(context["calendar_event_count"], 9)
        self.assertEqual(len(self.events(context)), 9)
        self.assertEqual(context["calendar_status"], "all")
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("legal:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calendário do escritório")

    def test_pending_includes_overdue_and_unfinished_appointments(self):
        events = self.events(self.context(status="pending"))
        self.assertEqual(set(events), {"Atrasada", "Hoje", "Outra equipe", "Prazo atrasado", "Em andamento", "Agendado"})
        self.assertFalse(events["Hoje"]["overdue"])

    def test_completed_never_means_past_appointment(self):
        events = self.events(self.context(status="completed"))
        self.assertEqual(set(events), {"Concluída", "Prazo cumprido"})
        self.assertTrue(all(item["done"] for item in events.values()))

    def test_overdue_uses_today_and_excludes_finished_records(self):
        self.assertEqual(set(self.events(self.context(status="overdue"))), {"Atrasada", "Prazo atrasado"})

    def test_ended_is_time_based_and_not_a_completion_claim(self):
        events = self.events(self.context(status="ended"))
        self.assertEqual(set(events), {"Encerrado"})
        self.assertFalse(events["Encerrado"]["done"])
        self.assertEqual(events["Encerrado"]["status"], "Encerrado")
        self.assertEqual(self.events(self.context())["Em andamento"]["status"], "Em andamento")

    def test_birthdays_do_not_inherit_assignee_or_event_status(self):
        context = self.context(responsible=self.operator.pk, status="completed")
        self.assertEqual(context["calendar_event_count"], 0)
        self.assertEqual([item["contact"].pk for item in context["birthdays"]], [self.person.pk])

    def test_navigation_preserves_filters_in_month_week_day_and_types(self):
        context = self.context(responsible=self.owner.pk, status="completed", niche="familia", kind="task", day="2026-10-13")
        urls = [context[key] for key in ["calendar_previous_url", "calendar_next_url", "calendar_today_url", "calendar_all_url"]]
        urls += [row["url"] for row in context["calendar_views"] + context["calendar_filters"] + context["calendar_days"]]
        urls += [row["day_url"] for row in context["calendar_days"]]
        for url in urls:
            params = parse_qs(urlparse(url).query)
            self.assertEqual(params["responsible"], [str(self.owner.pk)])
            self.assertEqual(params["status"], ["completed"])
            self.assertEqual(params["niche"], ["familia"])
        reset = parse_qs(urlparse(context["calendar_reset_url"]).query)
        self.assertEqual(reset, {"month": ["2026-10"], "day": ["2026-10-13"], "view": ["month"]})

    def test_invalid_filters_fail_closed_with_http_400(self):
        self.client.force_login(self.viewer)
        for params in [{"responsible": self.outside.pk}, {"responsible": self.portal.pk}, {"status": "anything"}, {"niche": "unknown"}, {"kind": "unknown"}, {"month": "invalid"}, {"day": "2100-01-01"}]:
            with self.subTest(params=params):
                response = self.client.get(reverse("legal:calendar"), params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["calendar_event_count"], 0)
                self.assertFalse(response.context["birthdays"])
                self.assertNotContains(response, "Tarefa secreta", status_code=400)
                self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_date_jump_form_keeps_responsible_status_and_niche(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("legal:calendar"), {"responsible": self.owner.pk, "status": "completed", "niche": "familia", "view": "week", "day": "2026-10-13"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="responsible" value="{self.owner.pk}"')
        self.assertContains(response, 'name="status" value="completed"')
        self.assertContains(response, "não confirma que foram realizados")
        self.assertEqual(response.context["calendar_view"], "week")
