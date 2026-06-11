# Generated migration for adding approval system to Market model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brokerage', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='market',
            name='source',
            field=models.CharField(
                choices=[('polymarket', 'Polymarket'), ('local', 'Local')],
                default='local',
                max_length=16
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='is_approved',
            field=models.BooleanField(
                default=False,
                help_text='Check to show this market on your frontend'
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name='market',
            options={'ordering': ['-created_at']},
        ),
    ]
