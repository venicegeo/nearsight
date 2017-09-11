# Copyright 2016, RadiantBlue Technologies, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dateutil import parser
import requests
import json
import csv
from django.conf import settings
from .models import Layer, get_data_dir
import time
from geoserver.catalog import Catalog, FailedRequestError
from geoserver.layer import Layer as GeoserverLayer
from django.db import connection, connections, ProgrammingError, OperationalError, transaction
from django.db.utils import ConnectionDoesNotExist, IntegrityError
import re
import shutil
from django.core.files import File
import os
from .models import Asset, get_type_extension, Feature
from .filters import run_filters
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import logging
import subprocess
import uuid
from httplib import ResponseNotReady

logger = logging.getLogger(__name__)
nearsight_status = {"status": ""}

class NearSight:

    # Note: Currently this method is not called anywhere, if it is needed in the future it will need to be modified
    # since it theoretically can create a layer.
    @staticmethod
    def ensure_layer(layer_name=None, layer_id=None):
        """
            A wrapper for write_layer
        Args:
            layer_name: layer name
            layer_id: An id for the layer (presumably assigned from NearSight.)

        Returns:
            The layer and notification of creation as a tuple.
        """
        return write_layer(name=layer_name, layer_id=layer_id)


    def convert_to_geojson(self, records, element_map, media_map):
        """

        Args:
            records: A dict of records, from NearSight
            element_map: See get_element_map.
            media_map: See get_media_map.

        Returns:
            A dict representing a geojson.

        """
        features = []
        for record in records:
            feature = {"type": "Feature",
                       "geometry": {"type": "Point",
                                    "coordinates": [record.get('longitude'),
                                                    record.get('latitude')]
                                    }}
            properties = {}
            for record_index in record:
                if record_index == 'form_values':
                    properties.update(self.form_values_to_properties(record.get('form_values'),
                                                                     element_map,
                                                                     media_map))
                else:
                    properties[record_index] = record[record_index]
            feature['properties'] = properties
            features += [feature]
        geojson = {"type": "FeatureCollection", "features": features}
        return geojson

    @staticmethod
    def get_element_map(form):
        """

        Args:
            form: A dict with the form information from NearSight.

        Returns:
            A dict where the key is the id value from nearsight,
            and the value is the actual name to be used in the geojson as the property name.
        """
        elements = form.get('elements')
        element_map = {}
        for element in elements:
            element_map[element.get('key')] = element.get('data_name')
        return element_map

    @staticmethod
    def get_media_map(form, element_map):
        """

        Args:
            form: A dict with the form information from NearSight.
            element_map: See get_element_map.

        Returns:
            An array where where the key is the name of a property, and the value is the type of media it is.

        """
        elements = form.get('elements')
        field_type = {'PhotoField': 'photos', 'VideoField': 'videos', 'AudioField': 'audio'}
        field_map = {}
        media_map = {}
        for element in elements:
            if field_type.get(element.get('type')):
                field_map[element.get('key')] = field_type.get(element.get('type'))
        for key in field_map:
            if element_map.get(key):
                media_map[element_map[key]] = field_map.get(key)
        return media_map


def chunks(a_list, chunk_size):
    """

    Args:
        a_list: A list.
        chunk_size: Size of each sub-list.

    Returns:
        A list of sub-lists.
    """
    for i in xrange(0, len(a_list), chunk_size):
        yield a_list[i:i + chunk_size]


def convert_to_epoch_time(date):
    """

    Args:
        date: A ISO standard date string

    Returns:
        An integer representing the date.
    """
    return int(time.mktime(parser.parse(date).timetuple()))


def append_time_to_features(features, properties_key_of_date=None):
    """

    Args:
        features: An array of features.
        properties_key_of_date: A string which is the key value in the properties dict,
        where a date string can be found.

    Returns:
        The array of features, where the date was converted to an int, and appended as a key.

    """
    if type(features) != list:
        features = [features]

    if not properties_key_of_date:
        properties_key_of_date == 'updated_at'

    for feature in features:
        feature['properties']["{}_time".format(properties_key_of_date)] = convert_to_epoch_time(
                feature.get('properties').get(properties_key_of_date))

    return features


def process_nearsight_data(f, request=None):
    """

    Args:
        f: Is the name of a zip file.

    Returns:
        An array layers from the zip file if it is successfully uploaded.
    """
    global nearsight_status
    layers = []

    try:
        archive_name = f.name
    except AttributeError:
        archive_name = f
    file_path = os.path.join(get_data_dir(), archive_name)
    if save_file(f, file_path):
        unzip_path = unzip_file(file_path)
        logger.info("Reading files from: {0}".format(unzip_path))
        for folder, subs, files in os.walk(unzip_path):
            for filename in files:
                logger.debug('Nearsight scanning file: {0} for .geojson extension.'.format(filename))
                if '.geojson' in filename:
                    if 'changesets' in filename:
                        # Changesets aren't implemented here, they need to be either handled with this file, and/or
                        # handled implicitly with geogig.
                        continue
                    geojson_file_loc = os.path.abspath(os.path.join(folder, filename))
                    logger.info("Uploading the geojson file: {}".format(geojson_file_loc))
                    nearsight_status["status"] = "Uploading the geojson file: {}".format(geojson_file_loc)

                    if upload_geojson(zip_path = file_path, file_path=geojson_file_loc, request=request):
                        layers += [os.path.splitext(filename)[0]]
                    else:
                        return []
                if '.csv' in filename:
                    csv_file_loc = os.path.abspath(os.path.join(folder, filename))
                    logger.info("Uploading the csv file: {}".format(csv_file_loc))
                    nearsight_status["status"] = "Uploading the csv file: {}".format(csv_file_loc)
                    if upload_csv(zip_path = file_path, file_path=csv_file_loc, request=request):
                        layers += [os.path.splitext(filename)[0]]
                    else:
                        return []

        shutil.rmtree(os.path.splitext(file_path)[0])
    return layers


def filter_features(features, **kwargs):
    """
    Args:
        features: A dict formatted like a geojson, containing features to be passed through various filters.

    Returns:
        The filtered features and the feature count as a tuple.
    """
    global nearsight_status
    nearsight_status["status"] = "Running filters on features (this may take awhile)"
    filtered_features, filtered_feature_count = run_filters.filter_features(features, **kwargs)
    nearsight_status["status"] = "{} features passed the filter".format(filtered_feature_count)
    return filtered_features, filtered_feature_count


