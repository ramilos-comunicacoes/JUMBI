from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Organization, User, Membership, AuditLog
from apps.core.platform_services import configure_office_access, create_office
from apps.legal.models import Matter
from .models import OrganizationSubscription, SubscriptionEvent
from .plans import PLANS
from .services import check_capacity, has_advanced, require_access
from .tests import BILLING_TEST_SETTINGS


@override_settings(**BILLING_TEST_SETTINGS)
class PartnerAccessTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('partner-admin@example.test','PartnerAdmin!4829')
        self.owner=User.objects.create_user('partner-owner@example.test','PartnerOwner!4829')
        self.org=Organization.objects.create(name='Parceiro teste',slug='parceiro-teste',business_type='office')
        self.other=Organization.objects.create(name='Outro escritório',slug='outro-parceiro-teste',business_type='office')
        Membership.objects.create(organization=self.org,user=self.owner,role='owner')
        self.subscription=OrganizationSubscription.objects.create(organization=self.org,plan='start',status='active')
        self.url=reverse('platform:office_access',args=[self.org.pk])
        self.client.force_login(self.admin)

    def data(self, **overrides):
        self.subscription.refresh_from_db()
        return {'revision':self.subscription.updated_at.isoformat(),'plan':'max','status':'active','is_partner':True,'note':'Parceria de teste',**overrides}

    def test_superuser_grants_free_max_to_only_one_office_and_audits(self):
        response=self.client.post(self.url,self.data(expires_at='2020-01-01T12:00'))
        self.assertRedirects(response,self.url)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.is_partner and self.subscription.is_available)
        self.assertEqual(self.subscription.plan,'max');self.assertIsNone(self.subscription.expires_at)
        self.assertEqual(self.subscription.limits['price'],Decimal('0.00'))
        self.assertEqual(SubscriptionEvent.objects.filter(subscription=self.subscription).count(),1)
        self.assertTrue(AuditLog.objects.filter(action='platform.office_access_changed',actor=self.admin).exists())
        self.assertFalse(OrganizationSubscription.objects.filter(organization=self.other).exists())
        self.owner.refresh_from_db();self.assertFalse(self.owner.is_superuser or self.owner.is_staff)
        self.assertContains(self.client.get(reverse('core:platform')),'Parceiro · Gratuito e ilimitado')

    def test_partner_can_exceed_commercial_quotas_but_not_permissions(self):
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data())
        with patch.dict(PLANS['max'],members=0,matters=0,versions=0), transaction.atomic():
            for resource in ('members','matters','versions'):
                check_capacity(self.org,resource,instance=Matter(organization=self.org,title='Nova pasta',status='active'))
        self.assertTrue(has_advanced(self.org))
        self.client.force_login(self.owner)
        for route in ('inventory:overview','fees:overview','contracts:library'):
            self.assertEqual(self.client.get(reverse(route)).status_code,200)
        self.assertEqual(self.client.post(self.url,self.data()).status_code,403)
        self.assertEqual(self.client.get(reverse('platform:office_access',args=[self.other.pk])).status_code,403)
        with self.assertRaises(PermissionDenied):configure_office_access(actor=self.owner,office_id=self.org.pk,data=self.data())

    def test_partner_subscription_page_has_no_payment_prompt(self):
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data())
        self.client.force_login(self.owner)
        response=self.client.get(reverse('billing:subscription'))
        self.assertContains(response,'Uso ilimitado');self.assertContains(response,'Gratuito')
        self.assertNotContains(response,'Registrar solicitação');self.assertNotContains(response,'Continuar pelo WhatsApp')
        self.client.post(reverse('billing:subscription'),{'plan':'start'})
        self.subscription.refresh_from_db();self.assertTrue(self.subscription.is_partner);self.assertEqual(self.subscription.requested_plan,'')

    def test_suspension_works_and_revoke_reinstates_real_limits(self):
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data(status='suspended'))
        with self.assertRaises(PermissionDenied):require_access(self.org)
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data(is_partner=False,plan='start'))
        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.is_partner);self.assertFalse(has_advanced(self.org))
        self.assertEqual(self.subscription.limits['members'],5)
        self.assertEqual(self.subscription.limits['price'],Decimal('299.90'))

    def test_revoke_over_capacity_or_stale_revision_does_not_lose_grant(self):
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data())
        stale=self.data()
        configure_office_access(actor=self.admin,office_id=self.org.pk,data=self.data(note='Atualizada'))
        with self.assertRaises(ValidationError):configure_office_access(actor=self.admin,office_id=self.org.pk,data=stale)
        with patch.dict(PLANS['start'],members=0):
            response=self.client.post(self.url,self.data(is_partner=False,plan='start'))
        self.assertContains(response,'excede os limites')
        self.subscription.refresh_from_db();self.assertTrue(self.subscription.is_partner)

    def test_new_partner_created_active_and_public_signup_cannot_grant(self):
        office=create_office(actor=self.admin,data={'name':'Novo parceiro','owner_name':'Responsável','owner_email':'new-partner@example.test',
            'password':'PartnerNew!49272','practice_areas':['civil'],'plan':'start','subscription_status':'pending','is_partner':True})
        self.assertTrue(office.subscription.is_partner and office.subscription.is_available)
        self.assertEqual(office.subscription.plan,'max')
        self.client.logout()
        self.client.post(reverse('core:signup'),{'first_name':'Visitante','email':'visitor-partner@example.test','organization_name':'Visitante',
            'plan':'max','is_partner':'on','password1':'VisitorAccount!47982','password2':'VisitorAccount!47982'})
        public=OrganizationSubscription.objects.get(organization__memberships__user__email='visitor-partner@example.test')
        self.assertFalse(public.is_partner or public.is_available)
