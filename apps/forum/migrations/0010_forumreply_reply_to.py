# pyright: reportMissingImports=false
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("forum", "0009_forumreply_image_ids_forumpoll_forumpolloption_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="forumreply",
            name="reply_to",
            field=models.ForeignKey(
                blank=True,
                db_column="reply_to_id",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="forum.forumreply",
            ),
        ),
    ]