def save_file(f, file_path):
    """
    This is designed to specifically look for zip files.

    Args:
        f: A url file object.
        file_path: The name of a file to move.

    Returns:
        True if file is moved.
    """

    if os.path.splitext(file_path)[1] != '.zip':
        return False
    if os.path.exists(file_path):
        return True
    try:
        with open(file_path, 'wb+') as destination:
            for chunk in f.chunks():
                destination.write(chunk)
    except IOError:
        logger.error("Failed to save the file: {0} to {1}".format(f.name, file_path))
        return False
    logger.info("Saved the file: {}".format(f.name))
    return True


def unzip_file(file_path):
    import zipfile
    global nearsight_status
    logger.info("Unzipping the file: {}".format(file_path))
    nearsight_status["status"] = "Unzipping the file: {}".format(file_path)
    unzip_path = os.path.join(get_data_dir(), os.path.splitext(file_path)[0])
    with zipfile.ZipFile(file_path) as zf:
        zf.extractall(unzip_path)
    return unzip_path


def upload_geojson(zip_path=None, file_path=None, geojson=None, request=None):
    """

    Args:
        file_path: The full path of a file containing a geojson.
        geojson: A dict formatted like a geojson.

    Returns:
        True if every step successfully completes.

    """

    from_file = False
    if file_path and geojson:
        logger.warn("upload_geojson() must take file_path OR features")
        return False
    elif geojson:
        geojson = geojson
    elif file_path:
        with open(file_path, 'r+') as data_file:
            geojson = json.load(data_file)
    else:
        logger.error("upload_geojson() must take file_path OR features")
        return False

    filtered_features, filtered_count = filter_features(geojson)

    if not filtered_features:
        logger.info("No features passed the filter for file: {0}".format(file_path))
        return False

    if filtered_features.get('features'):
        features = filtered_features.get('features')
    else:
        logger.info("Upload for file_path {}, contained no features.".format(file_path))
        return False

    if type(features) != list:
        features = [features]

    uploads = []
    count = 0
    total = len(features)
    file_basename = os.path.splitext(os.path.basename(file_path))[0]
    layer, created = write_layer(name=file_basename, layer_source_zip=zip_path)
    media_keys = get_update_layer_media_keys(media_keys=find_media_keys(features), layer=layer)

    field_map = get_field_map(features)
    prototype = get_prototype(field_map)

    id_field = get_feature_id_fieldname(features[0])

    nearsight_id = get_nearsight_id_fieldname()
    global nearsight_status
    nearsight_status["progress"] = { "total": total, "completed": 0 }
    for feature in features:
        if not feature:
            continue
        if not feature.get('geometry'):
            continue
        for key in field_map:
            if key not in feature.get('properties'):
                feature['properties'][key] = prototype.get(key)
                if isinstance(feature['properties'][key], type(None)):
                    feature['properties'][key] = ''
        for media_key in media_keys:
            if feature.get('properties').get(media_key):
                urls = []
                if type(feature.get('properties').get(media_key)) == list:
                    asset_uids = feature.get('properties').get(media_key)
                else:
                    asset_uids = feature.get('properties').get(media_key).split(',')
                for asset_uid in asset_uids:
                    asset, created = write_asset_from_file(asset_uid,
                                                           media_keys[media_key],
                                                           os.path.dirname(file_path))
                    if asset:
                        if asset.asset_data:
                            if getattr(settings, 'FILESERVICE_CONFIG', {}).get('url_template'):
                                urls += ['{}{}.{}'.format(getattr(settings,
                                                                  'FILESERVICE_CONFIG',
                                                                  {}).get('url_template').rstrip("{}"),
                                                          asset_uid,
                                                          get_type_extension(media_keys[media_key]))]
                            else:
                                urls += [asset.asset_data.url]
                    else:
                        urls += [""]
                feature['properties']['{}_url'.format(media_key)] = urls
            elif from_file and not feature.get('properties').get(media_key):
                feature['properties'][media_key] = ""
                feature['properties']['{}_url'.format(media_key)] = ""
        if feature.get('properties').get(id_field):
            feature['properties'][nearsight_id] = feature.get('properties').get(id_field)
        else:
            feature['properties'][nearsight_id] = feature.get('properties').get('id')
        feature['properties'].pop(id_field, None)

        nearsight_status["status"] = "writing feature: {0} of {1} for layer: {2}".format(count+1, total, layer.layer_name)
        write_feature(feature.get('properties').get(nearsight_id),
                      feature.get('properties').get('version'),
                      layer,
                      feature)
        uploads += [feature]
        count += 1
        nearsight_status["progress"]["completed"] = count

    # reset progress indicator
    nearsight_status["progress"] = { "total": 0, "completed": 0 }

    try:
        database_alias = 'nearsight'
        connections[database_alias]
    except ConnectionDoesNotExist:
        database_alias = None

    table_name = layer.layer_name
    nearsight_status["status"] = "uploading features to GeoServer..."
    if upload_to_db(uploads, table_name, media_keys, database_alias=database_alias):
        nearsight_status["status"] = "publishing layer to GeoServer ..."
        gs_layer, _ = publish_layer(table_name, database_alias=database_alias)
        if gs_layer is None:
            nearsight_status["status"] = "Error: publishing layer to GeoServer failed"
            return False
        nearsight_status["status"] = "updating GeoNode layers..."
        update_geonode_layers(gs_layer, request=request)
    else:
        nearsight_status["status"] = "Error: upload to GeoServer failed"
        return False
    nearsight_status["status"] = "Success: all operations complete"
    return True


