from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("forum", "0004_forumimage_forumreplylike_forumtopiclink_topicboost_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ForumReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(max_length=16)),
                ("target_id", models.PositiveIntegerField()),
                ("reporter_username", models.CharField(max_length=150)),
                ("reason", models.CharField(max_length=32)),
                ("details", models.TextField(blank=True, default="")),
                ("status", models.CharField(default="pending", max_length=16)),
                ("reviewer_username", models.CharField(blank=True, default="", max_length=150)),
                ("review_note", models.TextField(blank=True, default="")),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "forum_reports",
                "indexes": [models.Index(fields=["status", "-created_at"], name="forum_repor_status_691c1d_idx")],
            },
        ),
        migrations.CreateModel(
            name="ForumModerationAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(max_length=16)),
                ("target_id", models.PositiveIntegerField()),
                ("action", models.CharField(max_length=32)),
                ("admin_username", models.CharField(max_length=150)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "forum_moderation_actions",
                "indexes": [models.Index(fields=["target_type", "target_id", "-created_at"], name="forum_moder_target__709473_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="forumreport",
            constraint=models.UniqueConstraint(
                fields=("target_type", "target_id", "reporter_username"),
                name="uq_forum_reporter_target",
            ),
        ),
    ]
