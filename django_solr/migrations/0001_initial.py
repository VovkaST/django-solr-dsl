# Generated by Django 3.2.15 on 2023-12-16 20:16

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Indexes',
            fields=[
                ('guid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document', models.CharField(db_index=True, editable=False, max_length=255, verbose_name='Document name')),
                ('model', models.CharField(db_index=True, editable=False, max_length=255, verbose_name='Model name')),
                ('updated_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Date and time of last index')),
                ('hints', models.PositiveIntegerField(default=0, editable=False, verbose_name='Count of hints in index')),
            ],
            options={
                'verbose_name': 'Index',
                'verbose_name_plural': 'Indexes',
            },
        ),
    ]