def upload_csv(zip_path=None, file_path=None, geojson=None, request=None):
    """

    Args:
        file_path: The full path of a file containing a csv.
        csv: the actual csv to be parsed and converted to geojson.

    Returns:
        True if every step successfully completes.

    """

    # first serialize the layer
    global nearsight_status
    nearsight_status["progress"] = { "total": 0, "completed": 0 }

    file_basename = os.path.splitext(os.path.basename(file_path))[0]
    media = {"photos": "photos", "audio": "audio", "videos": "videos"}
    layer, created = write_layer(name=file_basename, media_keys=media, layer_source_zip=zip_path)

    # need to open the csv and write each feature to the feature table
    # need geometry, type, and properties as values
    nearsight_id = get_nearsight_id_fieldname()
    col_headers = []
    features_list = []

    with open(file_path, 'rb') as csvfile:
        csv_reader = csv.reader(csvfile, delimiter=',', quotechar='"')
        row_count = 0
        total = sum(1 for rows in csv_reader)
        csvfile.seek(0)
        nearsight_status["progress"]["total"] = total
        nearsight_status["status"] = "Reading features from file"

        is_fulcrum_csv = False
        for row in csv_reader:
            template_feature = {"type": "Feature",
                                "geometry": {"type": "Point", "coordinates": []},
                                "properties": {}}
            col_count = 0
            for col in row:
                if row_count == 0:
                    col_headers.append(col)
                else:
                    if col_headers[col_count] == 'PRODUCT_ID':
                         # get ID and version from class'd csv
                        template_feature['properties'][nearsight_id] = col
                        # TODO Below is a hack since these csv files do not contain a version so we just use the ID
                        template_feature['properties']['version'] = col
                    elif col_headers[col_count] == 'fulcrum_id':
                        # handle getting ID from fulcrum based csv
                        is_fulcrum_csv = True
                        template_feature['properties'][nearsight_id] = col
                    elif col_headers[col_count] == 'version':
                        # handle getting version from fulcrum based csv
                        template_feature['properties']['version'] = col
                    elif col_headers[col_count] == 'photos_url':
                        # don't use the urls from the file because we will be writing new ones
                        continue
                    elif col_headers[col_count] == 'photos':
                        # handle getting media from fulcrum based csv
                        template_feature['properties'][col_headers[col_count]] = col
                        photos_list = col.split(",")
                        template_feature['properties']['photos_url'] = []
                        for photo in photos_list:
                            asset, created = write_asset_from_file(photo, 'photos', os.path.dirname(file_path))
                            template_feature['properties']['photos_url'].append(asset.asset_data.url)
                    elif col_headers[col_count] == 'PHOTO_VIDEO':
                        # get media from class'd csv
                        # check if the item is photo or video and store the name (it will always be the same as the id)
                        asset_id = template_feature['properties'][nearsight_id]

                        if 'p' in col or 'P' in col:
                            template_feature['properties']['photos'] = asset_id
                            asset, created = write_asset_from_file(asset_id, 'photos', os.path.dirname(file_path))
                            template_feature['properties']['photos_url'] = asset.asset_data.url
                        if 'v' in col or 'V' in col:
                            template_feature['properties']['videos'] = asset_id
                            asset, created = write_asset_from_file(asset_id, 'videos', os.path.dirname(file_path))
                            template_feature['properties']['videos_url'] = asset.asset_data.url
                    else:
                        template_feature['properties'][col_headers[col_count]] = col
                col_count += 1
            if row_count != 0 and template_feature['properties'][nearsight_id] != '':
                # set the position based on lat lon we read
                if is_fulcrum_csv is not True:
                    template_feature['geometry']['coordinates'] = [template_feature['properties']['LON'], template_feature['properties']['LAT']]
                else:
                    template_feature['geometry']['coordinates'] = [template_feature['properties']['longitude'], template_feature['properties']['latitude']]
                features_list.append(template_feature)
                nearsight_status["status"] = "writing feature: {0} of {1} for layer: {2}".format(row_count+1, total, layer.layer_name)
                write_feature(template_feature.get('properties').get(nearsight_id),
                    1,
                    layer,
                    template_feature)
                nearsight_status["progress"]["completed"] = row_count
            logger.debug("found row "+str(row_count))
            row_count += 1

    # reset progress indicator
    nearsight_status["progress"] = { "total": 0, "completed": 0 }

    try:
        database_alias = 'nearsight'
        connections[database_alias]
    except ConnectionDoesNotExist:
        database_alias = None

    table_name = layer.layer_name
    nearsight_status["status"] = "uploading features to GeoServer..."
    if upload_to_db(features_list, table_name, media, database_alias=database_alias):
        nearsight_status["status"] = "publishing layer to GeoServer ..."
        gs_layer, _ = publish_layer(table_name, database_alias=database_alias)
        if gs_layer is None:
            nearsight_status["status"] = "Error: publishing layer to GeoServer failed"
            return False
        nearsight_status["status"] = "updating GeoNode layers..."
        update_geonode_layers(gs_layer, request=request)
    else:
        nearsight_status["status"] = "Error: upload to GeoServer failed"
        return False

    nearsight_status["status"] = "Success: all operations complete"
    return True


def find_media_keys(features):
    """
    Args:
        features: An array of features as a dict object.
    Returns:
        A value of keys and types for media fields.
    """
    key_map = {}
    asset_types = {'photos': 'jpg', 'videos': 'mp4', 'audio': 'm4a'}
    for feature in features:
        for prop_key, prop_val in feature.get('properties').iteritems():
            if '_url' in prop_key:
                media_key = prop_key.rstrip("_url")
                for asset_key in asset_types:
                    if prop_val:
                        if asset_key in prop_val:
                            key_map[media_key] = asset_key
                    elif asset_key in prop_key:
                        key_map[media_key] = asset_key
                if not key_map.get(media_key):
                    key_map[media_key] = 'photos'
    return key_map


def get_update_layer_media_keys(media_keys=None, layer=None):
    """
    Used to keep track of which properties are actually media files.
    Args:
        media_keys: A dict where the key is the property, and the value is the type (i.e. {'pic':'photos'})
        layer: A django model object representing the layer

    Returns:
        The Layer media keys.
    """
    logger.debug("get_update_layer_media_keys({0},{1})".format(media_keys, layer))
    with transaction.atomic():
        layer_media_keys = json.loads(layer.layer_media_keys)
        for media_key in media_keys:
            if not layer_media_keys.get(media_key):
                layer_media_keys[media_key] = media_keys.get(media_key)
            # Since photos is the default for a media key of unknown format, we should update it given the chance.
            elif layer_media_keys.get(media_key) == 'photos':
                layer_media_keys[media_key] = media_keys.get(media_key)
        layer.layer_media_keys = json.dumps(layer_media_keys)
        layer.save()
        return layer_media_keys


