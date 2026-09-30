from django.db import migrations, models


def migrate_legacy_text_service(apps, schema_editor):
    Provider = apps.get_model("imaging", "ImagingProvider")
    Setting = apps.get_model("catalog", "SystemSetting")
    prefix = "imaging.skill_chat."
    values = dict(Setting.objects.filter(setting_key__startswith=prefix).values_list("setting_key", "setting_value"))
    if not values or Provider.objects.filter(service_type="text").exists():
        return
    base_url = values.get(prefix + "base_url", "").strip()
    model = values.get(prefix + "model", "").strip()
    if not base_url or not model:
        return
    name = values.get(prefix + "name", "Skill 文本编译服务").strip() or "Skill 文本编译服务"
    if Provider.objects.filter(name=name).exists():
        name = f"{name[:110]}（文本）"
    Provider.objects.create(
        service_type="text", name=name, base_url=base_url,
        api_key=values.get(prefix + "api_key", ""), model=model,
        timeout_seconds=int(values.get(prefix + "timeout_seconds", "180")),
        enabled=values.get(prefix + "enabled", "true").lower() not in {"false", "0", "off", "no"},
    )


class Migration(migrations.Migration):
    dependencies = [("imaging", "0009_imagingtemplate_skill_entrypoint_and_more")]
    operations = [
        migrations.AddField(
            model_name="imagingprovider", name="service_type",
            field=models.CharField(choices=[("image", "图片生成"), ("text", "文本编译")], default="image", max_length=10),
        ),
        migrations.RunPython(migrate_legacy_text_service, migrations.RunPython.noop),
    ]
