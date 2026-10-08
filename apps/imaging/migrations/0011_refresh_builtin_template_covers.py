from django.db import migrations


COVERS = {
    "warm-dining": ("warm-dining-cover.png", "warm-dining-v2.webp"),
    "product-hero": ("product-hero-cover.png", "product-hero-v2.webp"),
    "campaign-poster": ("campaign-poster-cover.png", "campaign-poster-v2.webp"),
    "story-illustration": ("story-illustration-cover.png", "story-illustration-v2.webp"),
}


def update_covers(apps, schema_editor):
    Template = apps.get_model("imaging", "ImagingTemplate")
    for key, (old_name, new_name) in COVERS.items():
        old_urls = [
            "",
            f"/uploads/imaging/template-covers/{old_name}",
            f"/static/imaging/templates/{key}.png",
        ]
        Template.objects.filter(key=key, is_system=True, cover_url__in=old_urls).update(
            cover_url=f"/static/imaging/templates/{new_name}"
        )


def restore_covers(apps, schema_editor):
    Template = apps.get_model("imaging", "ImagingTemplate")
    for key, (old_name, new_name) in COVERS.items():
        Template.objects.filter(
            key=key, is_system=True,
            cover_url=f"/static/imaging/templates/{new_name}",
        ).update(cover_url=f"/uploads/imaging/template-covers/{old_name}")


class Migration(migrations.Migration):
    dependencies = [("imaging", "0010_imagingprovider_service_type")]

    operations = [migrations.RunPython(update_covers, restore_covers)]
