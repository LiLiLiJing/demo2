#!flask/bin/python

# Author: Ngo Duy Khanh
# Email: ngokhanhit@gmail.com
# Git repository: https://github.com/ngoduykhanh/flask-file-uploader
# This work based on jQuery-File-Upload which can be found at https://github.com/blueimp/jQuery-File-Upload/

import os, re
import os.path as osp

import PIL
from PIL import Image
import simplejson
import traceback

from flask import Flask, request, session, escape, render_template, redirect, url_for, send_from_directory, Response, jsonify
from flask_bootstrap import Bootstrap
from werkzeug import secure_filename

from lib.upload_file import uploadfile

import requests
import urllib2
import json
import  xml.dom.minidom

from pyproj import Proj, transform
import mysql.connector
import numpy as np
import struct
import datetime
import osgeo.gdal as gdal

app = Flask(__name__)
app.config['SECRET_KEY'] = 'hard to guess string'
app.config['UPLOAD_FOLDER'] = 'data/'
app.config['THUMBNAIL_FOLDER'] = 'data/thumbnail/'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 * 1024

ALLOWED_EXTENSIONS = set(['txt', 'gif', 'png', 'tif', 'tiff','jpg', 'jpeg', \
    'bmp', 'rar', 'zip', '7zip', 'doc', 'docx'])
THUMBNAIL_EXTENSION = 'png'
IGNORED_FILES = set(['.gitignore'])

bootstrap = Bootstrap(app)

# ================================
addr_lcl_sw = 'local'
# addr_lcl_sw = 'global'

if addr_lcl_sw == 'local':
    GLOBAL_GEOSERVER_ADDR='172.18.77.15:8089'
    GLOBAL_IP_ADDR='172.18.77.15'
    GLOBAL_PORT_NUMBER = 31555
else:
    GLOBAL_GEOSERVER_ADDR='159.226.21.10'
    GLOBAL_IP_ADDR='159.226.21.10'
    GLOBAL_PORT_NUMBER = 80
# ================================

# 2017-11-3, the package added for data communication with the geoserver
from geoserver.catalog import Catalog
geoserver_url = "http://172.18.77.15:8089/geoserver"
cat = Catalog(geoserver_url + "/rest", username="admin", password="geoserver")