def write_layer(name, layer_id='', date=0, layer_source_zip=None, media_keys=None):
    """
    Args:
        name: An SQL compatible string.
        layer_id: A unique ID for the layer
        date: An integer representing the date
        media_keys: See NearSightImporter.get_media_map

    Returns:
        The layer model object.
    """
    if not media_keys:
        media_keys = {}
    with transaction.atomic():
        layer_prefix = ''
        if getattr(settings, 'NEARSIGHT_LAYER_PREFIX'):
            layer_prefix = "{0}_".format(settings.NEARSIGHT_LAYER_PREFIX)
        layer_name = '{0}{1}'.format(layer_prefix, name.lower())
        logger.debug("writing layer: {0}".format(layer_name))
        try:
            layer, layer_created = Layer.objects.get_or_create(layer_name=layer_name,
                                                               layer_uid=layer_id,
                                                               layer_source=layer_source_zip,
                                                               defaults={'layer_date': int(date),
                                                                         'layer_media_keys': json.dumps(media_keys)})
            return layer, layer_created
        except IntegrityError:
            layer = Layer.objects.get(layer_name=layer_name)
            return layer, False


def write_feature(key, version, layer, feature_data):
    """

    Args:
        key: A unique key as a string, presumably the NearSight UID.
        version: A version number for the feature as an integer, usually provided by NearSight.
        layer: The layer model object, which represents the NearSight App (AKA the layer).
        feature_data: The actual feature data as a dict, mapped like a geojson.

    Returns:
        The feature model object.
    """
    global nearsight_status

    if key is None:
        key = uuid.uuid4()

    with transaction.atomic():
        logger.debug("write_feature({0}, {1}, {2}, {3})".format(key, version, layer, feature_data))
        feature, feature_created = Feature.objects.get_or_create(feature_uid=key,
                                                                 feature_version=version,
                                                                 defaults={'layer': layer,
                                                                           'feature_data': json.dumps(feature_data)})
        return feature



def get_feature_id_fieldname(feature):
    default_id = 'id'
    if not feature:
        return default_id

    properties = feature.get('properties')

    # first look for fulcrum_id as this is the most likely candidate
    if properties.get('fulcrum_id') is not None:
        logger.debug("Feature ID is fulcrum_id")
        return 'fulcrum_id'

    # otherwise check remaining properties for any sort of ID
    # this is probably not a good idea in the long run since ID
    # may come from change set or parent ID
    for property in properties:
        if '_id' in property or property in ['fid', 'id']:
            if properties.get(property) is None:
                # if the value is None keep looking
                continue
            logger.debug("Feature ID is {0}".format(property))
            return property
    logger.debug("Feature ID defaulting to {0}".format(default_id))
    return default_id


def get_nearsight_id_fieldname():
    return "nearsight_id"


def write_asset_from_file(asset_uid, asset_type, file_dir):
    """

    Args:
        asset_uid: The assigned ID from NearSight.
        asset_type: A string of 'Photos', 'Videos', or 'Audio'.
        from the nearsight site based on the UID and type.
        file_dir: A string for the file directory.

    Returns:
        A tuple of the asset model object, and a boolean representing 'was created'.
    """
    file_path = os.path.join(file_dir, '{}.{}'.format(asset_uid, get_type_extension(asset_type)))
    with transaction.atomic():
        asset, created = Asset.objects.get_or_create(asset_uid=asset_uid, asset_type=asset_type)
        if created:
            if os.path.isfile(file_path):
                with open(file_path, 'rb') as open_file:
                    logger.debug("writing file: {0}".format(file_path))
                    try:
                        asset.asset_data.save(asset_uid, File(open_file))
                    except Exception as e:
                        logger.error("THERE WAS AN ERROR SAVING FILE {0}".format(file_path))
                        logger.error(e)
            else:
                logger.info("The file {} was not found, and is most likely missing from the archive, "
                      "or was filtered out (if using filters).".format(file_path))
                return None, False
        return asset, created


def is_valid_photo(photo_file_path, **kwargs):
    """
    Args:
        photo_file_path: A File object of a photo:

    Returns:
         True if the photo does not contain us-coords.
         False if the photo does contain us-coords.
    """
    # https://gist.github.com/erans/983821#file-get_lat_lon_exif_pil-py-L40

    info = None
    try:
        im = Image.open(photo_file_path)
        info = im._getexif()
    except Exception as e:
        logger.warn("Failed to get exif data")
        logger.warn(e)
    if info:
        properties = get_gps_info(info)
    else:
        return True
    if properties.get('GPSInfo'):
        coords = get_gps_coords(properties)
        if coords:
            features = []
            feature = {"type": "Feature",
                       "geometry": {"type": "Point",
                                    "coordinates": [coords[1], coords[0]]
                                    },
                       "properties": properties
                       }
            features += [feature]
            geojson = {"type": "FeatureCollection", "features": features}
            filtered_features, count = filter_features(geojson, **kwargs)
            if filtered_features:
                return True
            else:
                return False
        else:
            return True
    else:
        return True


def get_gps_info(info):
    """
    Args:
         info: A json object of exif photo data

    Returns:
        A json object of exif photo data with decoded gps_data:
    """
    properties = {}
    if info.iteritems():
        for tag, value in info.iteritems():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_data = {}
                if value:
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                properties[decoded] = gps_data
            elif decoded != "MakerNote":
                properties[decoded] = value
    return properties


def get_gps_coords(properties):
    """
    Args:
         properties: A json containing decoded exif gps data:

    Returns:
         An array of coordinates in Decimal Degrees:
    """
    try:
        gps_info = properties["GPSInfo"]
        gps_lat = gps_info["GPSLatitude"]
        gps_lat_ref = gps_info["GPSLatitudeRef"]
        gps_long = gps_info["GPSLongitude"]
        gps_long_ref = gps_info["GPSLongitudeRef"]
    except KeyError:
        logger.warn("Could not get lat/long")
        return None

    lat = convert_to_degrees(gps_lat)
    if gps_lat_ref != "N":
        lat = 0 - lat

    lon = convert_to_degrees(gps_long)
    if gps_long_ref != "E":
        lon = 0 - lon

    coords = [round(lat, 6), round(lon, 6)]
    return coords


