from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_studentexemplar'),
    ]

    operations = [
        migrations.AddField(
            model_name='pastpaper',
            name='num_questions',
            field=models.PositiveIntegerField(default=0),
        ),
    ]