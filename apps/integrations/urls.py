"""URLs for JUMBI Integrations Hub and OpenAPI REST endpoints."""
from django.urls import path
from . import api_views
from . import views
from . import webhook_views

app_name = "integrations"

urlpatterns = [
    # Web UI Routes
    path("conectores/", views.connectors, name="connectors"),
    path("monitoramentos/", views.monitors, name="monitors"),
    path("triagem/", views.triage, name="triage"),
    path("cobertura/", views.coverage, name="coverage"),
    path("relatorios/", views.reports, name="reports"),
    path("relatorios/<int:pk>/download/", views.download_report, name="download_report"),

    # REST API Endpoints (OpenAPI 3.1.0)
    path("api/v1/integrations/providers/", api_views.list_providers, name="api_providers"),
    path("api/v1/integrations/accounts/", api_views.accounts_collection, name="api_accounts"),
    path("api/v1/integrations/accounts/<uuid:account_id>/", api_views.account_detail, name="api_account_detail"),
    path("api/v1/integrations/accounts/<uuid:account_id>/validate/", api_views.validate_account, name="api_validate_account"),
    path("api/v1/integrations/monitors/", api_views.monitors_collection, name="api_monitors"),
    path("api/v1/integrations/monitors/<uuid:monitor_id>/runs/", api_views.start_monitor_run, name="api_start_run"),
    path("api/v1/integrations/runs/<uuid:run_id>/", api_views.get_run, name="api_get_run"),
    path("api/v1/integrations/coverage/", api_views.list_coverage, name="api_coverage"),
    path("api/v1/communications/", api_views.list_communications, name="api_communications"),
    path("api/v1/communications/<uuid:communication_id>/reviews/", api_views.review_communication, name="api_review_communication"),
    path("api/v1/communications/<uuid:communication_id>/official-action-authorizations/", api_views.authorize_official_action, name="api_authorize_official"),
    path("api/v1/reports/daily-communications/", api_views.create_daily_report_api, name="api_daily_report"),

    # Webhook Endpoint (HMAC-SHA256)
    path("api/v1/integrations/pdpj/webhooks/<uuid:subscription_id>/", webhook_views.receive_pdpj_webhook, name="api_pdpj_webhook"),
]