def convert_to_degrees(value):
    """
    Args:
        value: An exif format coordinate:

    Returns:
        Float value of a coordinate in Decimal Degree format
    """
    d0 = value[0][0]
    d1 = value[0][1]
    d = float(d0) / float(d1)

    m0 = value[1][0]
    m1 = value[1][1]
    m = float(m0) / float(m1)

    s0 = value[2][0]
    s1 = value[2][1]
    s = float(s0) / float(s1)

    return d + (m / 60.0) + (s / 3600.0)


def update_geonode_layers(geoserver_layer, request=None):
    """
    Asynchronously runs gs_slup to update a GeoNode layer.
    Returns: None
    """
    from .tasks import update_geonode_layers

    owner = 'admin'
    if request:
        owner = request.user.username

    params = dict(filter=geoserver_layer.name, owner=owner, execute_signals=True)

    if isinstance(geoserver_layer, GeoserverLayer):
        params.setdefault('workspace', geoserver_layer.resource.workspace.name)
        params.setdefault('store', geoserver_layer.resource.store.name)

    else:
        params.setdefault('workspace', geoserver_layer.workspace.name)
        params.setdefault('store', geoserver_layer.store.name)

    update_geonode_layers.delay(**params)


def upload_to_db(feature_data, table, media_keys, database_alias=None):
    """

    Args:
        feature_data: A dict mapped as a geojson.
        table: The name of the layer being added. If exists it will data will be appended,
            else a new table will be created.
        media_keys: A dict where the key is the name of a properties field containing
            a media file, and the value is the type (i.e. {'bldg_pic': 'photos'})
        database_alias: Alias of database in the django DATABASES dict.
    Returns:
        True, if no errors occurred.
    """
    if not is_db_supported(database_alias):
        return False

    if not feature_data:
        return False

    if type(feature_data) != list:
        feature_data = [feature_data]

    if any(app in settings.INSTALLED_APPS for app in ['geoshape', 'geonode', 'exchange']):
        feature_data = prepare_features_for_geonode(feature_data, media_keys=media_keys)

    key_name = get_nearsight_id_fieldname()

    # Sort the data in memory before making a ton of calls to the server.
    feature_data, non_unique_features = get_duplicate_features(features=feature_data, properties_id=key_name)

    # Use ogr2ogr to create a table and add an index, before any non unique values are added.
    if not table_exists(table=table, database_alias=database_alias):
        ogr2ogr_geojson_to_db(geojson_file=features_to_file(feature_data[0]),
                              database_alias=database_alias,
                              table=table)
        add_unique_constraint(database_alias=database_alias, table=table, key_name=key_name)
        if len(feature_data) > 1:
            feature_data = feature_data[1:]
        else:
            feature_data = None

    # Try to upload the presumed unique values in bulk.
    uploaded = False
    while not uploaded:
        if not feature_data:
            break
        feature_data, non_unique_feature_data = check_db_for_features(feature_data,
                                                                      table,
                                                                      database_alias=database_alias)
        if non_unique_feature_data:
            update_db_features(non_unique_feature_data, table, database_alias=database_alias)

        if feature_data:
            ogr2ogr_geojson_to_db(geojson_file=features_to_file(feature_data),
                                  database_alias=database_alias,
                                  table=table)
        else:
            uploaded = True

    # Finally update one by one all of the features we know are in the database
    if non_unique_features:
        update_db_features(non_unique_features, table, database_alias=database_alias)
    return True


def is_db_supported(database_alias=None):
    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection
    db_conn.close()

    if 'postgis' not in db_conn.settings_dict.get('ENGINE') and 'postgres' not in db_conn.settings_dict.get('ENGINE'):
        return False
    else:
        return True


def prepare_features_for_geonode(feature_data, media_keys=None):
    """

    Args:
        feature_data: An array of features, to be prepared for best viewing in geonode.
        media_keys: A list of the properties keys which map to media files.

    Returns:
        A list of the features, with slightly modified properties.

    """



    if not feature_data:
        return None

    if type(feature_data) != list:
        feature_data = [feature_data]

    if not media_keys:
        return feature_data

    logger.debug('preparing {} features for geonode'.format(len(feature_data)))

    maploom_media_keys = ["photos", "videos", "audios", "fotos"]

    for feature in feature_data:
        new_props = {}
        delete_prop = []
        for prop in feature.get('properties'):
            if not prop:
                continue
            if prop.lower() == "name":
                new_props['nearsight_name'] = feature.get('properties').get(prop)
                delete_prop += [prop]
            if not feature.get('properties').get(prop):
                feature['properties'][prop] = ''
            for mmkey in maploom_media_keys:
                if prop.startswith(mmkey) and prop not in media_keys:
                    new_props['prop_{}'.format(prop)] = feature.get('properties').get(prop)
                    delete_prop += [prop]
        feature['properties'].update(new_props)
        for media_key, media_val in media_keys.iteritems():
            if ('{}_caption'.format(media_key)) in feature.get('properties'):
                feature['properties']['caption_{}'.format(media_key)] = \
                    ", ".join(feature['properties'].get('{}_caption'.format(media_key)))
                try:
                    del feature['properties']['{}_caption'.format(media_key)]
                    if feature.get('properties').get('prop_{}_caption'.format(media_key)):
                        del feature['properties']['prop_{}_caption'.format(media_key)]
                except KeyError:
                    pass
            try:
                url_prop = "{}_url".format(media_key)
                del feature['properties'][url_prop]
            except KeyError:
                pass
            media_ext = get_type_extension(media_val)
            if media_val == 'audio':
                # nearsight calls it something, maploom calls it something else.
                media_val = 'audios'
            if media_val != media_key:
                new_key = '{}_{}'.format(media_val, media_key)
            else:
                new_key = media_val

            if feature.get('properties').get(media_key):
                media_assets = feature.get('properties').get(media_key)
                try:
                    media_assets = ["{}".format(file_name)
                                    for file_name in media_assets.split(',')]
                except AttributeError:
                    pass
                if media_assets[0]:
                    if not os.path.splitext(media_assets[0])[1]:
                        media_assets = ["{}.{}".format(os.path.basename(file_name), media_ext)
                                        for file_name in media_assets]
                    else:
                        media_assets = ["{}".format(os.path.basename(file_name))
                                        for file_name in media_assets]
                    feature['properties'][new_key] = json.dumps(media_assets)
            else:
                feature['properties'][new_key] = json.dumps([])
        for del_prop in delete_prop:
            try:
                del feature['properties'][del_prop]
            except KeyError:
                pass
    return feature_data


