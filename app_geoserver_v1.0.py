#!flask/bin/python

# Author: Ngo Duy Khanh
# Email: ngokhanhit@gmail.com
# Git repository: https://github.com/ngoduykhanh/flask-file-uploader
# This work based on jQuery-File-Upload which can be found at https://github.com/blueimp/jQuery-File-Upload/

import os
import os.path as osp

import PIL
from PIL import Image
import simplejson
import traceback

from flask import Flask, request, render_template, redirect, url_for, send_from_directory, Response, jsonify
from flask_bootstrap import Bootstrap
from werkzeug import secure_filename

from lib.upload_file import uploadfile

import requests
import urllib2
import json
import  xml.dom.minidom

from pyproj import Proj, transform
import numpy as np
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'hard to guess string'
app.config['UPLOAD_FOLDER'] = 'data/'
app.config['THUMBNAIL_FOLDER'] = 'data/thumbnail/'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 * 1024

ALLOWED_EXTENSIONS = set(['txt', 'gif', 'png', 'tif', 'tiff','jpg', 'jpeg', 'bmp', 'rar', 'zip', '7zip', 'doc', 'docx'])
THUMBNAIL_EXTENSION = 'png'
IGNORED_FILES = set(['.gitignore'])

bootstrap = Bootstrap(app)
GLOBAL_PORT_NUMBER = 31533

# 2017-11-3, the package added for data communication with the geoserver
from geoserver.catalog import Catalog
geoserver_url = "http://172.18.77.15:8089/geoserver"
cat = Catalog(geoserver_url + "/rest", username="admin", password="geoserver")


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def gen_file_name(filename):
    """
    If file was exist already, rename it and return a new name
    """

    i = 1
    while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
        name, extension = os.path.splitext(filename)
        filename = '%s_%s%s' % (name, str(i), extension)
        i += 1

    return filename


def create_thumbnail(image):
    try:
        base_width = 80
        img = Image.open(os.path.join(app.config['UPLOAD_FOLDER'], image))
        w_percent = (base_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        img = img.resize((base_width, h_size), PIL.Image.ANTIALIAS)
        thumbnail_image=image.replace(image.rsplit('.', 1)[1].lower(),THUMBNAIL_EXTENSION)
        img.save(os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_image))

        return True

    except:
        print traceback.format_exc()
        return False


# written at 15:40, on 2017-11-30, test the html5 visualization under flask
@app.route("/folder-view", methods=['GET', 'POST'])
def folder_view():
    print "Calling the folder_view service"
    return render_template('folder_view.html')


@app.route("/folder-imgsview", methods=['GET', 'POST'])
def folder_imgsview():
    print "Calling the folder_imgsview service"
    return render_template('folder_imgsview.html')


@app.route("/basic-test", methods=['GET', 'POST'])
def basic_test():
    print "Calling the basic_test service"
    return render_template('basic_test.html')


@app.route("/order-index", methods=['GET', 'POST'])
def order_index():
    print "Calling the order_index service"
    return render_template('orderindex.html')


