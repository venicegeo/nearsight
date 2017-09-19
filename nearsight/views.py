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

from django.shortcuts import render
from .forms import UploadNearSightData
from .filters.run_filters import check_filters
from django.http import HttpResponse
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from wsgiref.util import FileWrapper

from .nearsight import nearsight_status
from .models import Layer


import json
import logging

logger = logging.getLogger(__file__)

def index(request):
    return viewer(request)


def geojson(request):
    from .mapping import get_geojson

    geojson_dict = {}
    if request.method == 'GET':
        if 'layer' not in request.GET:
            return HttpResponse("No layer exists, or a layer was not specified.", status=400)
        for layer in request.GET.getlist('layer'):
            if get_geojson(layer=layer):
                geojson_dict[layer] = json.loads(get_geojson(layer=layer))
    if not geojson_dict:
        return HttpResponse("No layer exists, or a layer was not specified.", status=400)
    return HttpResponse(json.dumps(geojson_dict), content_type="application/json")


def layer_source_download(request):
    if request.method == 'GET':
        if 'layer' not in request.GET:
            return HttpResponse("No layer was specified.", status=400)
        try:
            layer_name = request.GET.get('layer', '')
            layer = Layer.objects.get(layer_name=layer_name)
        except ObjectDoesNotExist:
            return HttpResponse("Layer: "+layer+" does not exist.", status=400)

        # check for old layers from previous migrations where the source was not recorded
        if layer.layer_source == "Unknown":
            return HttpResponse("Layer: "+layer+" returned an uknown source", status=400)

        # make sure the file exists on disk
        try:
            zip_file = open(layer.layer_source, 'rb')
        except:
            return HttpResponse("Layer: "+layer+" source could not be found on disk", status=400)

        zip_filename_toks = layer.layer_source.split('/')
        zip_filename = zip_filename_toks[len(zip_filename_toks)-1]
        response = HttpResponse(FileWrapper(zip_file), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="%s"' % zip_filename
        return response
    return HttpResponse("Invalid request method: "+request.method, status=400)


def upload(request):
    from .nearsight import process_nearsight_data
    from .mapping import get_geojson

    geojson_dict = {}
    if request.method == 'POST':
        form = UploadNearSightData(request.POST, request.FILES)
        logger.debug(request.FILES)
        if form.is_valid():
            check_filters()
            available_layers = process_nearsight_data(request.FILES['file'], request=request)
            for layer in available_layers:
                if get_geojson(layer=layer):
                    geojson_dict[layer] = json.loads(get_geojson(layer=layer))
            return HttpResponse(json.dumps(geojson_dict), content_type="application/json")
        else:
            logger.error("FORM NOT VALID.")
    else:
        form = UploadNearSightData()
    return render(request, 'nearsight/upload.html', {'form': form})


def viewer(request):
    from .mapping import get_geojson
    if request.method == 'GET':
        basemaps = []
        tuples = settings.LEAFLET_CONFIG['TILES']
        for layer_tuple in tuples:
            name, link, attr = layer_tuple
            basemaps.append([name, link, attr])
        if 'layer' not in request.GET:
            return render(request, 'nearsight/map.html', {'geojson_request_url': '', 'basemaps': basemaps})
        geojson_dict = {}
        available_layers = []
        for layer in request.GET.getlist('layer'):
            if get_geojson(layer=layer):
                available_layers += ['layer=' + layer]
        if geojson_dict:
            return render(request, 'nearsight/map.html',
                          {'geojson_request_url': '/nearsight/geojson?{}' + '&'.join(available_layers),
                           'basemaps': basemaps})
        else:
            return render(request, 'nearsight/map.html', {'geojson_request_url': '', 'basemaps': basemaps})


def layers(request):
    from .mapping import get_layer_names
    return HttpResponse(json.dumps(get_layer_names()), content_type="application/json")


def status_request(request):
    if request.method == 'GET':
        response = HttpResponse(json.dumps(nearsight_status), content_type="application/json")
        nearsight_status["status"] = ""
        return response
