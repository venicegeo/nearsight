import os
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

setup(
    name='nearsight',
    version='1.0.0',
    author='Radiant Blue',
    author_email='venice@radiantblue.com',
    url='https://github.com/venicegeo/nearsight',
    download_url="https://github.com/venicegeo/nearsight",
    description="Ingest NearSight data to django app",
    long_description=open(os.path.join(here, 'README.md')).read(),
    license='See LICENSE file.',
    packages=find_packages(exclude=["mvp"]),
    include_package_data=True,
    zip_safe=False,
    install_requires=['celery',
                      'django-celery',
                      'django-celery-beat',
                      'python-memcached',
                      'boto3',
                      'pytz',
                      'Pillow',
                      'django',
                      'gsconfig',
                      'requests',
                      'shapely',
                      'gdal'],
    classifiers=['Topic :: Utilities',
                 'Natural Language :: English',
                 'Operating System :: OS Independent',
                 'Intended Audience :: Developers',
                 'Environment :: Web Environment',
                 'Framework :: Django',
                 'Development Status :: 1 - Planning',
                 'Programming Language :: Python :: 2.7'],
)