# At 10:14, on 2017-12-1, operations for listing workspace, stores and layers, layer-groups
@app.route("/folder-traverse&<string:operation>", methods=['GET', 'POST'])
def folder_traverse(operation):
    operation_splits = operation.split('&')
    print '*** Splitted Operation Strings *** == ', operation_splits

    if operation_splits[0] == 'listdirs':
        # show all the workspaces, return in full links
        all_ws_list = cat.get_workspaces()

        num_ws = len(all_ws_list)
        ws_info_list = [{'name': '', 'url': '', 'num_objs': 0} for _ in range(num_ws)]

        # get the name, xml, and content count in the target workspace
        for ws_i, ws_obj in enumerate(all_ws_list):
            cur_ws_name = ws_obj.name
            cur_ws_url = ws_obj.href

            cur_ws_resrcs = cat.get_resources(workspace = ws_obj)
            cur_ws_objcount = len(cur_ws_resrcs)

            ws_info_list[ws_i]['name'] = cur_ws_name
            ws_info_list[ws_i]['url'] = cur_ws_url
            ws_info_list[ws_i]['num_objs'] = cur_ws_objcount

        return Response(json.dumps(ws_info_list), mimetype='application/json')

    elif operation_splits[0] == 'showdir':
        show_wsdir_name = operation_splits[1]

        show_wsdir_xml = cat.get_workspace(name = show_wsdir_name)
        cur_ws_resrcs = cat.get_resources(workspace = show_wsdir_xml)

        # iterate through the list of resources and get their properties
        cur_ws_resrccount = len(cur_ws_resrcs)
        ws_resrcs_list = [{'name': '', 'type': '', 'thumbnail': None} \
            for _ in range(cur_ws_resrccount)]

        for rs_i, rs_obj in enumerate(cur_ws_resrcs):
            ws_resrcs_list[rs_i]['name'] = rs_obj.name
            ws_resrcs_list[rs_i]['type'] = rs_obj.resource_type
            ws_resrcs_list[rs_i]['thumbnail'] = None

        return Response(json.dumps(ws_resrcs_list), mimetype='application/json')

    elif operation_splits[0] == 'createdir':
        # create a new workspace
        wsdir_name = operation_splits[1]
        wsdir_uri = "/".join([geoserver_url, wsdir_name])
        wsdir_obj = cat.create_workspace(name = wsdir_name, uri = wsdir_uri)

        return Response(json.dumps({'name': wsdir_obj.name, 'url': wsdir_obj.href}), \
            mimetype='application/json')

    elif operation_splits[0] == 'deletedir':
        wsdir_name = operation_splits[1]
        wsdir_obj = cat.get_workspace(name = wsdir_name)
        del_status = cat.delete(wsdir_obj)

        return Response(json.dumps(del_status), mimetype='application/json')

    elif operation_splits[0] == 'manipdir':
        # make maniputations to the folder content
        pass

@app.route('/thumbnail&<string:workspacename>',methods=['POST','GET'])
def make_thumbnail(workspacename):
    url='http://172.18.77.15:8089/geoserver/%s/wms?service=WMS&version=1.1.0&request=GetMap&layers=%s:%s&styles=&bbox=%s,%s,%s,%s&width=80&height=80&srs=%s&format=image/png' 
    resources=cat.get_resources(workspace=cat.get_workspace(workspacename))

    res_list=[]
    for r in resources:
        res_url=url%(r.workspace.name,r.workspace.name,r.name,r.native_bbox[0],r.native_bbox[2],\
                 r.native_bbox[1],r.native_bbox[3],r.native_bbox[4] if r.native_bbox[4] is not None \
                 and r.native_bbox[4].startswith('EPSG') else ('EPSG:4326' if float(r.native_bbox[0])<10000 else 'EPSG:2309' ) )
        res_list.append({"name":r.name,"url":res_url})

    return jsonify(res_list)

# categorized at 10:12, on 2017-12-1, file uploading / deletion operations
@app.route("/upload", methods=['GET', 'POST'])
def upload():
    print "Entering upload(), with ", request.method
    
    if request.method == 'POST':
        files = request.files['file']

        if files:
            filename = secure_filename(files.filename)
            # filename = gen_file_name(filename)
            mime_type = files.content_type

            if not allowed_file(files.filename):
                result = uploadfile(name=filename, type=mime_type, size=0, not_allowed_msg="File type not allowed")

            else:
                # save file to disk
                uploaded_file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                files.save(uploaded_file_path)

                # create thumbnail after saving
                if mime_type.startswith('image'):
                    create_thumbnail(filename)
                
                # get file size after saving
                size = os.path.getsize(uploaded_file_path)

                # return json for js call back
                result = uploadfile(name=filename, type=mime_type, size=size)

                # 2017-11-3, now the file is saved at location - result.url
                store_name = osp.splitext(osp.basename(result.url))[0]
                cat.create_coveragestore(name=store_name, data=result.url, workspace=cat.get_default_workspace())
            
            return simplejson.dumps({"files": [result.get_file()]})

    if request.method == 'GET':
        # get all file in ./data directory
        #files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'],f)) and f not in IGNORED_FILES ]
        all_stores=cat.get_stores()

        # Appended at 09:39, on 2017-11-14, filtering the gotten stores with permitted types
        permit_types = ['WorldImage', 'GeoTIFF']
        stores = [s_obj for s_obj in all_stores if s_obj.type in permit_types]

        
        file_display = []

        for st in stores:
            dd={"name": st.name,
                "size": 0,
                "url": "show/%s"%st.name,
                "thumbnailUrl": 'thumbnail/%s.png'%st.name,
                "deleteUrl": 'delete/%s'%st.name,
                "deleteType": 'DELETE',
                "workspace": st.workspace.name}

            file_display.append(dd)

        return simplejson.dumps({"files": file_display})


