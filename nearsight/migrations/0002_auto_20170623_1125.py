# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import nearsight.models


class Migration(migrations.Migration):

    dependencies = [
        ('nearsight', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='asset',
            name='asset_data',
            field=models.FileField(storage=nearsight.models.CustomStorage(base_url='/api/fileservice/view/', location=b'/vagrant/.storage/media/fileservice'), upload_to=nearsight.models.get_asset_name),
        ),
    ]
