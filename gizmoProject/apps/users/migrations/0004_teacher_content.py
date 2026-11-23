# Generated migration for PastPaper, ModelAnswer, Textbook, StudyMaterial, Submission

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_sitesettings'),
    ]

    operations = [
        migrations.CreateModel(
            name='PastPaper',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('period', models.CharField(blank=True, choices=[('midterm1', 'Midterm 1'), ('midterm2', 'Midterm 2'), ('final', 'Final Exam'), ('supplementary', 'Supplementary')], max_length=20)),
                ('academic_year', models.CharField(blank=True, max_length=20)),
                ('total_marks', models.PositiveIntegerField(default=100)),
                ('duration_mins', models.PositiveIntegerField(default=120)),
                ('notes', models.TextField(blank=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='papers/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='papers', to='users.course')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='papers_uploaded', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ModelAnswer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question_ref', models.CharField(blank=True, max_length=100)),
                ('topic', models.CharField(blank=True, max_length=200)),
                ('answer_text', models.TextField()),
                ('key_points', models.TextField(blank=True)),
                ('marks', models.PositiveIntegerField(default=0)),
                ('criteria', models.TextField(blank=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='answers/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='users.pastpaper')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='Textbook',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=300)),
                ('authors', models.CharField(blank=True, max_length=300)),
                ('edition', models.CharField(blank=True, max_length=100)),
                ('isbn', models.CharField(blank=True, max_length=30)),
                ('chapters', models.CharField(blank=True, max_length=200)),
                ('description', models.TextField(blank=True)),
                ('file', models.FileField(upload_to='textbooks/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('courses', models.ManyToManyField(blank=True, related_name='textbooks', to='users.course')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='textbooks_uploaded', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='StudyMaterial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('material_type', models.CharField(choices=[('lecture', 'Lecture Slides'), ('notes', 'Notes'), ('video', 'Video'), ('code', 'Code'), ('other', 'Other')], default='other', max_length=10)),
                ('description', models.TextField(blank=True)),
                ('file', models.FileField(upload_to='materials/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='materials', to='users.course')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='materials_uploaded', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='Submission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('answer_text', models.TextField(blank=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='submissions/')),
                ('score', models.FloatField(blank=True, null=True)),
                ('feedback', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('answer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submissions', to='users.modelanswer')),
                ('paper', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to='users.pastpaper')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submissions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-submitted_at']},
        ),
    ]