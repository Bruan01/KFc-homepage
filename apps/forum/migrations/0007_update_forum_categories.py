# pyright: reportMissingImports=false
"""Update forum categories to 4 domain boards + all board."""
from django.db import migrations


NEW_CATEGORIES = [
    {"slug": "all", "name": "全部", "icon": "全", "color": "#657080", "sort_order": 0},
    {"slug": "product", "name": "产品", "icon": "💼", "color": "#2563eb", "sort_order": 1},
    {"slug": "research", "name": "科研", "icon": "🔬", "color": "#7c3aed", "sort_order": 2},
    {"slug": "agent", "name": "Agent", "icon": "🤖", "color": "#059669", "sort_order": 3},
    {"slug": "hardware", "name": "硬件", "icon": "⚡", "color": "#dc2626", "sort_order": 4},
]


def update_forum_categories(apps, schema_editor):
    category_model = apps.get_model("forum", "ForumCategory")

    # Deactivate all existing categories
    category_model.objects.all().update(is_active=False)

    # Create/update new categories
    for data in NEW_CATEGORIES:
        category_model.objects.update_or_create(
            slug=data["slug"],
            defaults={key: value for key, value in data.items() if key != "slug"},
        )


def restore_old_categories(apps, schema_editor):
    category_model = apps.get_model("forum", "ForumCategory")
    category_model.objects.all().update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("forum", "0006_add_category_moderators"),
    ]

    operations = [
        migrations.RunPython(update_forum_categories, restore_old_categories),
    ]
