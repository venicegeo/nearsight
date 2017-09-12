# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nearsight', '0003_auto_20170718_1326'),
    ]

    operations = [
        migrations.AlterField(
            model_name='layer',
            name='layer_uid',
            field=models.CharField(default='Unknown', max_length=100),
        ),
    ]
