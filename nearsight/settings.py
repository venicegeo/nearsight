import os

# DATABASES = {
#         'nearsight': {
#             'ENGINE': 'django.contrib.gis.db.backends.postgis',
#             'NAME': 'postgis',
#             'USER': 'user',
#             'PASSWORD': 'password',
#             'HOST': 'host',
#             'PORT': 'port'
#         }
#     }

# if not locals().get('DATABASES', {}).get('nearsight'):
#     raise Exception("A database was not configured for django fulrum. \n"
#                     "A database called 'nearsight' is expected in DATABASES.")


# OGC_SERVER = {
#     'default': {
#         'BACKEND': 'backend.geoserver',
#         'LOCATION': GEOSERVER_URL,
#         'PUBLIC_LOCATION': GEOSERVER_URL,
#         'USER': 'admin',
#         'PASSWORD': 'xxxxxxx',
#         'DATASTORE': 'exchange_imports',
#     }
# }

NEARSIGHT_UPLOAD_PATH = os.getenv("NEARSIGHT_UPLOAD_PATH")
NEARSIGHT_LAYER_PREFIX = os.getenv("NEARSIGHT_LAYER_PREFIX")
NEARSIGHT_CATEGORY_NAME = os.getenv('NEARSIGHT_CATEGORY_NAME', 'NearSight')
NEARSIGHT_GEONODE_RESTRICTIONS = os.getenv('NEARSIGHT_GEONODE_RESTRICTIONS', "NearSight Data")


S3_CREDENTIALS = [
    # {
    # 's3_bucket': ['my_s3_bucket'],
    # 's3_key': 'XXXXXXXXXXXXXXXXXXXX',
    # 's3_secret': 'XxXxXxXxXxXxXxXxXxXxXxX',
    # 's3_gpg': 'XxXxXxXxXxXxX'
    # }
]

#Define the cache to be used. Memcache is suggested, but other process safe caches can be used too (e.g. file or database)
# CACHES['nearsight'] = CACHES.get('nearsight', {
#         'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
#         'LOCATION': NEARSIGHT_UPLOAD_PATH,
# })
# CACHES['default'] = CACHES.get('default', CACHES.get('nearsight'))

USE_TZ = os.getenv("USE_TZ", True)
TIME_ZONE = os.getenv("TIME_ZONE", 'UTC')
# CELERY_ACCEPT_CONTENT = ['json']
# CELERY_TASK_SERIALIZER = 'json'
# CELERY_RESULT_SERIALIZER = 'json'
# CELERY_SEND_EVENTS = True
CELERYBEAT_USER = os.getenv("CELERYBEAT_USER")
CELERYBEAT_GROUP = os.getenv("CELERYBEAT_GROUP")
CELERYBEAT_SCHEDULER = os.getenv("CELERYBEAT_SCHEDULER", 'djcelery.schedulers.DatabaseScheduler')

CELERYBEAT_SCHEDULE = {}
CELERY_ENABLE_UTC = os.getenv("CELERY_ENABLE_UTC")
NEARSIGHT_SERVICE_UPDATE_INTERVAL = os.getenv("NEARSIGHT_SERVICE_UPDATE_INTERVAL", 5)
SSL_VERIFY = os.getenv("SSL_VERIFY", False)