def features_to_file(features, file_path=None):
    """Write a geojson to file.

    Args:
        features: A list of features.
        file_path: The path to write the file to.

    Returns:
        The location of the geojson file that was written..
    """
    if not file_path:
        try:
            file_path = os.path.join(get_data_dir(), 'temp.geojson')
            file_path = '/'.join(file_path.split('\\'))
        except AttributeError:
            logger.error("ERROR: Unable to write features_to_file because " \
                  "file_path AND get_data_dir() are not defined.")

    if not features:
        return None

    if type(features) == list:
        feature_collection = {"type": "FeatureCollection", "features": features}
    else:
        feature_collection = {"type": "FeatureCollection", "features": [features]}

    with open(file_path, 'w') as open_file:
        open_file.write(json.dumps(feature_collection))

    return file_path


def get_pg_conn_string(database_alias=None):
    """

    Args:
        database_alias: Database dict from the django settings.

    Returns:
        A string needed to connect to postgres.
    """

    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection

    return "host={host} " \
           "port={port} " \
           "dbname={database} " \
           "user={user} " \
           "password={password}".format(host=db_conn.settings_dict.get('HOST'),
                                        port=db_conn.settings_dict.get('PORT'),
                                        database=db_conn.settings_dict.get('NAME'),
                                        user=db_conn.settings_dict.get('USER'),
                                        password=db_conn.settings_dict.get('PASSWORD'))