@app.route("/delete/<string:filename>", methods=['DELETE'])
def delete(filename):
    try:
        execute_url="curl -v -u admin:geoserver -X DELETE %s/workspaces/%s/coveragestores/%s?recurse=true" \
            % (geoserver_url + "/rest", cat.get_default_workspace().name, filename)
        ret_code = os.system(execute_url)

        return simplejson.dumps({filename: 'True'})
    except:
        return simplejson.dumps({filename: 'False'})


# serve static files
@app.route("/thumbnail/<string:filename>", methods=['GET'])
def get_thumbnail(filename):
    return send_from_directory(app.config['THUMBNAIL_FOLDER'], filename=filename)


@app.route("/data/<string:filename>", methods=['GET'])
def get_file(filename):
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER']), filename=filename)


@app.route('/show/<string:storename>', methods=['GET', 'POST'])
def show(storename, ):
    # resource = cat.get_resource(storename, workspace=cat.get_default_workspace())
    resource = cat.get_resource(storename)
    src_proj = resource.projection

    store_dict = {}
    store_dict['bbox'] = resource.latlon_bbox
    store_dict['workspacename'] = resource.workspace.name
    store_dict['storename'] = storename
    store_dict['projection'] = src_proj

    return render_template('show.html',store_dict=store_dict)


@app.route('/showgroup/<string:groupname>', methods=['GET', 'POST'])
def showgroup(groupname):
    workspace_name=groupname.split(':')[0]
    groupname=groupname.split(':')[1]
    resource = cat.get_layergroup(name=groupname, workspace=cat.get_workspace(workspace_name))
    src_proj = cat.get_layer(resource.layers[0]).resource.projection

    store_dict = {}
    store_dict['bbox'] = resource.bounds
    store_dict['workspacename'] = workspace_name
    store_dict['storename'] = groupname
    store_dict['projection'] = src_proj

    return render_template('show.html',store_dict=store_dict)


@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    return render_template('index.html')


@app.route('/uploadpage&<string:ws_name>', methods=['GET', 'POST'])
def uploadpage(ws_name=""):
    print '((((((((((((((((((((uploadpage))))))))))))))))))))))'

    store_dict={'workspace': ws_name}
    return render_template('upload.html', store_dict=store_dict)


# @app.route('/uploadpage', methods=['GET', 'POST'])
# def uploadpage():
#     print '((((((((((((((((((((uploadpage))))))))))))))))))))))'
#     return render_template('upload.html')

