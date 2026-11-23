from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_pastpaper_num_questions'),
    ]

    operations = [
        migrations.CreateModel(
            name='AITrainingLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('report_json',       models.TextField()),
                ('confidence_score',  models.IntegerField(default=0)),
                ('confidence_label',  models.CharField(blank=True, max_length=100)),
                ('n_model_answers',   models.IntegerField(default=0)),
                ('n_key_points',      models.IntegerField(default=0)),
                ('n_exemplars',       models.IntegerField(default=0)),
                ('n_graded_subs',     models.IntegerField(default=0)),
                ('mae',               models.FloatField(default=0.0)),
                ('pearson_r',         models.FloatField(default=0.0)),
                ('grade_band_acc',    models.FloatField(default=0.0)),
                ('similarity_method', models.CharField(default='tfidf', max_length=30)),
                ('created_at',        models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]