def ogr2ogr_geojson_to_db(geojson_file, database_alias=None, table=None):
    """Uses an ogr2ogr script to upload a geojson file.

    Args:
        geojson_file: A geojson file.
        database_alias: Database dict from the django settings.
        table: A DB table.

    Returns:
        True if the file is succesfully uploaded.
    """

    if not geojson_file:
        return False

    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection

    if 'postgis' in db_conn.settings_dict.get('ENGINE') or 'postgres' in db_conn.settings_dict.get('ENGINE'):
        db_format = 'PostgreSQL'
        dest = "PG:'{0}'".format(get_pg_conn_string(database_alias))
        options = ['-update', '-append']
    else:
        return True

    execute_append = ['ogr2ogr',
                      '-f', db_format,
                      '-skipfailures',
                      dest,
                      '{}'.format(geojson_file),
                      '-nln', table] + options
    logger.debug("Executing: {0}".format(' '.join(execute_append)))
    proc = subprocess.Popen(' '.join(execute_append), shell=True, executable='/bin/bash',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    std_out, std_err = proc.communicate()
    exitcode = proc.wait()
    if exitcode != 0:
        logger.error('ogr2ogr call failed')
        logger.error('{0}'.format(std_out))
        logger.error('{0}'.format(std_err))
        logger.error('ogr2ogr returned: {0}'.format(proc.returncode))
        return False
    return True


def add_unique_constraint(database_alias=None, table=None, key_name=None):
    """Adds a unique constraint to a table.

    Args:
        database_alias: Database dict from the django settings.
        table: A DB tables
        key_name: The column to create the unique index on.

    Returns:
        None
    """
    if not is_alnum(table):
        return None

    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection

    cur = db_conn.cursor()

    if 'postgis' in db_conn.settings_dict.get('ENGINE') or 'postgres' in db_conn.settings_dict.get('ENGINE'):
        query = "ALTER TABLE {} ADD UNIQUE({});".format(table, key_name)
    else:
        return False
    #
    # if 'sqlite' in db_conn.settings_dict.get('NAME'):
    #     query = "CREATE UNIQUE INDEX unique_{key_name} on {table}({key_name})".format(table=table, key_name=key_name)
    # else:
    #     query = "ALTER TABLE {} ADD UNIQUE({});".format(table, key_name)

    try:
        with transaction.atomic():
            cur.execute(query)
    except ProgrammingError as pe:
        logger.error("Unable to add a key because {} was not created yet.".format(table))
        logger.error(pe)
    finally:
        cur.close()
        db_conn.close()


def table_exists(database_alias=None, table=None):
    """

    Args:
        database_alias: Database dict from the django settings.
        table: The table to check.

    Returns:
        True if table exists.
    """
    if not is_alnum(table):
        return None

    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection

    cur = db_conn.cursor()

    query = "select * from {0};".format(table)

    try:
        with transaction.atomic():
            cur.execute(query)
        does_table_exist = True
    except ProgrammingError:
        does_table_exist = False
    except OperationalError:
        does_table_exist = False
    finally:
        cur.close()
        db_conn.close()
    return does_table_exist


def check_db_for_features(features, table, database_alias=None):
    """This searches a database table to see if and of the features already exist in the DB.

    Args:
        features: A dict structured like a geojson of features.
        table: The string representing the database table.
        database_alias: A string which references the django database model in the settings file.

    Returns:
        A dict of unique features, and a dict of non unique features as a tuple.
    """
    if not features:
        return None
    db_features = get_all_db_features(table, database_alias=database_alias)
    unique_features = []
    non_unique_features = []
    for feature in features:
        checked_feature = check_db_for_feature(feature, db_features)
        if checked_feature == 'reject':
            continue
        if checked_feature:
            non_unique_features += [feature]
        else:
            unique_features += [feature]
    return unique_features, non_unique_features


def get_duplicate_features(features, properties_id=None):
    """This searches a feature list against itself for duplicate features.

    Args:
        features: A dict structured like a geojson of features.
        properties_id: The string representing the properties key of the feature UID.

    Returns:
        A dict of unique features, and a dict of non unique features as a tuple.
    """
    if not features or not properties_id:
        return None, None
    if len(features) == 1:
        return features, None

    sorted_features = sort_features(sort_features(features, 'version'), properties_id)

    unique_features = [sorted_features[0]]
    non_unique_features = []
    if not sorted_features[1]:
        return unique_features, non_unique_features
    for feature in sorted_features[1:]:
        if feature.get('properties').get(properties_id) == unique_features[-1].get('properties').get(properties_id):
            non_unique_features += [feature]
        else:
            unique_features += [feature]
    return unique_features, non_unique_features


def sort_features(features, properties_key=None):
    return sorted(features, key=lambda (feature): feature['properties'][properties_key])


def check_db_for_feature(feature, db_features=None):
    """

    Args:
        feature: A feature to be checked for.
        db_features: All of the db features (see get_all_db_features).

    Returns:
        The feature if it matches, otherwise None.
    """
    nearsight_id = feature.get('properties').get(get_nearsight_id_fieldname())
    if not db_features:
        return None
    if db_features.get(nearsight_id):
        # While it is unlikely that the database would have a newer version than the one being presented.
        # Older versions should be rejected.  If they fail to be handled at least they won't overwrite a
        # more current value.
        if db_features.get(nearsight_id).get('version') > feature.get('properties').get('version'):
            return "reject"
        feature['ogc_fid'] = db_features.get(nearsight_id).get('ogc_fid')
        return feature
    return None


def get_all_db_features(layer, database_alias=None):
    """

    Args:
        layer: A database table.
        database_alias: Django database object defined in the settings.

    Returns:
        A dict of features (not these are NOT formatted like a geojson).
    """
    if not is_alnum(layer):
        return None

    if database_alias:
        cur = connections[database_alias].cursor()
    else:
        cur = connection.cursor()

    query = "SELECT * FROM {};".format(layer)
    try:
        with transaction.atomic():
            cur.execute(query)
            features = {}
            nearsight_id_index = get_column_index(get_nearsight_id_fieldname(), cur)
            ogc_id_index = get_column_index('ogc_fid', cur)
            version_id_index = get_column_index('version', cur)
            for feature in cur:
                features[feature[nearsight_id_index]] = {get_nearsight_id_fieldname(): feature[nearsight_id_index],
                                                       'ogc_fid': feature[ogc_id_index],
                                                       'version': feature[version_id_index],
                                                       'feature_data': feature}
    except ProgrammingError:
        return None
    finally:
        cur.close()
    return features


def get_column_index(name, cursor):
    """Checks a raw sql query description for the name of a column.

    Args:
        name: The name being searched for.
        cursor: A database cursor.

    Returns:
        The index value for the column.
    """
    if not cursor.description:
        return
    for ind, val in enumerate([desc[0] for desc in cursor.description]):
        if val.lower() == name.lower():
            return ind


def update_db_features(features, layer, database_alias=None):
    """A wrapper to repeatedly call update_db_feature.

    Args:
        features: A feature whose id exists in the database, to be updated.
        layer: The name of the database table.
        database_alias: The django database structure defined in settings.

    Returns:
        None
    """
    if not features or not layer:
        logger.info("A feature or layer was not provided to update_db_features")
        return
    if type(features) != list:
        features = [features]
    for feature in features:
        update_db_feature(feature,
                          layer,
                          database_alias=database_alias)


def update_db_feature(feature, layer, database_alias=None):
    """

    Args:
        feature: A feature whose id exists in the database, to be updated.
        layer: The name of the database table.
        database_alias: The django database structure defined in settings.

    Returns:
        None
    """
    if not is_alnum(layer):
        return

    if not feature:
        return

    if not feature.get('ogc_fid'):
        check_feature = check_db_for_feature(feature, get_all_db_features(layer, database_alias=database_alias))
        if not check_feature:
            logger.warn("WARNING: An attempted to update a feature that doesn't exist in the database.")
            logger.warn(" A new entry will be created for the feature {}.".format(feature))
        elif check_feature == 'reject':
            logger.warn("WARNING: An attempt was made to update a feature with an older version. "
                  "The feature {} was rejected.".format(feature))
        else:
            feature = check_feature

    delete_db_feature(feature,
                      layer=layer,
                      database_alias=database_alias)

    ogr2ogr_geojson_to_db(geojson_file=features_to_file(feature),
                          database_alias=database_alias,
                          table=layer)


def delete_db_feature(feature, layer, database_alias=None):
    """

    Args:
        feature: A feature whose id exists in the database, to be removed.
        layer: The name of the database table.
        database_alias: The django database structure defined in settings.

    Returns:
        None
    """
    if not is_alnum(layer):
        return

    if not feature:
        return

    if not feature.get('ogc_fid'):
        check_feature = check_db_for_feature(feature, get_all_db_features(layer, database_alias=database_alias))
        if not check_feature:
            logger.warn("WARNING: An attempt was made to delete a feature "
                  "that doesn't exist in the database (or have an OGC_FID.")
        elif check_feature == 'reject':
            logger.warn("WARNING: An attempt was made to update a feature with an older version. "
                  "The feature {} was rejected.".format(feature))
    if database_alias:
        db_conn = connections[database_alias]
    else:
        db_conn = connection

    cur = db_conn.cursor()

    query = "DELETE FROM {} WHERE {} = '{}';".format(layer, get_nearsight_id_fieldname(), feature.get('properties').get(get_nearsight_id_fieldname()))

    try:
        with transaction.atomic():
            cur.execute(query)
    except ProgrammingError:
        logger.error("Unable to delete the feature:")
        logger.error(str(feature))
        logger.error("It is most likely not in the database or missing a nearsight_id.")
    finally:
        cur.close()
        db_conn.close()


def is_alnum(data):
    """
    Used to ensure that only 'safe' data can be used to query data.
    This should never be a problem since NearSight implements the same restrictions.

    Args:
        data: String of data to be tested.

    Returns:
        True: if data is only alphanumeric or '_' chars.
    """
    if re.match(r'\w+$', data):
        return True


def publish_layer(layer_name, geoserver_base_url=None, database_alias=None):
    """
    Args:
        layer_name: The name of the table that already exists in postgis,
         to be published as a layer in geoserver.
        geoserver_base_url: A string where geoserver is accessed(i.e. "http://localhost:8080/geoserver")
        database_alias: A string representing the Django database object to use.

    Returns:
        A tuple of (layer, created).
    """

    ogc_server = get_ogc_server()

    if not ogc_server:
        logger.info("An OGC_SERVER wasn't defined in the settings")
        return

    if get_ogc_server().get('LOCATION'):
        geoserver_base_url = get_ogc_server().get('LOCATION').rstrip('/')

    if not geoserver_base_url:
        # print('The function publish_layer was called without a '
        #       'geoserver_base_url parameter or an OGC_SERVER defined in the settings')
        return None, False
    url = "{}/rest".format(geoserver_base_url)
    workspace_name = "geonode"
    workspace_uri = "http://www.geonode.org/"
    if database_alias:
        conn = connections[database_alias]
    else:
        conn = connection
    host = conn.settings_dict.get('HOST')
    port = conn.settings_dict.get('PORT')
    password = conn.settings_dict.get('PASSWORD')
    db_type = "postgis"
    user = conn.settings_dict.get('USER')
    srs = "EPSG:4326"
    database = conn.settings_dict.get('NAME')
    datastore_name = database

    if not password:
        logger.warn("Geoserver can not be updated without a database password provided in the settings file.")

    cat = Catalog(url,
                  username=ogc_server.get('USER'),
                  password=ogc_server.get('PASSWORD'),
                  disable_ssl_certificate_validation=not getattr(settings, 'SSL_VERIFY', True))

    # Check if local workspace exists and if not create it
    try:
        workspace = cat.get_workspace(workspace_name)
    except ResponseNotReady as rnr:
        logger.error("Nearsight is unable to communicate with GeoServer, please check OGC_SERVER settings.")
        logger.error(rnr)
        raise(rnr)
    except FailedRequestError as fre:
        logger.error("Nearsight is unable to communicate with GeoServer, because GeoServer returned an error.")
        logger.error(fre)
        raise (fre)

    if workspace is None:
        cat.create_workspace(workspace_name, workspace_uri)
        logger.info("Workspace " + workspace_name + " created.")

    # Get list of datastores
    datastores = cat.get_stores()

    datastore = None
    # Check if remote datastore exists on local system
    for ds in datastores:
        if ds.name.lower() == datastore_name.lower():
            datastore = ds

    if not datastore:
        datastore = cat.create_datastore(datastore_name, workspace_name)
        datastore.connection_parameters.update(port=port,
                                               host=host,
                                               database=database,
                                               passwd=password,
                                               user=user,
                                               dbtype=db_type)
        cat.save(datastore)

    # Check if remote layer already exists on local system
    layer = cat.get_layer(layer_name)

    # layer = None
    # for lyr in layers:
    #     if lyr.resource.name.lower() == layer_name.lower():
    #         layer = lyr

    if not layer:
        # Publish remote layer
        try:
            layer = cat.publish_featuretype(layer_name.lower(), datastore, srs, srs=srs)
        except Exception as e:
            nearsight_status["status"] = "error publishing feature layer"
        return layer, True
    else:
        return layer, False


def dictfetchall(cursor):
    """

    Args:
        cursor: A python database cursor.

    Returns:
        A dict of the information in the cursor object.

    """
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
        ]


