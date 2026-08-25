from django.db import migrations


BRANCH_SHEETS = {
    'OD3301LR-JGM': '1brVV0GHj-jI9A_ds_dFyiaQbGcqu2If6iboH6mok9tI',
    'OD3302LR-CSP': '1QqYwzk6WjIs2XWJP_S2TAWxKeaAWNv_OrD6MuobTC-4',
}


def configure_history_spreadsheets(apps, schema_editor):
    Branch = apps.get_model('inventory', 'Branch')
    for branch_code, sheet_id in BRANCH_SHEETS.items():
        Branch.objects.filter(branch_code=branch_code).update(google_sheet_id=sheet_id)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0010_inventoryalert')]

    operations = [migrations.RunPython(configure_history_spreadsheets, migrations.RunPython.noop)]
