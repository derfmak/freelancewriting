from django.contrib.postgres.operations import CreateExtension
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('admin_portal', '0007_contactmessage'),
    ]

    operations = [
        CreateExtension('pg_trgm'),
    ]