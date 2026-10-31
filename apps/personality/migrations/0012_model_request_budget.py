from collections import defaultdict

from django.db import migrations, models
from django.db.models import Count


def initialize_request_usage(apps, schema_editor):
    Assessment = apps.get_model('personality', 'Assessment')
    AnalysisCall = apps.get_model('personality', 'AnalysisCall')
    DailyUsage = apps.get_model('personality', 'DailyUsage')
    PersonalityJob = apps.get_model('personality', 'PersonalityJob')
    daily = defaultdict(int)
    for user_id, created_at in AnalysisCall.objects.values_list('assessment__user_id', 'created_at'):
        daily[(user_id, created_at[:10])] += 1
    for assessment in Assessment.objects.annotate(call_count=Count('analysis_calls')).iterator(chunk_size=200):
        checkpoints = PersonalityJob.objects.filter(assessment_id=assessment.pk).values_list('checkpoint', flat=True)
        recorded = max((state.get('total_requests', 0) for checkpoint in checkpoints for state in [checkpoint.get('single_report', {})] if isinstance(state, dict)), default=0)
        Assessment.objects.filter(pk=assessment.pk, model_requests=0).update(model_requests=max(assessment.call_count, recorded))
    for (user_id, day), count in daily.items():
        usage, _ = DailyUsage.objects.get_or_create(user_id=user_id, day=day)
        DailyUsage.objects.filter(pk=usage.pk, model_requests__lt=count).update(model_requests=count)


class Migration(migrations.Migration):
    dependencies = [('personality', '0011_operationalalert_questionfeedback')]
    operations = [
        migrations.AddField(model_name='assessment', name='model_requests', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='dailyusage', name='model_requests', field=models.PositiveIntegerField(default=0)),
        migrations.RunPython(initialize_request_usage, migrations.RunPython.noop),
    ]
