from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.core.models import Organization, Membership
from apps.ponto.models import WorkSchedule, EmployeeSchedule, TimeRecord, TimeAdjustmentRequest, HolidayOrDayOff
from apps.ponto.services import (
    register_punch,
    get_next_expected_record_type,
    calculate_daily_timesheet,
    get_monthly_timesheet,
    get_team_presence_summary,
    get_or_create_default_schedule
)

User = get_user_model()


class PontoServicesTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Escritório Teste",
            slug="escritorio-teste",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE
        )
        self.user = User.objects.create_user(
            email="adv@teste.com",
            password="password123",
            first_name="Advogado"
        )
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=Membership.Role.OPERATOR,
            is_active=True
        )
        self.schedule = get_or_create_default_schedule(self.org)

    def test_default_schedule_created(self):
        self.assertIsNotNone(self.schedule)
        self.assertEqual(self.schedule.daily_expected_hours, 8.0)
        self.assertEqual(self.schedule.tolerance_minutes, 10)

    def test_punch_registration_and_hash_sha256(self):
        today = date.today()
        record = register_punch(
            membership=self.membership,
            record_type="entry_1",
            source="webcam_face",
            face_detected=True,
            face_confidence=92,
            face_landmarks_count=6,
            photo_base64="data:image/jpeg;base64,mock",
            latitude=-23.5505,
            longitude=-46.6333,
            location_accuracy=15.0,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0 Test",
            target_date=today
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.record_type, "entry_1")
        self.assertTrue(record.face_detected)
        self.assertEqual(record.face_confidence, 92)
        # SHA-256 hash must be 64 hexadecimal characters
        self.assertEqual(len(record.hash_sha256), 64)

        # Check next expected punch
        next_type = get_next_expected_record_type(self.membership, target_date=today)
        self.assertEqual(next_type, "exit_1")

    def test_daily_timesheet_calculation(self):
        test_day = date(2026, 10, 20)
        # Create full day of punches: 08:00 -> 12:00, 13:00 -> 17:00 (8 hours)
        dt_e1 = timezone.make_aware(timezone.datetime.combine(test_day, time(8, 0)))
        dt_s1 = timezone.make_aware(timezone.datetime.combine(test_day, time(12, 0)))
        dt_e2 = timezone.make_aware(timezone.datetime.combine(test_day, time(13, 0)))
        dt_s2 = timezone.make_aware(timezone.datetime.combine(test_day, time(17, 0)))

        register_punch(self.membership, "entry_1", custom_datetime=dt_e1, target_date=test_day)
        register_punch(self.membership, "exit_1", custom_datetime=dt_s1, target_date=test_day)
        register_punch(self.membership, "entry_2", custom_datetime=dt_e2, target_date=test_day)
        register_punch(self.membership, "exit_2", custom_datetime=dt_s2, target_date=test_day)

        summary = calculate_daily_timesheet(self.membership, test_day, self.schedule)
        self.assertEqual(summary["worked_minutes"], 480)  # 8 hours = 480 minutes
        self.assertEqual(summary["worked_str"], "08:00")
        self.assertEqual(summary["balance_minutes"], 0)
        self.assertEqual(summary["balance_str"], "00:00")
        self.assertEqual(summary["status_key"], "finished")

    def test_monthly_timesheet_summary(self):
        timesheet = get_monthly_timesheet(self.membership, year=2026, month=10)
        self.assertIn("days", timesheet)
        self.assertEqual(len(timesheet["days"]), 31)  # October has 31 days
        self.assertIn("total_worked_str", timesheet)
        self.assertIn("total_balance_str", timesheet)

    def test_team_presence_summary(self):
        presence = get_team_presence_summary(self.org)
        self.assertEqual(presence["total_members"], 1)
        self.assertEqual(len(presence["not_started"]), 1)


class PontoViewsAndAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.org = Organization.objects.create(
            name="Escritório Teste",
            slug="escritorio-teste",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE
        )
        self.admin_user = User.objects.create_user(
            email="admin@teste.com",
            password="password123",
            first_name="Admin"
        )
        self.admin_membership = Membership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=Membership.Role.OWNER,
            is_active=True
        )

        self.employee_user = User.objects.create_user(
            email="colab@teste.com",
            password="password123",
            first_name="Colaborador"
        )
        self.employee_membership = Membership.objects.create(
            user=self.employee_user,
            organization=self.org,
            role=Membership.Role.OPERATOR,
            is_active=True
        )

    def test_dashboard_authenticated(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("ponto:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ponto Eletrônico")

    def test_clock_in_page(self):
        self.client.force_login(self.employee_user)
        response = self.client.get(reverse("ponto:clock_in"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Terminal Biométrico Facial")

    def test_punch_api_json(self):
        self.client.force_login(self.employee_user)
        payload = {
            "record_type": "entry_1",
            "face_detected": True,
            "face_confidence": 95,
            "face_landmarks_count": 6,
            "photo_base64": "data:image/jpeg;base64,mockphoto",
            "latitude": -23.5505,
            "longitude": -46.6333,
            "location_accuracy": 10.0
        }
        response = self.client.post(
            reverse("ponto:punch_api"),
            data=payload,
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("receipt", data)
        self.assertTrue(len(data["receipt"]["hash_sha256"]) == 64)

    def test_adjustment_request_creation_and_approval(self):
        self.client.force_login(self.employee_user)
        # Colab creates request
        create_resp = self.client.post(reverse("ponto:adjustment_create"), {
            "date": "2026-10-20",
            "request_type": "medical_leave",
            "reason": "Consulta médica agendada"
        })
        self.assertEqual(create_resp.status_code, 302)

        req = TimeAdjustmentRequest.objects.get(membership=self.employee_membership)
        self.assertEqual(req.status, "pending")

        # Admin approves
        self.client.force_login(self.admin_user)
        decide_resp = self.client.post(reverse("ponto:adjustment_decide", args=[req.id]), {
            "action": "approve"
        })
        self.assertEqual(decide_resp.status_code, 302)

        req.refresh_from_db()
        self.assertEqual(req.status, "approved")
        self.assertEqual(req.reviewed_by, self.admin_membership)
