from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personality", "0013_character_signature_quotes")]

    operations = [
        migrations.AddField(
            model_name="character",
            name="mbti_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("INTJ", "INTJ"), ("INTP", "INTP"), ("ENTJ", "ENTJ"), ("ENTP", "ENTP"),
                    ("INFJ", "INFJ"), ("INFP", "INFP"), ("ENFJ", "ENFJ"), ("ENFP", "ENFP"),
                    ("ISTJ", "ISTJ"), ("ISFJ", "ISFJ"), ("ESTJ", "ESTJ"), ("ESFJ", "ESFJ"),
                    ("ISTP", "ISTP"), ("ISFP", "ISFP"), ("ESTP", "ESTP"), ("ESFP", "ESFP"),
                ],
                max_length=4,
            ),
        ),
    ]
