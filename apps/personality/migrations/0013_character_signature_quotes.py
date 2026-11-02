from django.db import migrations


KITA_SOURCE = {
    'url': 'https://zh.moegirl.org.cn/zh-cn/%E5%96%9C%E5%A4%9A%E9%83%81%E4%BB%A3',
    'text': '让大家看看吧，其实……后藤同学是非常帅气的！',
}


def add_signature_quotes(apps, schema_editor):
    Character = apps.get_model('personality', 'Character')
    for character in Character.objects.filter(source_id__in=[2162, 87975]).iterator():
        profile = dict(character.profile or {})
        if character.source_id == 2162:
            profile['signature_quote'] = {'text': '自分の言葉は曲げねえ', 'source_url': 'https://naruto-official.com/news/01_1610'}
        else:
            sources = list(character.extra_sources or [])
            if not any(source.get('url') == KITA_SOURCE['url'] for source in sources):
                sources.append(KITA_SOURCE)
                character.extra_sources = sources
            profile['signature_quote'] = {'text': KITA_SOURCE['text'], 'source_url': KITA_SOURCE['url']}
        character.profile = profile
        character.save(update_fields=['profile', 'extra_sources'])


def remove_signature_quotes(apps, schema_editor):
    Character = apps.get_model('personality', 'Character')
    for character in Character.objects.filter(source_id__in=[2162, 87975]).iterator():
        profile = dict(character.profile or {})
        profile.pop('signature_quote', None)
        character.profile = profile
        if character.source_id == 87975:
            character.extra_sources = [source for source in (character.extra_sources or []) if source.get('url') != KITA_SOURCE['url']]
        character.save(update_fields=['profile', 'extra_sources'])


class Migration(migrations.Migration):
    dependencies = [('personality', '0012_model_request_budget')]
    operations = [migrations.RunPython(add_signature_quotes, remove_signature_quotes)]