# 2017-12-6, 17:28, the connection configurations for the mysql user-job management
mysql_config = {'user': 'root', 'password': 'weiguang123', 'database': 'RSISS'}


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def gen_file_name(filename):
    """
    If file already exists, rename it and return a new name
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


# At 9:52, on 2017-12-7, the web-API for receiving the labeld polygons
def parse_annot_geostrings(annot_geostrs):
    '''
    Convert the given annotation geometrical parameter string into list of doubles.
    Example string: '15561529.36248355,4238805.742944532;15561447.886879355,4238608.660064116;15561649.373846484,4238560.21511027'
    '''
    xypairs_splits = annot_geostrs.split(';')

    annot_dbllist = list()
    for pair_i, pair_str in enumerate(xypairs_splits):
        cur_xstr, cur_ystr = pair_str.split(',')
        annot_dbllist.append(np.double(cur_xstr))
        annot_dbllist.append(np.double(cur_ystr))

    return annot_dbllist


def make_annot_geostrings(annot_doublepairs):
    '''
    Convert the given list of doubles into the annotation style xy-coordinations pairs.
    Example string: '15561529.36248355,4238805.742944532;15561447.886879355,4238608.660064116;15561649.373846484,4238560.21511027'
    '''
    n_coords = len(annot_doublepairs)
    n_pairs = n_coords / 2

    annot_strlist = list()
    for pair_i in range(n_pairs):
        cur_xstr = annot_doublepairs[pair_i * 2].astype(str)
        cur_ystr = annot_doublepairs[pair_i * 2 + 1].astype(str)

        annot_strlist.append(','.join([cur_xstr, cur_ystr]))

    return ';'.join(annot_strlist)

def convrt_doubles_to_hexstr(in_doubles_list):
    num_doubles = len(in_doubles_list)
    ds_stream = struct.pack('%dd' % num_doubles, *in_doubles_list)

    return '0x' + ''.join([r'{:02x}'.format(ord(x)) for x in ds_stream])


def convrt_hexstr_to_doubles(in_hex_bytearr):
    num_bytes = len(in_hex_bytearr)
    doubles_arr = struct.unpack('%dd' % (len(in_hex_bytearr) / 8), in_hex_bytearr)
    doubles_arr = [np.double(item) for item in doubles_arr]

    return doubles_arr


@app.route("/user-manage&<string:opt_type>", methods=['GET', 'POST'])
def user_management_api(opt_type):
    print "Entering user management Web-API, ", request.method

    if request.method == 'POST':
        pass
    elif request.method == 'GET':
        if opt_type == 'get-usrnames':
            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            sql_cmd = "select user.uname, user.display_name from user;"
            db_cursor.execute(sql_cmd)

            usrnms_list = list()
            for row in db_cursor.fetchall():
                usrnms_list.append({'uname': row[0], 'disp_name': row[1]})
            
            cnx_obj.close()

            return jsonify(usrnms_list)


@app.route("/poly-labels&<string:opt_type>", methods=['GET', 'POST'])
def poly_labels_proc(opt_type):
    print "Entering poly_labels_proc labeling data processing function: ", request.method

    if request.method == 'POST':
        if opt_type == 'commit_annot':
            '''
            The committed form should contain the following fields
                user_name, directory (workspace_name), img_name (store_name)
                polygon_type (annotation_type), object_type (class of the object)
            '''
            label_data = request.form

            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            sql_cmd = "insert into annot (uid, directory, imgnm, objclass, geotype, vertex) "\
                + "values ((select max(_id) from user where user.uname = '%s'), " % (label_data['username']) \
                + "'%s', '%s', " % (label_data['workspace'], label_data['infoname']) \
                + "(select max(_id) from obj_types where type_name = '%s'), " % (label_data['infoType']) \
                + "(select max(_id) from geo_types where type_name = '%s'), " % (label_data['geoType']) \
                + "%s);" % (convrt_doubles_to_hexstr(parse_annot_geostrings(label_data['geoStr'])))
            db_cursor.execute(sql_cmd)
            cnx_obj.commit()

            sql_cmd = "select last_insert_id();"
            db_cursor.execute(sql_cmd)            

            row = db_cursor.fetchall()
            # print "ID: ", row[0][0]
            cnx_obj.close()
            return Response(json.dumps({'index': row[0][0]}), mimetype='application/json')

        if opt_type == 'remove_annot':
            '''
            Remove all the annotations on a specific annotation image.
            '''
            rm_annot_req = request.form

            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            db_cursor.execute("SET SQL_SAFE_UPDATES = 0;")
            cnx_obj.commit()

            sql_cmd = "delete from annot where annot.imgnm = '%s';" % (rm_annot_req['infoname'])
            db_cursor.execute(sql_cmd)

            cnx_obj.commit()
            cnx_obj.close()

            return Response(json.dumps({'code': 200}), mimetype='application/json')

        if opt_type == 'remove_one_annot':
            '''
            2017-12-14, remove a single annotation from the database
            '''
            rm_annot_req = request.form

            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            db_cursor.execute("SET SQL_SAFE_UPDATES = 0;")
            cnx_obj.commit()

            sql_cmd = "delete from annot where annot._id = '%s';" % (rm_annot_req['annot_id'])
            db_cursor.execute(sql_cmd)

            cnx_obj.commit()
            cnx_obj.close()

            return Response(json.dumps({'code': 200}), mimetype='application/json')

        # retrieve the labeling data from the corresponding store and build the json structure
        if opt_type == 'get_annots':
            '''
            The parameters for getting the user/store specific annotations.
                user_name, workspace, img_name, obj_class
            '''
            get_annot_req = request.form

            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            # print "Form: ", get_annot_req
            sql_cmd = "SELECT aa._id, obj_types.type_name, geo_types.type_name, aa.vertex, aa.detailtype " \
                + "FROM (SELECT * FROM annot " \
                + "WHERE annot.uid IN (SELECT user._id FROM user WHERE user.uname ='%s')" % (get_annot_req['username']) \
                + "AND annot.imgnm = '%s') AS aa " % (get_annot_req['infoname']) \
                + "INNER JOIN geo_types INNER JOIN obj_types " \
                + "ON aa.objclass = obj_types._id AND aa.geotype = geo_types._id"

            db_cursor.execute(sql_cmd)
            
            annot_list = list()
            for row in db_cursor.fetchall():
                # print row[3]
                cur_annot = {'annot_id': row[0], 'obj_class': row[1], 'geo_type': row[2], \
                    'vertexs': make_annot_geostrings(convrt_hexstr_to_doubles(row[3])), \
                    'detailtype': row[4]}
                annot_list.append(cur_annot)
            cnx_obj.close()

            return Response(json.dumps(annot_list), mimetype='application/json')

        if opt_type == 'add_desc':
            '''
            2018-1-2, 14:50, update the detailed descriptions about the current annotation.
            '''
            detaildesc_req = request.form

            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            # print "Form: ", detaildesc_req
            sql_cmd = "update RSISS.annot set detailtype='%s' where _id=%s" \
                % (detaildesc_req['detailtype'], detaildesc_req['id'])

            db_cursor.execute("SET SQL_SAFE_UPDATES = 0;")
            cnx_obj.commit()

            db_cursor.execute(sql_cmd)
            cnx_obj.commit()
            
            cnx_obj.close()

            return jsonify({'code': 200, 'id': detaildesc_req['id']})

    elif request.method == 'GET':
        if opt_type == 'get_objclass':
            '''
            Return all the available object class names from the database.
            '''
            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            sql_cmd = "select type_name from obj_types;"
            db_cursor.execute(sql_cmd)

            types_list = [row[0] for row in db_cursor.fetchall()]
            cnx_obj.close()
            return Response(json.dumps(types_list), mimetype='application/json')

        if opt_type == 'get_geotypes':
            '''
            Return all the available geometrical types names from the database.
            '''
            cnx_obj = mysql.connector.connect(**mysql_config)
            db_cursor = cnx_obj.cursor()

            sql_cmd = "select type_name from geo_types;"
            db_cursor.execute(sql_cmd)

            types_list = [row[0] for row in db_cursor.fetchall()]
            cnx_obj.close()
            return Response(json.dumps(types_list), mimetype='application/json')


# written at 15:40, on 2017-11-30, test the html5 visualization under flask
@app.route("/folder-view", methods=['GET', 'POST'])
def folder_view():
    print "Calling the folder_view service"
    store_dict = {'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR}
    return render_template('folder_view.html', store_dict=store_dict)


@app.route("/folder-imgsview&<string:ws_name>", methods=['GET', 'POST'])
def folder_imgsview(ws_name):
    print "Calling the folder_imgsview service"
    store_dict = {'workspace': ws_name, 'port_number': GLOBAL_PORT_NUMBER, \
        'remote_addr': GLOBAL_IP_ADDR}
    return render_template('folder_imgsview.html', store_dict=store_dict)


@app.route("/folder-result&<string:ws_name>", methods=['GET', 'POST'])
def folder_result(ws_name):
    print "Calling the folder_imgsview service"
    store_dict = {'workspace': ws_name, 'port_number': GLOBAL_PORT_NUMBER, \
        'remote_addr': GLOBAL_IP_ADDR}
    return render_template('folder_result.html', store_dict=store_dict)


@app.route("/basic-test", methods=['GET', 'POST'])
def basic_test():
    print "Calling the basic_test service"
    return render_template('basic_test.html')


@app.route("/creat-order", methods=['GET', 'POST'])
def creat_order():
    print "Calling the creat_order service"
    store_dict = {'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR}
    return render_template('creat_order.html', store_dict=store_dict)


@app.route("/order-index", methods=['GET', 'POST'])
def order_index():
    print "Calling the order_index service"
    store_dict = {'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR}
    return render_template('orderindex.html', store_dict=store_dict)


# At 17:30, on 2017-12-6, operations for the mysql user-job managements
@app.route("/userjob-mng&<string:mngopts>", methods=['GET', 'POST'])
def userjob_manage(mngopts):
    if mngopts == '':
        pass


@app.route("/annot-objs", methods=['POST'])
def annot_objs_onimg():
    print "Entering method annot_objs_onimg: ", request
    if request.method == 'POST':
        st_name = request.form['check']
        return redirect(url_for('show', storename=st_name))


# At 10:14, on 2017-12-1, operations for listing workspace, stores and layers, layer-groups
@app.route("/folder-traverse&<string:operation>", methods=['GET', 'POST'])
def folder_traverse(operation):
    operation_splits = operation.split(':')
    print '*** Splitted Operation Strings *** == ', operation_splits
    # import ipdb; ipdb.set_trace()

    if operation_splits[0] == 'listdirs':
        # show all the workspaces, return in full links
        # import ipdb; ipdb.set_trace()

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
        # import ipdb; ipdb.set_trace()
        
        wsdir_name = operation_splits[1]
        wsdir_uri = "/".join([geoserver_url, wsdir_name])
        wsdir_obj = cat.create_workspace(name = wsdir_name, uri = wsdir_uri)

        return Response(json.dumps({'name': wsdir_obj.name, 'url': wsdir_obj.href}), \
            mimetype='application/json')

    elif operation_splits[0] == 'deletedir':
        wsdir_name = operation_splits[1]
        wsdir_obj = cat.get_workspace(name = wsdir_name)
        del_status = cat.delete(wsdir_obj, recurse=True)

        return Response(json.dumps(del_status), mimetype='application/json')

    elif operation_splits[0] == 'manipdir':
        # make maniputations to the folder content
        pass


@app.route('/thumbnail-single&<string:store_name>')
def make_thumbnail_single(store_name):
    url='%s/%s/wms?service=WMS&version=1.1.0&' \
        + 'request=GetMap&layers=%s:%s&styles=&bbox=%s,%s,%s,%s&width=80&height=80' \
        + '&srs=%s&format=image/png'

    r = cat.get_resource(store_name)
    res_url=url%(geoserver_url, r.workspace.name,r.workspace.name,r.name,r.native_bbox[0],r.native_bbox[2], \
            r.native_bbox[1],r.native_bbox[3],r.native_bbox[4] if r.native_bbox[4] is not None \
            and r.native_bbox[4].startswith('EPSG') else ('EPSG:4326' if float(r.native_bbox[0])<10000 else 'EPSG:2309'))

    return res_url


@app.route('/thumbnail&<string:workspacename>',methods=['POST','GET'])
def make_thumbnail(workspacename):
    url='%s/%s/wms?service=WMS&version=1.1.0&' \
        + 'request=GetMap&layers=%s:%s&styles=&bbox=%s,%s,%s,%s&width=80&height=80' \
        + '&srs=%s&format=image/png'

    resources=cat.get_resources(workspace=cat.get_workspace(workspacename))

    res_list=[]
    for r in resources:
        # appended at 9:15, on 2017-12-20, check if the containing raster is an algorithm output
        ignore_suffixs = ['AsynMask', 'AsynPlane', 'AsynStorage', 'shp', 'vec', 'vec1']

        cur_rsuffix = r.name.split('_')[-1]
        if cur_rsuffix in ignore_suffixs:
            continue

        res_url=url%(geoserver_url,r.workspace.name,r.workspace.name,r.name,r.native_bbox[0],r.native_bbox[2],\
                 r.native_bbox[1],r.native_bbox[3],r.native_bbox[4] if r.native_bbox[4] is not None \
                 and r.native_bbox[4].startswith('EPSG') else ('EPSG:4326' if float(r.native_bbox[0])<10000 else 'EPSG:2309'))
        # import ipdb; ipdb.set_trace()
        res_list.append({"name":r.name,"url":res_url, "workspace": workspacename})

    return jsonify(res_list)

# added at 11:20, on 2017-12-13, build the .tfw file for the EPSG:404000 type image
# copied from /home/jcai/workspace/flask/app.py
def generate_tfw(infile,tfw_name):
    src = gdal.Open(infile)
    xform = src.GetGeoTransform()

    src = None
    edit1=xform[0]+xform[1]/2
    edit2=xform[3]+xform[5]/2

    #tfw = open(os.path.splitext(infile)[0] + '.tfw', 'wt')
    tfw = open(tfw_name + '.tfw', 'wt')
    tfw.write("%0.8f\n" % xform[1])
    tfw.write("%0.8f\n" % xform[2])
    tfw.write("%0.8f\n" % xform[4])
    tfw.write("%0.8f\n" % xform[5])
    tfw.write("%0.8f\n" % edit1)
    tfw.write("%0.8f\n" % edit2)
    tfw.close()


# categorized at 10:12, on 2017-12-1, file uploading / deletion operations
@app.route("/upload", methods=['GET', 'POST'])
def upload():
    print "<<<<<<< Entering upload(), with ", request.method
    # import ipdb; ipdb.set_trace()

    if request.method == 'POST' and (not 'operation' in request.form.keys()):
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

                # 2017-12-13, 12:31, check the projection parameter of the uploaded image
                upimg_gdalinfo = gdal.Open(result.url)
                epsg_strs = re.search("PRIMEM\[.+AUTHORITY\[(.+?)\]\]", upimg_gdalinfo.GetProjection())

                store_name = osp.splitext(osp.basename(result.url))[0]
                workspace_name = request.form['workspace']

                if epsg_strs is None: # no PRIMEM means EPSG:404000
                    geotfw_fname = osp.splitext(result.url)[0]
                    generate_tfw(result.url, geotfw_fname)

                    data_struct = {'tiff': result.url, 'tfw': geotfw_fname + '.tfw'}

                    ws_obj = cat.get_workspace(workspace_name)
                    cat.create_coveragestore(name=store_name, data=data_struct, workspace=ws_obj)

                else: # otherwise, means a normal geotiff image
                    print "Uploading image GeoInfo: ", epsg_strs[0]
                    # 2017-11-3, now the file is saved at location - result.url
                    ws_obj = cat.get_workspace(workspace_name)
                    cat.create_coveragestore(name=store_name, data=result.url, workspace=ws_obj)
            
            return simplejson.dumps({"files": [result.get_file()]})

    else:
        # get all file in ./data directory
        #files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'],f)) and f not in IGNORED_FILES ]
        all_stores=cat.get_stores(workspace=cat.get_workspace(name=request.form['workspace']))

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
        # ws_obj = cat.get_resource(filename)
        # execute_url="curl -v -u admin:geoserver -X DELETE %s/workspaces/%s/coveragestores/%s?recurse=true" \
        #     % (geoserver_url + "/rest", ws_obj.workspace.name, filename)
        # ret_code = os.system(execute_url)

        store_obj = cat.get_store(filename)
        cat.delete(store_obj, recurse=True)

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


@app.route('/show&<string:storename>', methods=['GET', 'POST'])
def show(storename):
    resource = cat.get_resource(storename)
    src_proj = resource.projection

    store_dict = {'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR, \
        'geoserver_addr': GLOBAL_GEOSERVER_ADDR}
    special_projs = ['EPSG:404000']

    if src_proj in special_projs:
        store_dict['bbox'] = resource.latlon_bbox[0:4]
        store_dict['workspacename'] = resource.workspace.name
        store_dict['storename'] = storename
        store_dict['projection'] = src_proj
    else:
        store_dict['bbox'] = resource.latlon_bbox
        store_dict['workspacename'] = resource.workspace.name
        store_dict['storename'] = storename
        store_dict['projection'] = src_proj

    return render_template('show.html',store_dict=store_dict)


@app.route('/asynmask-select&<string:storename>', methods=['GET', 'POST'])
def asynmask_select(storename):
    resource = cat.get_resource(storename)
    src_proj = resource.projection

    store_dict = {'port_number': GLOBAL_PORT_NUMBER}
    store_dict['bbox'] = resource.latlon_bbox
    store_dict['workspacename'] = resource.workspace.name
    store_dict['storename'] = storename
    store_dict['projection'] = src_proj

    return render_template('algo_regionsel.html',store_dict=store_dict)


@app.route('/listorders&<string:job_type>')
def listorders_bytype(job_type='bridgemask'):
    cnx_obj = mysql.connector.connect(**mysql_config)
    db_cursor = cnx_obj.cursor()

    if job_type == 'all':
        sql_cmd = "select description, result, process_status from job where job.params regexp '^JobType';"
    else:
        sql_cmd = "select description, result, process_status from job where " \
            + "job.params = 'JobType:%s';" % (job_type)

    db_cursor.execute(sql_cmd)
    

    avail_orderlist = list()
    for row in db_cursor.fetchall():
        row_reqjson = json.loads(row[0])

        # parse the description, get the store_name, and get the workspace_name
        req_parmsplits = row_reqjson['img_url'].split('?')[1].split('&')
        req_keys = [sect.split('=')[0] for sect in req_parmsplits]
        req_vals = [sect.split('=')[1] for sect in req_parmsplits]

        if 'coverageId' in req_keys:
            store_name = req_vals[req_keys.index('coverageId')]
            workspace_name = cat.get_resource(store_name).workspace.name
        elif 'layers' in req_keys: # if the coverageId does not exists, then it must be layers
            layer_str = req_vals[req_keys.index('layers')]
            workspace_name, store_name = layer_str.split(':')

        cur_orderstatus = {'order_param': row_reqjson, 'order_result': row[1], \
            'status': row[2], 'storename': store_name, 'workspace': workspace_name}

        avail_orderlist.append(cur_orderstatus)

    cnx_obj.close()
    # return Response(json.dumps(avail_orderlist), mimetype='application/json')
    return jsonify(avail_orderlist)


def hproc_getjobresult_bysavstorenm(job_storenm):
    '''
    2017-12-21, 9:30, getting the result of the job by the saved storename.
    '''
    ws_list = cat.get_workspaces()
    for ws_obj in ws_list:
        curws_lyrgrps = cat.get_layergroups(workspace=ws_obj)
        for grp_obj in curws_lyrgrps:
            curgrp_lyrnms = grp_obj.layers
            if job_storenm in curgrp_lyrnms:
                return grp_obj.name, grp_obj

    return None, None


def hproc_deleteorder_geosrvr(job_storenm):
    '''
    2017-12-21, 10:00, delete the saved algorithm processing result store from geoserver.
    '''
    # step 1: delete the correlating layer-group
    lyrgrp_name, lyrgrp_obj = hproc_getjobresult_bysavstorenm(job_storenm)

    if lyrgrp_name:
        cat.delete(lyrgrp_obj)

    # step 2: delete the layer object itself, if featureType, delete layer at first
    lyr_obj = cat.get_layer(job_storenm)
    if lyr_obj:
        cat.delete(lyr_obj)

    # step 3: delete the correlated store object
    str_obj = cat.get_store(job_storenm)
    if str_obj:
        cat.delete(str_obj, recurse=True)


@app.route('/deleteorder&<job_storenm>', methods=['POST', 'GET'])
def deleteorder_bystrenm(job_storenm):
    '''
    Appended at 9:59, on 2017-12-20
    Removing the appointed order by the result-saving storename.
    '''
    # check if the layer group exists, then removing it from the geoserver
    # step 1: remove the store from the geoserver
    hproc_deleteorder_geosrvr(job_storenm)

    # then removing it from the mysql database
    cnx_obj = mysql.connector.connect(**mysql_config)
    db_cursor = cnx_obj.cursor()

    db_cursor.execute("SET SQL_SAFE_UPDATES = 0;")
    cnx_obj.commit()

    sql_cmd = "delete from job where job.path = '%s';" % (job_storenm)
    print "SQL Command: ", sql_cmd

    try:
        db_cursor.execute(sql_cmd)
        cnx_obj.commit()
    except Exception, err:
        cnx_obj.close()
        return jsonify({'code': 405})
        
    cnx_obj.close()

    return jsonify({'code': 200})


@app.route('/create-lblorder-ui', methods=['POST'])
def create_label_orderui():
    # the frontend will post the selected list workspace names
    f = request.form

    sel_wslist = f.getlist(f.keys()[0])
    store_dict = {'ws_list': sel_wslist, 'port_number': GLOBAL_PORT_NUMBER}
    return render_template('creat_order.html', store_dict=store_dict)


@app.route('/show-lblordrs-ui', methods=['POST', 'GET'])
def show_label_orderui():
    # the frontend will post the selected list workspace names
    store_dict = {'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR}
    return render_template('show_lblorder.html', store_dict=store_dict)


@app.route('/lblorder-manip&<string:opt_type>', methods=['GET', 'POST'])
def labelorder_manip(opt_type):
    '''
    2017-12-20, 19:01, manipulations to the image labeling order table
    '''
    opt_type_split = opt_type.split(':')

    if opt_type_split[0] == "create-order":
        # parse the given form object, form the mysql updating command
        post_f = request.form

        # sect 1: getting the selected workspaces
        wsnms_list = post_f.getlist('workspace')
        wsnms_str = 'Workspace:' + ','.join(wsnms_list)

        # sect 2: getting the object types being selected
        objtypes_list = [item[:-1].encode('ascii') for item in post_f.getlist('object')]
        objtypes_str = 'ObjTypes:' + ','.join(objtypes_list)

        # sect 3: getting the user being selected
        usrs_list = [item[:-1].encode('ascii') for item in post_f.getlist('user')]
        usrs_str = 'Users:' + ','.join(usrs_list)

        # sect 4: gettting the labeling description
        desc_str = post_f.getlist('otherInfo')[0]

        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()
        sql_cmd = "insert into job (uid, path, params, description) " \
            + "values (1, '%s', 'AnnotJob;%s', '%s')" % (';'.join([wsnms_str, objtypes_str]), usrs_str, desc_str)
        db_cursor.execute(sql_cmd)
        cnx_obj.commit()
        cnx_obj.close()

        return jsonify({'code': 200})

    elif opt_type_split[0] == "get-orders":
        # get all the annotation orders
        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        sql_cmd = "select _id, path, params, start_time, description from job " \
            + "where job.params regexp '^AnnotJob';"
        db_cursor.execute(sql_cmd)

        annotjobs_list = list()
        for row in db_cursor.fetchall():
            cur_id, cur_pathstr, cur_params, cur_starttime, cur_desc = row
            cur_workspace, cur_objtypes = cur_pathstr.split(';')
            cur_users = cur_params.split(';')[1]
            cur_info = {'id': cur_id, 'workspace': cur_workspace, 'objtypes': cur_objtypes, \
                'users': cur_users, 'description': cur_desc, "start_time": cur_starttime}
            annotjobs_list.append(cur_info)

        cnx_obj.close()
        return jsonify(annotjobs_list)

    elif opt_type_split[0] == "get-specorder":
        # retreive the information from mysql, the detailed descriptions about the annotation job
        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        order_no = request.form['order_no']
        sql_cmd = "select _id, path, params, start_time, description from job where job._id = %s;" % order_no
        db_cursor.execute(sql_cmd)
        cnx_obj.close()

    elif opt_type_split[0] == "get-specusr-order":
        # get the order related to a specific user
        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        user_name = request.form['user_name']
        sql_cmd = "select _id, path, params, start_time, description from job " \
            + "where (job.params regexp '^AnnotJob') and (job.params like '\%%s\%')" % (user_name)
        db_cursor.execute(sql_cmd)

        usr_annotjobs_list = list()
        for row in db_cursor.fetchall():
            cur_id, cur_pathstr, cur_params, cur_starttime, cur_desc = row
            cur_workspace, cur_objtypes = cur_pathstr.split(';')

            cur_info = {'id': cur_id, 'workspace': cur_workspace, 'objtypes': cur_objtypes, \
                'users': 'Users:%s' % user_name, 'description': cur_desc, "start_time": cur_starttime}

            usr_annotjobs_list.append(cur_info)

        cnx_obj.close()
        return jsonify(usr_annotjobs_list)

    elif opt_type_split[0] == "proc-order":
        # import ipdb; ipdb.set_trace()
        # comment: 2018-1-9, lifeimo, command = "lblorder-manip&proc-order:<id>:<type>"
        order_id = opt_type_split[1]

        if len(opt_type_split) > 2:
            t_return = opt_type_split[2]
        else:
            t_return = 'none'

        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        sql_cmd = "select path, params, start_time, description from job" \
            + " where job._id = %s;" % order_id
        db_cursor.execute(sql_cmd)

        cur_pathstr, cur_params, cur_starttime, cur_desc = db_cursor.fetchall()[0]
        cur_workspace, cur_objtypes = cur_pathstr.split(';')
        cur_users = cur_params.split(';')[1]
        cnx_obj.close()

        # parse the workspace, and collect the coveragestores in it
        cur_wslist = cur_workspace.split(':')[1].split(',')

        cur_strlist = list()
        cur_strnms_list = list()
        for cur_wsname in cur_wslist:
            cur_ws_rsclist = cat.get_resources(workspace=cur_wsname)

            for cur_rsc in cur_ws_rsclist:
                cur_rsc_name = cur_rsc.name; cur_strnms_list.append(cur_rsc_name)
                cur_rsc_suffix = cur_rsc_name.split('_')[-1]

                if cur_rsc_suffix in ['AsynMask', 'AsynStorage', 'AsynPlane']:
                    continue
                if (not cur_rsc.resource_type == 'coverage'):
                    continue

                if cur_rsc.projection in ['EPSG:404000', ]:
                    cur_rsc_bbox = cur_rsc.latlon_bbox[0:4]
                else:
                    cur_rsc_bbox = cur_rsc.latlon_bbox

                cur_rsc_info = {'projection': cur_rsc.projection, 'workspacename': cur_wsname, \
                    'storename': cur_rsc_name, 'bbox': cur_rsc_bbox}
                cur_strlist.append(cur_rsc_info)

        cur_info = {'storeinfos': cur_strlist, 'objtypes': cur_objtypes, \
                'users': cur_users, 'description': cur_desc, "start_time": cur_starttime, \
                'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR, \
                'geoserver_addr': GLOBAL_GEOSERVER_ADDR, 'id': order_id}

        #import ipdb; ipdb.set_trace()
        if t_return == 'none':
            return render_template('annotordr_show.html', store_dict=cur_info)
        elif t_return == 'json':
            return jsonify(cur_info)
        elif isinstance(t_return, unicode):
            cur_info['sel_imgname'] = t_return.encode('utf-8')
            cur_info['sel_imgidx'] = cur_strnms_list.index(cur_info['sel_imgname'])
            # import ipdb; ipdb.set_trace()
            return render_template('annotordr_show_imgsel.html', store_dict=cur_info)

    elif opt_type == "update-order":
        pass


@app.route('/showgroup/<string:grp_name>', methods=['GET', 'POST'])
def showgroup(grp_name):
    workspace_name, groupname=grp_name.split(':')
    print ">>>> Showgroup, ws ", workspace_name, ", gpname ", groupname

    resource = cat.get_layergroup(name=groupname, workspace=cat.get_workspace(workspace_name))
    src_proj = cat.get_layer(resource.layers[0]).resource.projection

    store_dict = {}
    store_dict['bbox'] = resource.bounds
    store_dict['workspacename'] = workspace_name
    store_dict['storename'] = groupname
    store_dict['projection'] = src_proj

    store_dict['port_number'] = GLOBAL_PORT_NUMBER
    store_dict['remote_addr'] = GLOBAL_IP_ADDR
    store_dict['geoserver_addr'] = GLOBAL_GEOSERVER_ADDR

    return render_template('algo_regionsel.html',store_dict=store_dict)


@app.route('/showgroup-transp/<string:grp_name>', methods=['GET', 'POST'])
def showgroup_transp(grp_name):
    workspace_name, groupname=grp_name.split(':')
    print ">>>> Showgroup-transp, ws ", workspace_name, ", gpname ", groupname

    resource = cat.get_layergroup(name=groupname, workspace=cat.get_workspace(workspace_name))
    resrc0_proj = cat.get_layer(resource.layers[0]).resource.projection

    store_dict = {}
    store_dict['bbox'] = resource.bounds
    store_dict['workspacename'] = workspace_name

    store_dict['storename1'] = resource.layers[0]
    store_dict['storename2'] = resource.layers[1]

    store_dict['projection'] = resrc0_proj

    store_dict['port_number'] = GLOBAL_PORT_NUMBER
    store_dict['remote_addr'] = GLOBAL_IP_ADDR
    store_dict['geoserver_addr'] = GLOBAL_GEOSERVER_ADDR

    return render_template('algo_regionsel_transtack.html',store_dict=store_dict)


@app.route('/logstate', methods=['GET', 'POST'])
def logstate():
    if 'username' in session:
        return jsonify({'code': 200, 'value': escape(session['username'])})
    else:
        return jsonify({'code': 405})


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('username', None)
    # return redirect('/')
    return jsonify({'code': 200})


@app.route('/', methods=['GET', 'POST'])
def index():
    print ">>>> Index Request, ", request.method

    if request.method == 'POST':
        # import ipdb; ipdb.set_trace()
        session['username'] = request.form['form-username']
        password = request.form['form-password']
        login_type = request.form['login-type']

        # get all the annotation orders
        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        sql_cmd = "select uname, display_name, pwd, utype from user " \
            + "where (uname = '%s') or (display_name = '%s');" % (session['username'], session['username'])
        db_cursor.execute(sql_cmd)

        # just get the first row of records from the selectoin result
        req_rows = db_cursor.fetchall(); n_recs = len(req_rows)
        if n_recs <=0:
            return jsonify({'code': '404'})
        else:
            # check the type of the user
            first_rec_row = req_rows[0]; user_type = first_rec_row[3]
            cur_user_types = [item.strip() for item in user_type.split(',')]

            # import ipdb; ipdb.set_trace()
            if ('user' in cur_user_types) and (login_type == 'user'):
                return redirect(url_for('login_user', user_name = session['username']))
            elif ('admin' in cur_user_types) and (login_type == 'admin'):
                return redirect(url_for('login_admin'))
        cnx_obj.close()

    if request.method == 'GET':
        return render_template('login.html')


@app.route('/login-admin', methods=['GET', 'POST'])
def login_admin():
    store_dict={'port_number': GLOBAL_PORT_NUMBER, 'remote_addr': GLOBAL_IP_ADDR}
    return render_template('index.html', store_dict=store_dict)

@app.route('/login-user&<string:user_name>', methods=['GET', 'POST'])
def login_user(user_name):
    store_dict={'port_number': GLOBAL_PORT_NUMBER, 'user_name': user_name, \
        'remote_addr': GLOBAL_IP_ADDR}
    return render_template('index_user.html', store_dict=store_dict)

@app.route('/uploadpage&<string:ws_name>', methods=['GET', 'POST'])
def uploadpage(ws_name=""):
    print '((((((((((((((((((((uploadpage))))))))))))))))))))))'

    store_dict={'workspace': ws_name, 'port_number': GLOBAL_PORT_NUMBER}
    return render_template('upload.html', store_dict=store_dict)


# 2017-12-20, 13:49, the web-API for saving and retrieving temporary variables
@app.route('/tempvars&<string:opt_type>', methods=['POST'])
def tempvars_opt(opt_type):
    print "Calling tempvars API with method: ", request.method
    if opt_type == 'save':
        var_values = request.form['values']
        var_name = request.form['name']

        session['var_' + var_name] = var_values
        return jsonify(var_values)

    elif opt_type == 'retrieve':
        var_name = request.form['name']
        if 'var_' + var_name in session:
            return jsonify(session['var_' + var_name])
        else:
            return 405


# 2018-1-12, 9:45, user annotation processing status recording
# =============================================================
@app.route('/user-annot-status&<string:opt_type>', methods=['GET', 'POST'])
def user_annot_status(opt_type):
    print "Calling the user annotation status processing function."
    user_name = request.form['user_name'].encode('utf-8')
    order_idx = request.form['order_idx'].encode('utf-8')

    # import ipdb; ipdb.set_trace()

    cnx_obj = mysql.connector.connect(**mysql_config)
    db_cursor = cnx_obj.cursor()

    db_cursor.execute("select _id, uname, display_name from user where uname = '%s';" % (user_name))
    fetch_recs = db_cursor.fetchall()
    if len(fetch_recs) <= 0:
        return jsonify({'code': 404, 'error': 'no user found'})
    else:
        first_uid = fetch_recs[0][0]
    cnx_obj.close()

    if opt_type == 'append-img-status':
        # initialize the annotation status for the specific image in the order
        annot_imgnm = request.form['img_name'].encode('utf-8')

        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        sql_cmd = "select _id, annot_status from user_annot_status " \
            + "where annot_userid=%s and annot_imgnm='%s';" % (first_uid, annot_imgnm)
        db_cursor.execute(sql_cmd)
        db_recs = db_cursor.fetchall()
        if len(db_recs) > 0:
            return jsonify({'code': 405, 'comment': 'record already exists.'})

        sql_cmd = "insert into user_annot_status (annot_ordridx, annot_userid, annot_imgnm, annot_status) " \
            + "values (%s, %s, '%s', 'ongoing');" % (order_idx, first_uid, annot_imgnm)
        db_cursor.execute("SET SQL_SAFE_UPDATES = 0;"); cnx_obj.commit()
        db_cursor.execute(sql_cmd); cnx_obj.commit()

        cnx_obj.close()

        return jsonify({'code': 200, 'comment': 'new image labeling record initialized'})

    elif opt_type == 'check-order-status':
        # first, check the existence of the user-order pairwised records
        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        # insert into the annotation commands in the user_annot_status datatable
        db_cursor.execute("select annot_imgnm, annot_status, last_annot_time, annot_comment " \
            + "from user_annot_status where annot_ordridx = %s and annot_userid = %s;" % (order_idx, first_uid))

        ordr_img_status = list()
        for user_annot_rec in db_cursor.fetchall():
            user_img_status = {'imgnm': user_annot_rec[0], 'status': user_annot_rec[1], \
                'last_modif_time': user_annot_rec[2], 'comment': user_annot_rec[3]}
            ordr_img_status.append(user_img_status)

        cnx_obj.close()

        # second, get and list the related images in the 'user-record' pairs
        if len(ordr_img_status) <= 0:
            return jsonify({'code': 404, 'comment': 'no records for current order'})
        else:
            return jsonify({'code': 200, 'status_list': ordr_img_status})

    elif opt_type == 'update-img-status':
        annot_imgnm = request.form['img_name'].encode('utf-8')
        annot_status = request.form['annot_status'].encode('utf-8') # ongoing, accomplished
        annot_comment = request.form['annot_comment'].encode('utf-8')

        cnx_obj = mysql.connector.connect(**mysql_config)
        db_cursor = cnx_obj.cursor()

        db_cursor.execute("SET SQL_SAFE_UPDATES = 0;")
        cnx_obj.commit()

        db_cursor.execute("update user_annot_status set annot_status='%s', " % (annot_status) \
            +"last_annot_time=now(), annot_comment='%s'" % (annot_comment) \
            + "where annot_userid=%s and annot_ordridx=%s;" % (first_uid, order_idx))
        cnx_obj.commit()
        cnx_obj.close()

        return jsonify({'code': 200, 'comment': 'new status updated for %s' % order_idx})


# 2017-12-11, 17:46, build / insert the new order records
# ==========================================================
def get_taskstorenm(store_name):
    cnx_obj = mysql.connector.connect(**mysql_config)
    db_cursor = cnx_obj.cursor()

    sql_cmd = "select process_status from job where job.path = '%s'" \
        % (store_name)

    db_cursor.execute(sql_cmd)

    task_status = db_cursor.fetchall()
    cnx_obj.close()
    
    return task_status[0][0] if len(task_status) > 0 else False


def add_taskrecord(task_name, task_info):
    print ">>>> add record >>>>"
    
    cnx_obj = mysql.connector.connect(**mysql_config)
    db_cursor = cnx_obj.cursor()

    if task_name == 'AsynMask':
        params_str = "JobType:bridgemask"
    elif task_name == 'AsynPlane':
        params_str = "JobType:planedet"
    elif task_name == 'AsynStorage':
        params_str = "JobType:storagedet"

    descr_str = json.dumps(task_info)

    sql_cmd = \
        "insert into job (uid, path, params, process_status, description) " \
        + "values ((select max(_id) from user " \
        + "where user.uname = 'lifeimo'), " \
        + "'%s', '%s', 0, " % (task_info['save_storenm'], params_str) \
        + "'%s');" % (descr_str)

    db_cursor.execute(sql_cmd)
    cnx_obj.commit()
    cnx_obj.close()

    print ">> New Record %s added." % (task_info['save_storenm'])

    return True


def asyn_tasks(task_name, req_form):
    # parse the requesting parameters
    taskrslt_strnm = req_form['save_storenm']

    if not get_taskstorenm(taskrslt_strnm):
        add_taskrecord(task_name, req_form)
        # thread = multiprocessing.Process(target=update_taskrecord, args=(taskrslt_strnm,))
        # thread.start()

    task_status = get_taskstorenm(taskrslt_strnm)
    if task_status == '0':
        ret_json = {'status': 'processing'}
    else:
        ret_json = {'status': 'finished'}

    return json.dumps(ret_json)


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

    wms_request_projs = ['EPSG:404000', ]
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

    elif attData_arr[1] in ['AsynMask', 'AsynPlane', 'AsynStorage']:
        # request_url = urllib2.Request(url='http://172.18.77.15:6033/asyn-bridgemask', \
        #     headers=headers, data=json.dumps(post_dict))
        # resp = urllib2.urlopen(request_url)
        addmsk_rslt = asyn_tasks(attData_arr[1], post_dict)

        return jsonify({'code': 200, 'order_rslt': addmsk_rslt})

if __name__ == '__main__':
    app.run(debug=True, host=GLOBAL_IP_ADDR, port=GLOBAL_PORT_NUMBER)