# 2017-11-7, 09:55, collection of services on processing region collection
@app.route('/procrequest/<string:storename>', methods=['POST'])
def get_procrequest(storename):
    # get the processing type and the processing target category
    request_dict = dict(request.form)

    geoType = request_dict['type'][0]
    geoData = request_dict['geo'][0]
    attData = request_dict['att'][0]

    print '================================================'
    print 'GeoType: ', geoType
    print 'GeoData: ', geoData
    print 'AttData: ', attData
    

    # now build the WCS request url for retrieving the image in original resolution
    geoData_arr = geoData.split(',')
    lons_arr = np.array([float(item) for item in geoData_arr[0::2]], dtype=np.float64)
    lats_arr = np.array([float(item) for item in geoData_arr[1::2]], dtype=np.float64)

    min_lon = lons_arr.min(); max_lon = lons_arr.max()
    min_lat = lats_arr.min(); max_lat = lats_arr.max()

    # build the WCS request string
    prsrc = cat.get_resource(storename)
    prsrc_proj = prsrc.projection
    prsrc_ws = prsrc.workspace

    wms_request_projs = ['EPSG:404000']
    if prsrc_proj in wms_request_projs:
        
        res=requests.get("%s/wcs?service=WCS&version=2.0.0&" % geoserver_url\
                         + "request=DescribeCoverage&CoverageId=%s" % storename)

        dom = xml.dom.minidom.parseString(res.text)
        root = dom.documentElement
        vectors=root.getElementsByTagName('gml:offsetVector')

        xy_offsets_mat = np.zeros([2, 2], dtype=np.float64)
        xy_offsets_vec = np.zeros([2, ], dtype=np.float64)

        for v_i, vv in enumerate(vectors):
            cur_offset_str = vv.firstChild.data
            cur_offset_arr = np.array(cur_offset_str.split(" "), dtype=np.float64)
            xy_offsets_mat[v_i, :] = cur_offset_arr

        xy_offsets_vec[:] = np.array([xy_offsets_mat[0, 1], xy_offsets_mat[1, 0]], dtype=np.float64)
        x_len = (max_lat - min_lat) / xy_offsets_vec[0]
        y_len = (max_lon - min_lon) / xy_offsets_vec[1]
        x_len = int(x_len) if x_len>0 else int(x_len*-1)
        y_len = int(y_len) if y_len>0 else int(y_len*-1)
        rsrc = cat.get_resource(storename)
        ws_name = rsrc.workspace.name

        imgretrv_url = '%s/%s/wms?service=WMS&version=1.1.0&request=GetMap&layers=%s:%s&' % (geoserver_url,ws_name,ws_name,storename)\
                        + 'styles=&bbox=%s,%s,%s,%s&' % (str(min_lon),str(min_lat),str(max_lon),str(max_lat))\
                        + 'width=%s&height=%s&srs=EPSG:2309&format=image/geotiff' % (str(y_len),str(x_len))
    else:
        imgretrv_url = "%s/ows?service=WCS&version=2.0.0&" % (geoserver_url) \
            + "request=GetCoverage&coverageId=%s&format=image/geotiff&" % (storename) \
            + "subset=Lat(%s,%s)&subset=Long(%s,%s)" % (str(min_lat), str(max_lat), str(min_lon), str(max_lon))

    # then build the name of the resulting store
    cur_time = datetime.datetime.now().strftime("%Y%m%d_%H_%M_%S_%f")
    savstore_nm = storename + "_" + cur_time + "_" + attData.split(',')[-1]

    print "Retrieve URL: " + imgretrv_url
    print "Save Store Name: " + savstore_nm

    # send the request to the algorithmic processing service
    post_dict = {'server_url': geoserver_url + "/rest", 'img_url': imgretrv_url, \
        'save_storenm': savstore_nm}
    headers = {'Content-Type': 'application/json'}

    attData_arr = attData.split(',')

    if attData_arr[1] == 'Mask':
        request_url = urllib2.Request(url='http://172.18.77.15:31534/bridgemask', \
            headers=headers, data=json.dumps(post_dict))
        resp = urllib2.urlopen(request_url)

        # now stack the original and the returned layers, make the layer group
        group_name = savstore_nm + '_GRP'
        group_layers = [storename, savstore_nm]
        group_styles = [cat.get_layer(cur_layername).default_style.name \
            for cur_layername in group_layers]

        result_group = cat.create_layergroup(name=group_name, layers=group_layers, 
            styles=group_styles, bounds=cat.get_layer(storename).resource.native_bbox, \
            workspace=cat.get_default_workspace().name)

        cat.save(result_group)

        return 'showgroup/' + group_name

    elif attData_arr[1] == 'Detection':
        request_url = urllib2.Request(url='http://172.18.77.15:31535/planedetect', 
            headers=headers, data=json.dumps(post_dict))
        resp = urllib2.urlopen(request_url)
        
        # now stack the original and the returned layers, make the layer group
        group_name = savstore_nm + '_ROI'
        group_layers = [storename, savstore_nm]
        group_styles = [cat.get_layer(cur_layername).default_style.name \
            for cur_layername in group_layers]

        result_group = cat.create_layergroup(name=group_name, layers=group_layers, \
            styles=group_styles, bounds=cat.get_layer(storename).resource.native_bbox, \
            workspace=prsrc_ws.name)

        cat.save(result_group)
        
        return 'showgroup/%s:%s'%(prsrc_ws.name,group_name)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=31555)
