# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='trackedpost',
            name='published_at',
            field=models.DateTimeField(blank=True, help_text='Original publication date on the social platform', null=True),
        ),
    ]
