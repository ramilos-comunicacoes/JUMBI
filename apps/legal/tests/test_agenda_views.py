from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.legal.calendar_forms import CalendarFilterForm
from apps.legal.calendar_services import calendar_context
from apps.legal.models import Appointment, Deadline, Task
from apps.legal.tests.test_calendar import CalendarTests


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False, TIME_ZONE="America/Fortaleza")
class AgendaViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        CalendarTests.setUpTestData.__func__(cls)

    request_for = CalendarTests.request_for
    appointment = CalendarTests.appointment

    def test_week_starts_on_monday_and_crosses_month_boundary(self):
        self.appointment(datetime(2027, 1, 31, 23), datetime(2027, 2, 1, 2), matter=self.matter)
        context = calendar_context(self.request_for(), selected_day=date(2027, 2, 1), view="week")
        self.assertEqual([day["date"] for day in context["calendar_days"]], [date(2027, 2, 1) + timedelta(days=i) for i in range(7)])
        self.assertEqual(context["calendar_event_count"], 1)
        segment = context["calendar_days"][0]["timed"][0]
        self.assertEqual(segment["segment_time"], "00:00–02:00")
        self.assertTrue(segment["continues_before"])
        self.assertEqual(segment["height"], 120)
        self.assertEqual(parse_qs(urlparse(context["calendar_previous_url"]).query)["day"], ["2027-01-25"])

    def test_week_end_and_start_are_exclusive(self):
        self.appointment(datetime(2027, 1, 31, 23), datetime(2027, 2, 1, 0))
        self.appointment(datetime(2027, 2, 7, 23), datetime(2027, 2, 8, 0))
        self.appointment(datetime(2027, 2, 8, 0), datetime(2027, 2, 8, 1))
        context = calendar_context(self.request_for(), selected_day=date(2027, 2, 1), view="week")
        self.assertEqual(context["calendar_event_count"], 1)
        self.assertEqual(context["calendar_days"][-1]["timed"][0]["segment_time"], "23:00–24:00")
        self.assertFalse(context["calendar_days"][0]["events"])

    def test_day_separates_deadlines_and_tasks_from_timed_important_dates(self):
        day = date(2027, 2, 10)
        Task.objects.create(organization=self.org, matter=self.matter, title="Entrega", owner=self.owner, due_date=day)
        Deadline.objects.create(organization=self.org, matter=self.matter, title="Conferir prazo", owner=self.owner, due_date=day, source="Manual")
        self.appointment(datetime(2027, 2, 10, 10), datetime(2027, 2, 10, 11), kind=Appointment.Kind.IMPORTANT_DATE)
        context = calendar_context(self.request_for(), selected_day=day, view="day")
        self.assertEqual(len(context["calendar_days"]), 1)
        self.assertEqual({event["kind"] for event in context["calendar_days"][0]["all_day"]}, {"deadline", "task"})
        self.assertEqual(context["calendar_days"][0]["timed"][0]["kind"], "important")
        self.assertEqual(context["calendar_event_count"], 3)
        self.assertEqual(parse_qs(urlparse(context["calendar_next_url"]).query)["day"], ["2027-02-11"])

    def test_overlap_requires_same_owner_and_does_not_include_touching_intervals(self):
        a = self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 10))
        b = self.appointment(datetime(2027, 2, 10, 9, 30), datetime(2027, 2, 10, 10, 30))
        c = self.appointment(datetime(2027, 2, 10, 10, 30), datetime(2027, 2, 10, 11))
        other_owner = self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 11))
        other_owner.owner = self.viewer
        other_owner.save()
        context = calendar_context(self.request_for(), selected_day=date(2027, 2, 10), view="day")
        by_id = {item["id"]: item for item in context["calendar_day_events"]}
        self.assertTrue(by_id[f"appointment-{a.pk}"]["conflict"])
        self.assertTrue(by_id[f"appointment-{b.pk}"]["conflict"])
        self.assertFalse(by_id[f"appointment-{c.pk}"]["conflict"])
        self.assertFalse(by_id[f"appointment-{other_owner.pk}"]["conflict"])
        self.assertEqual(context["calendar_conflict_count"], 2)

    def test_hidden_appointment_cannot_create_a_conflict_indicator(self):
        self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 10), matter=self.secret, title="Segredo")
        self.appointment(datetime(2027, 2, 10, 9, 30), datetime(2027, 2, 10, 10, 30), matter=self.matter)
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                context = calendar_context(self.request_for(), selected_day=date(2027, 2, 10), view=view)
                self.assertNotIn("Segredo", str(context))
                self.assertEqual(context["calendar_conflict_count"], 0)
                self.assertEqual(context["calendar_event_count"], 1)

    def test_visual_lanes_keep_short_and_overlapping_appointments_separate(self):
        self.appointment(datetime(2027, 2, 10, 9), datetime(2027, 2, 10, 9, 5))
        self.appointment(datetime(2027, 2, 10, 9, 10), datetime(2027, 2, 10, 9, 15))
        self.appointment(datetime(2027, 2, 10, 23, 58), datetime(2027, 2, 11, 0))
        context = calendar_context(self.request_for(), selected_day=date(2027, 2, 10), view="day")
        segments = context["calendar_days"][0]["timed"]
        self.assertNotEqual(segments[0]["left"], segments[1]["left"])
        self.assertEqual(segments[0]["width"], 50)
        self.assertFalse(segments[0]["conflict"])
        self.assertEqual(segments[-1]["top"], 23 * 60 + 58)
        self.assertEqual(segments[-1]["height"], 36)
        self.assertEqual(segments[-1]["segment_time"], "23:58–24:00")

    def test_links_keep_view_day_category_and_niche(self):
        context = calendar_context(self.request_for(params={"niche": "familia"}), selected_day=date(2027, 2, 10), view="week", kind="task")
        params = parse_qs(urlparse(context["calendar_next_url"]).query)
        self.assertEqual(params["view"], ["week"])
        self.assertEqual(params["kind"], ["task"])
        self.assertEqual(params["niche"], ["familia"])
        self.assertEqual(params["day"], ["2027-02-17"])
        day_switch = next(item for item in context["calendar_views"] if item["key"] == "day")
        self.assertEqual(parse_qs(urlparse(day_switch["url"]).query)["day"], ["2027-02-10"])
        self.assertEqual(context["birthdays"], [])

    def test_birthdays_follow_cross_month_week(self):
        self.contact.birth_date = date(1990, 3, 1)
        self.contact.save()
        context = calendar_context(self.request_for(), selected_day=date(2027, 2, 28), view="week")
        self.assertEqual(context["birthdays"], [])
        context = calendar_context(self.request_for(), selected_day=date(2028, 2, 28), view="week")
        self.assertEqual([item["date"] for item in context["birthdays"]], [date(2028, 3, 1)])
        day_context = calendar_context(self.request_for(), selected_day=date(2028, 2, 28), view="day")
        self.assertEqual(day_context["birthdays"], [])

    def test_supported_bounds_and_invalid_filters(self):
        for params in ({"view": "year"}, {"day": "1900-12-31"}, {"day": "2100-01-01"}, {"day": "2027-02-30"}):
            self.assertFalse(CalendarFilterForm(params).is_valid())
        for view in ("month", "week", "day"):
            low = calendar_context(self.request_for(), selected_day=date(1901, 1, 1), view=view)
            high = calendar_context(self.request_for(), selected_day=date(2099, 12, 31), view=view)
            self.assertEqual(low["calendar_previous_url"], "")
            self.assertEqual(high["calendar_next_url"], "")
            if view != "month":
                self.assertGreaterEqual(low["calendar_days"][0]["date"], date(1901, 1, 1))
                self.assertLessEqual(high["calendar_days"][-1]["date"], date(2099, 12, 31))

    def test_date_jump_selects_month_and_dashboard_stays_monthly(self):
        context = calendar_context(self.request_for(params={"day": "2027-03-12", "view": "week"}))
        self.assertEqual(context["calendar_view"], "month")
        self.assertEqual(context["calendar_month"], date(2027, 3, 1))
        self.assertEqual(context["calendar_selected_day"], date(2027, 3, 12))

    def test_each_view_and_invalid_filter_render_for_viewer(self):
        self.client.force_login(self.viewer)
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.client.get(reverse("legal:calendar"), {"view": view, "day": "2027-02-10"})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'aria-label="Visualização da agenda"')
                self.assertContains(response, f'data-calendar-view="{view}"')
                self.assertNotContains(response, "Novo compromisso")
        response = self.client.get(reverse("legal:calendar"), {"view": "year", "day": "9999-12-31"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'data-calendar-view="month"', status_code=400)
        self.assertContains(response, "Revise os filtros", status_code=400)
        self.assertEqual(response.context["calendar_event_count"], 0)
