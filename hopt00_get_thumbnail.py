from geoserver.catalog import Catalog
cat = Catalog("http://172.18.77.15:8089/geoserver/rest", username="admin", password="geoserver")
url='http://172.18.77.15:8089/geoserver/%s/wms?service=WMS&version=1.1.0&request=GetMap&layers=%s:%s&styles=&bbox=%s,%s,%s,%s&width=80&height=80&srs=%s&format=image/png'
rr=cat.get_resources(workspace=cat.get_workspace('shenzhen'))

for r in rr:
    print r.name,url%(r.workspace.name,r.workspace.name,r.name,r.native_bbox[0],r.native_bbox[2],\
                r.native_bbox[1],r.native_bbox[3],r.native_bbox[4] if r.native_bbox[4] is not None \
                and r.native_bbox[4].startswith('EPSG') else ('EPSG:4326' if float(r.native_bbox[0])<10000 else 'EPSG:2309' ) )