def truncate_tiles(layer_name=None, srs=4326, geoserver_base_url=None, **kwargs):
    """

    Args:
        layer_name: The GWC layer to remove tiles from.
        srs: The projection default is 4326.
        geoserver_base_url: A string where geoserver is accessed(i.e. "http://localhost:8080/geoserver")

    Returns:
        None
    """
    # See http://docs.geoserver.org/stable/en/user/geowebcache/rest/seed.html for more parameters.
    # See also https://github.com/GeoNode/geonode/issues/1656
    params = kwargs
    if layer_name:
        params.setdefault("name", "geonode:{0}".format(layer_name))
    params.setdefault("srs", {"number": srs})
    params.setdefault("zoomStart", 0)
    if srs == 4326:
        params.setdefault("zoomStop", 21)
    else:
        params.setdefault("zoomStop", 31)
    params.setdefault("format", "image/png")
    params.setdefault("type", "truncate")
    params.setdefault("threadCount", 4)

    payload = json.dumps({"seedRequest": params})

    ogc_server = get_ogc_server()

    if not ogc_server:
        logger.info("An OGC_SERVER wasn't defined in the settings")
        return

    geoserver_base_url = geoserver_base_url or ogc_server.get('LOCATION').rstrip('/')

    url = "{0}/gwc/rest/seed/geonode:{1}.json".format(geoserver_base_url, layer_name)

    requests.post(url,
                  auth=(ogc_server.get('USER'),
                        ogc_server.get('PASSWORD')),
                  headers={"content-type": "application/json"},
                  data=payload,
                  verify=getattr(settings, 'SSL_VERIFY', True))


def get_ogc_server(alias=None):
    """
    Args:
        alias: An alias for which OGC_SERVER to get from the settings file, default is 'default'.
    Returns:
        A dict containing inormation about the OGC_SERVER.
    """

    ogc_server = getattr(settings, 'OGC_SERVER', None)

    if ogc_server:
        if ogc_server.get(alias):
            return ogc_server.get(alias)
        else:
            return ogc_server.get('default')
    else:
        return {}


def initialize_sqlite_db(cursor):
    """

    Args:
        cursor: A database cursor object
    """
    results = cursor.execute("SELECT * from sqlite_master LIMIT 1")
    if not results.fetchone():
        cursor.execute("CREATE TABLE 'temp'('Field1' INTEGER);")


def get_field_map(features):
    """

    Args:
        features: An array of features

    Returns: A mapping of all of the available fields in the entire geojson.

    """
    field_map = {}
    for feature in features:
        if not feature.get('properties'):
            continue
        for prop, value in feature.get('properties').iteritems():
            if prop not in field_map or isinstance(field_map[prop], type(None)):
                field_map[prop] = type(value)
    logger.debug("field map: {0}".format(field_map))
    return field_map


def get_prototype(field_map):
    """

    Args:
        field_map: A mapping of all of the fields available and types as a dict.
        see get_field_map.

    Returns: A prototypical dict representing every possible field with default json values.
    """
    prototype = {}
    for key, value in field_map.iteritems():
        if isinstance(value, int):
            prototype[key] = 0
        elif isinstance(value, list):
            prototype[key] = '[]'
        elif isinstance(value, str):
            prototype[key] = ''
    logger.debug("prototype feature: {0}".format(prototype))
    return prototype


def delete_feature(feature_uid):
    """

    Args:
        feature_uid: An id (presumably the nearsight_id) of an object to remove from the nearsight database.

    """
    if getattr(settings, 'DATABASES', {}).get('nearsight'):
        database_alias = 'nearsight'
    else:
        database_alias = None

    is_database_used = False
    if is_db_supported(database_alias):
        is_database_used = True

    for feature in Feature.objects.filter(feature_uid=feature_uid):
        if is_database_used:
            delete_db_feature(json.loads(feature.feature_data), feature.layer.layer_name, database_alias=database_alias)
        feature.delete()
