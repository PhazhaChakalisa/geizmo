import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_teacher_content'),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentExemplar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_name', models.CharField(blank=True, max_length=200)),
                ('year', models.CharField(blank=True, max_length=20)),
                ('question_ref', models.CharField(blank=True, max_length=100)),
                ('content_text', models.TextField(blank=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='exemplars/')),
                ('score', models.FloatField(blank=True, null=True)),
                ('total_marks', models.PositiveIntegerField(default=0)),
                ('commentary', models.TextField(blank=True)),
                ('is_visible', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('added_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exemplars_added', to=settings.AUTH_USER_MODEL)),
                ('answer_ref', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='exemplars', to='users.modelanswer')),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exemplars', to='users.pastpaper')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]