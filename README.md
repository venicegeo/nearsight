# nearsight

This is a django application which enables importing of nearsight data into GeoNode. 


Since Maploom supports viewing images attached to a features in a web client, it can be used to view NearSight App data.

Maploom pulls the images from a fileservice that has been added to Exchange. The following outlines how `nearsight` app adds the features and images collected by NearSight to Maploom which has been installed as the viewer in GeoNode. 


## Installation
NOTE: For this app to be functional, you should add NEARSIGHT_UPLOAD_PATH and optionally S3_CREDENTIALS.
```
yum install -y git 
git clone https://github.com/venicegeo/nearsight
cd nearsight
pip install -e .
```


##### DATABASES: (Required)
A database in which the geospatial data can be stored. 
Example: 
```
    DATABASES = {
        'nearsight': {
            'ENGINE': 'django.contrib.gis.db.backends.postgis',
            'NAME': *database name*,
            'USER': *database user*,
            'PASSWORD': *database password*,
            'HOST': *database host*,
            'PORT': *database port*,
        }
    }
 ```

##### OGC_SERVER: (Optional)
Server to host layers in the database.
Example:
```
    OGC_SERVER = {
        'default': {
            'BACKEND': 'backend.geoserver',
            'LOCATION': GEOSERVER_URL,
            'PUBLIC_LOCATION': GEOSERVER_URL,
            'USER': 'admin',
            'PASSWORD': 'xxxxxxx',
            'DATASTORE': 'exchange_imports',
        }
    }
```
            
##### NEARSIGHT_UPLOAD_PATH: (Optional)
A file path where user uploaded files or S3 files will be stored while processing.
Example: `NEARSIGHT_UPLOAD_PATH = '/var/lib/geonode/nearsight_data'`

##### S3_CREDENTIALS: (Optional)
Configuration to pull data from an S3 bucket.
Example: 
```
    S3_CREDENTIALS = [{
        's3_bucket': ['my_s3_bucket'],
        's3_key': 'XXXXXXXXXXXXXXXXXXXX',
        's3_secret': 'XxXxXxXxXxXxXxXxXxXxXxX',
        's3_gpg': XxXxXxXxXxXxX'
    }]
```

##### --- NOTE: For this app to be functional, you should add at least one of the options: NEARSIGHT_API_KEYS, NEARSIGHT_UPLOAD_PATH, or S3_CREDENTIALs ---

##### INSTALLED_APPS: (Required)
The name of this app must be added to the installed_app variable so it can run as part of the host django project.
Example: `INSTALLED_APPS += ('nearsight',)`

##### CACHES: (Required)
Define the cache to be used. Memcache is suggested, but other process safe caches can be used too.
Example: 
```
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
            'LOCATION': '127.0.0.1:11211',
        }
    }
```

##### CELERY: (Optional)
If you plan to use celery as a task runner there are several celery variables to define.
Examples:
```
CELERY_ACCEPT_CONTENT=['json']
CELERY_TASK_SERIALIZER='json'
CELERY_RESULT_SERIALIZER='json'
CELERY_SEND_EVENTS=True
CELERYBEAT_USER='exchange'
CELERYBEAT_GROUP='exchange'
CELERYBEAT_SCHEDULER='djcelery.schedulers.DatabaseScheduler'
CELERYBEAT_SCHEDULE = {
    'Update_layers_30_secs': {
        'task': 'nearsight.tasks.task_update_layers',
        'schedule': timedelta(seconds=30),
        'args': None
    },
    'Pull_s3_data_120_secs': {
        'task': 'nearsight.tasks.pull_s3_data',
        'schedule': timedelta(seconds=120),
        'args': None
    },
}
```

##### LEAFLET_CONFIG: (Optional)
Defines the basemaps to be used in the nearsight viewer map. If you plan to use the nearsight viewer, you will need to define your selected basemaps here.
Example: 
```
    LEAFLET_CONFIG = {
        'TILES': [
            ('BasemapName',
             'url-to-basemap-server-here',
             'Attribution for the basemap'),
        ]
    }
```

## Usage
Once up and running you need to configure filters and import data.

To configure the filters, navigate to the django admin console and navigate to nearsight - filters.
Then click on each filter and either make it not active or change the settings.  By default for testing, there are filters active which excludes data in the US.  Optionally, you can switch to show ONLY data in the US, or deactivate the filter.
Filters are available to reduce the amount of undesired redundant data on your remote system.  This is to allow only subsets to exist on the current system. Note that the filters are destructive. If you filter points, the system marks the time that they were "filtered" and won't evaluate them again, so old data won't show up if it was "filtered" previously.  Likewise if you run a new filter on old points, "filtered" points (or media) will be deleted.

To import data you can (all of which will be run through existing filters):
 - upload a geojson zip archive from NearSight through the nearsight_viewer.
 - Enter S3 Credentials to automatically download zip archives from an S3 bucket(s).
 Note that zip files are extracted and imported.  Extracted files are deleted but zip files are left in the NEARSIGHT_UPLOAD_PATH folder.

## Celery Tasks
 - 'nearsight.tasks.task_filter_assets'
 - 'nearsight.tasks.task_filter_features'
    Goes through every layer looks for us phone number and geospatial filter
 - 'nearsight.tasks.pull_s3_data'
    Every 120 seconds, celery-beat triggers this task
    Pulls zip file from S3 and puts it on disk, then runs “process nearsight data”
 - 'nearsight.tasks.task_update_tiles'
    Truncates Geowebcache tiles runs via celery-beat every 30 sec
 - 'nearsight.tasks.update_geonode_layers'
    Publishes a layer in geonode from a geoserver record

##  LICENSE

The code for this project is provided under the Apache 2 license. Any contributions to this repository constitutes agreement with your contribtions being provided under this license. 
