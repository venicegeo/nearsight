# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nearsight', '0002_auto_20170628_1243'),
    ]

    operations = [
        migrations.AddField(
            model_name='layer',
            name='layer_source',
            field=models.CharField(default='Unknown', max_length=256),
            preserve_default=False,
        ),
    ]
