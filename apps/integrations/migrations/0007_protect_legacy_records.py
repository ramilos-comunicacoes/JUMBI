from django.db import migrations


def protect(apps, schema_editor):
    from apps.integrations.credentials import PREFIX, encrypt_credentials
    Account = apps.get_model("integrations", "IntegrationAccount")
    for account in Account.objects.using(schema_editor.connection.alias).exclude(encrypted_credentials="").iterator():
        if not account.encrypted_credentials.startswith(PREFIX):
            account.encrypted_credentials = encrypt_credentials({"api_key": account.encrypted_credentials})
            account.has_credentials = True
            account.status = "NOT_HOMOLOGATED"
            account.save(update_fields=["encrypted_credentials", "has_credentials", "status"])
    # Preserve legacy records, but never let a historical sample look verified.
    Run = apps.get_model("legal", "DJENSearchRun")
    for run in Run.objects.using(schema_editor.connection.alias).all().iterator():
        run.status = "partial"
        run.errors = (run.errors + "\nRegistro legado: origem não comprovada; pode conter demonstração. Execute nova pesquisa oficial antes de usar.").strip()
        run.save(update_fields=["status", "errors"])
    apps.get_model("legal", "DJENCommunication").objects.using(schema_editor.connection.alias).filter(status="pending_review").update(proposed_due_date=None)
    apps.get_model("integrations", "CourtCommunication").objects.using(schema_editor.connection.alias).filter(review_status="PENDING_REVIEW").update(proposed_due_date=None)


class Migration(migrations.Migration):
    dependencies = [("integrations", "0006_apirequest"), ("legal", "0007_administrativedemand_requirement_due_date")]
    operations = [migrations.RunPython(protect, migrations.RunPython.noop)]
