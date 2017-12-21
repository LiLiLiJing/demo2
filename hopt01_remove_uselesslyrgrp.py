# written at 9:21, on 2017-12-20, helping function
# removing the redundant layer groups - with vacant layers
import os, sys

from geoserver.catalog import Catalog
geoserver_url = "http://172.18.77.15:8089/geoserver"
cat = Catalog(geoserver_url + "/rest", username="admin", password="geoserver")

# getting the names of all the existing workspaces
srvr_wslist = cat.get_workspaces()

for ws_obj in srvr_wslist:
    ws_name = ws_obj.name
    srvr_lyrgrplist = cat.get_layergroups(workspace=ws_obj)

    # check if all the related layers exists in the current layer group
    for grp_obj in srvr_lyrgrplist:
        for mbr_lyr_name in grp_obj.layers:
            if not cat.get_resource(mbr_lyr_name):
                cat.delete(grp_obj)
                print "Deleting group: ", grp_obj.name
                break

# then removing all the layer groups with the appointed suffixes


