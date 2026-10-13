from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.calendar_forms import CalendarFilterForm
from apps.legal.calendar_services import birthday_context, calendar_context, normalize_whatsapp_phone
from apps.legal.models import Appointment, Contact, Deadline, Matter, Task


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False, TIME_ZONE="America/Fortaleza")
class CalendarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório Aurora", slug="calendar-aurora", business_type="office", practice_areas=["familia", "trabalhista"])
        cls.other = Organization.objects.create(name="Outro escritório", slug="calendar-other", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="calendar-owner@example.test", password="test-only-password")
        cls.viewer = get_user_model().objects.create_user(email="calendar-viewer@example.test", password="test-only-password")
        cls.outsider = get_user_model().objects.create_user(email="calendar-other@example.test", password="test-only-password")
        cls.owner_membership = Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        cls.viewer_membership = Membership.objects.create(organization=cls.org, user=cls.viewer, role="viewer")
        Membership.objects.create(organization=cls.other, user=cls.outsider, role="owner")
        cls.contact = Contact.objects.create(organization=cls.org, name="Ana & Silva", phone="(88) 99274-5456", birth_date=date(1992, 2, 29))
        cls.secret_contact = Contact.objects.create(organization=cls.org, name="Cliente sigiloso", phone="88992745456", birth_date=date(1980, 2, 28))
        cls.other_contact = Contact.objects.create(organization=cls.other, name="Pessoa de fora", birth_date=date(1995, 2, 28))
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta de família", client=cls.contact, owner=cls.owner, area="familia")
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta sigilosa", client=cls.secret_contact, owner=cls.owner, confidential=True, area="familia")
        cls.other_matter = Matter.objects.create(organization=cls.other, title="Pasta externa", client=cls.other_contact, owner=cls.outsider)

    def request_for(self, user=None, params=None):
        request = RequestFactory().get("/juridico/calendario/", params or {})
        request.user = user or self.viewer
        request.organization = self.org
        request.membership = self.viewer_membership if request.user == self.viewer else self.owner_membership
        return request

    def appointment(self, starts, ends, matter=None, **kwargs):
        return Appointment.objects.create(organization=self.org, matter=matter, title=kwargs.pop("title", "Encontro"), starts_at=timezone.make_aware(starts), ends_at=timezone.make_aware(ends), owner=self.owner, **kwargs)

    def test_phone_normalization_rejects_ambiguous_or_malformed_numbers(self):
        valid = {"(88) 99274-5456": "5588992745456", "+55 88 99274-5456": "5588992745456", "5588992745456": "5588992745456", "+1 (212) 555-1234": "12125551234", "0044 20 7946 0958": "442079460958", "(11) 2345-6789": "551123456789"}
        for raw, expected in valid.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_whatsapp_phone(raw), expected)
        for raw in ["", "992745456", "123", "(00) 99999-9999", "(88) 81234-5678", "+55 88 1234-5678", "88992745456 ramal 2", "javascript:alert(1)", "+00000000", "+1234567890123456", "not a phone"]:
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_whatsapp_phone(raw))

    def test_birthdays_are_clients_from_visible_matters_only(self):
        Contact.objects.create(organization=self.org, name="Contato sem pasta", birth_date=date(1989, 2, 28))
        result = birthday_context(self.request_for(), month=date(2027, 2, 1), today=date(2027, 2, 28))
        self.assertEqual([x["contact"].pk for x in result["birthdays"]], [self.contact.pk])
        self.assertEqual(result["birthday_today_count"], 1)
        self.secret.members.add(self.viewer)
        self.assertEqual(len(birthday_context(self.request_for(), month=date(2027, 2, 1))["birthdays"]), 2)

    def test_duplicate_client_matters_do_not_duplicate_birthdays(self):
        Matter.objects.create(organization=self.org, title="Outra pasta", client=self.contact, owner=self.owner)
        data = birthday_context(self.request_for(), month=date(2028, 2, 1), today=date(2028, 2, 29))
        self.assertEqual(len(data["birthdays"]), 1)
        self.assertFalse(data["birthdays"][0]["leap_adjusted"])
        self.assertEqual(data["birthdays"][0]["date"], date(2028, 2, 29))

    def test_non_leap_birthday_is_explicitly_february_28(self):
        result = birthday_context(self.request_for(), month=date(2027, 2, 1), today=date(2027, 2, 28))
        item = result["birthdays"][0]
        self.assertTrue(item["leap_adjusted"])
        self.assertTrue(item["is_today"])
        url = urlparse(item["whatsapp_url"])
        self.assertEqual(url.netloc, "wa.me")
        self.assertEqual(url.path, "/5588992745456")
        text = parse_qs(url.query)["text"][0]
        self.assertIn("Ana & Silva", text)
        self.assertIn("Escritório Aurora", text)

    def test_missing_phone_has_no_link(self):
        self.contact.phone = "123"
        self.contact.save()
        self.assertIsNone(birthday_context(self.request_for(), month=date(2027, 2, 1))["birthdays"][0]["whatsapp_url"])

    def test_contact_birth_validation_applies_to_model(self):
        for values in [{"kind": Contact.Kind.COMPANY, "birth_date": date(2000, 1, 1)}, {"birth_date": timezone.localdate() + timedelta(days=1)}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Contact.objects.create(organization=self.org, name="Inválido", **values)

    def test_revoked_membership_sees_no_birthday(self):
        self.viewer_membership.is_active = False
        self.viewer_membership.save()
        self.assertEqual(birthday_context(self.request_for(), month=date(2027, 2, 1))["birthdays"], [])

    def test_calendar_grid_leap_month_and_year_navigation(self):
        result = calendar_context(self.request_for(), month=date(2028, 2, 1))
        self.assertEqual(len([day for day in result["calendar_days"] if day["current_month"]]), 29)
        self.assertEqual(result["calendar_days"][0]["date"].weekday(), 6)
        self.assertEqual(len(result["calendar_days"]) % 7, 0)
        january = calendar_context(self.request_for(), month=date(2027, 1, 1))
        self.assertEqual(january["calendar_previous"], "2026-12")
        december = calendar_context(self.request_for(), month=date(2027, 12, 1))
        self.assertEqual(december["calendar_next"], "2028-01")

    def test_multiday_event_is_counted_once_and_midnight_end_is_exclusive(self):
        self.appointment(datetime(2027, 2, 2, 9), datetime(2027, 2, 4, 0), matter=self.matter)
        result = calendar_context(self.request_for(), month=date(2027, 2, 1))
        self.assertEqual(result["calendar_event_count"], 1)
        occupied = [day["date"].day for day in result["calendar_days"] if day["events"]]
        self.assertEqual(occupied, [2, 3])

    def test_cross_month_appointments_and_local_timezone_are_included(self):
        self.appointment(datetime(2027, 1, 31, 23), datetime(2027, 2, 1, 2), matter=self.matter)
        result = calendar_context(self.request_for(), month=date(2027, 2, 1), selected_day=date(2027, 2, 1))
        self.assertEqual(result["calendar_event_count"], 1)
        self.assertEqual(result["calendar_day_events"][0]["time"], "23:00")
        self.assertEqual(result["calendar_day_events"][0]["date"], date(2027, 1, 31))

    def test_scoped_categories_and_filters_do_not_leak_confidential_events(self):
        self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 10), matter=self.secret, title="Audiência secreta")
        self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 10), matter=self.matter, kind=Appointment.Kind.IMPORTANT_DATE)
        Task.objects.create(organization=self.org, matter=self.matter, title="Entrega", owner=self.owner, due_date=date(2027, 2, 10))
        Deadline.objects.create(organization=self.org, matter=self.matter, title="Prazo", owner=self.owner, due_date=date(2027, 2, 10), source="Fonte")
        Deadline.objects.create(organization=self.other, matter=self.other_matter, title="Prazo externo", owner=self.outsider, due_date=date(2027, 2, 10), source="Fonte")
        result = calendar_context(self.request_for(), month=date(2027, 2, 1), selected_day=date(2027, 2, 10))
        self.assertEqual(result["calendar_counts"], {"deadline": 1, "task": 1, "important": 1})
        self.assertNotIn("Audiência secreta", str(result))
        self.assertNotIn("Prazo externo", str(result))
        filtered = calendar_context(self.request_for(), month=date(2027, 2, 1), selected_day=date(2027, 2, 10), kind="deadline")
        self.assertEqual([e["kind"] for e in filtered["calendar_day_events"]], ["deadline"])
        self.assertEqual(filtered["calendar_day_events"][0]["url"], reverse("legal:detail", args=[self.matter.pk]))

    def test_invalid_month_is_rejected_and_arbitrary_day_is_not_used(self):
        for month in ["2027-99", "0", "9999-12", "2027-2", "2027-02-01"]:
            with self.subTest(month=month):
                self.assertFalse(CalendarFilterForm({"month": month}).is_valid())
        result = calendar_context(self.request_for(), month=date(2027, 2, 1), selected_day=date(2099, 1, 1), today=date(2027, 2, 18))
        self.assertEqual(result["calendar_selected_day"], date(2027, 2, 18))

    def test_niche_filters_events_and_birthdays_and_navigation(self):
        self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 10), matter=self.matter)
        result = calendar_context(self.request_for(params={"niche": "trabalhista"}), month=date(2027, 2, 1))
        self.assertEqual(result["calendar_event_count"], 0)
        self.assertEqual(result["birthdays"], [])
        self.assertIn("niche=trabalhista", result["calendar_days"][0]["url"])

    def test_calendar_route_readonly_viewer_and_invalid_month_render(self):
        self.client.force_login(self.viewer)
        for params in [{"month": "2027-02"}, {"month": "invalid"}]:
            response = self.client.get(reverse("legal:calendar"), params)
            expected = 400 if params["month"] == "invalid" else 200
            self.assertEqual(response.status_code, expected)
            self.assertContains(response, "Calendário e agenda", status_code=expected)
            self.assertNotContains(response, "Novo compromisso", status_code=expected)
        response = self.client.get(reverse("legal:calendar"), {"month": "2027-02"})
        self.assertContains(response, "Ana &amp; Silva")
        self.assertNotContains(response, "Cliente sigiloso")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("legal:calendar")).status_code, 302)
