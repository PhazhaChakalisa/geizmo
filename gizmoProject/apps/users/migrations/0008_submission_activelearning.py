from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0007_aitraininglog'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='flagged_for_dataset',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='submission',
            name='dataset_approved',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='submission',
            name='dataset_reviewed_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]