#!/usr/bin/env python
#  -*- coding:utf-8 -*-
##############################################################################
# MODULE:    v.osm.preproc
# AUTHOR(S): Monia Molinari, Marco Minghini
# PURPOSE:   Tool for extracting road features in the OSM dataset which have a correspondence in the reference dataset
# COPYRIGHT: (C) 2015 by the GRASS Development Team
#
# This program is free software under the GNU General Public
# License (>=v2). Read the file COPYING that comes with GRASS
# for details.
# ############################################################################
#%Module
#%  description: Tool for extracting road features in the OSM dataset which have a correspondence in the reference dataset
#%  keywords: vector, OSM, preprocessing
#%End

#%option
#% key: osm
#% type: string
#% gisprompt: old,vector,vector
#% description: OpenStreetMap dataset
#% required: yes
#%end

#%option
#% key: ref
#% type: string
#% gisprompt: old,vector,input
#% description: Reference dataset
#% required: yes
#%end

#%option
#% key: buffer
#% type: double
#% description: Buffer around reference dataset (map units)
#% required: yes
#%end

#%option
#% key: angle_thres
#% type: double
#% description: Threshold value for angular coefficient comparison (degrees)
#% required: yes
#%end

#%option G_OPT_V_OUTPUT
#% key: output
#% description: Name for output map
#% required: yes
#%end

#%option
#% key: douglas_thres
#% type: double
#% description: Threshold value for Douglas-Peucker algorithm (map unit)
#% required: no
#%end

#%option G_OPT_F_OUTPUT
#% key: out_file
#% description: Name for output file with statistics (if omitted or "-" output to stdout)
#% required: no
#%end

#%option
#% key: nprocs
#% type: integer
#% description: Number of r.series processes to run in parallel
#% required: no
#% multiple: no
#% answer: 1
#%end

import math
import sys
import time
import grass.script as grass
from multiprocessing import Queue, Process


def length(data):
    feat_osm = int(((grass.read_command("v.info", map=data, flags="t",
                                        quiet=True)).split("\n")[2]).split("=")[1])
    if feat_osm > 0:
        length_data = grass.read_command("v.to.db", map=data, option="length",
                                         flags="p")
        s_data = 0
        l_data = length_data.split("\n")
        for item in l_data[1:-1]:
            s_data += float(item.split("|")[1])
    else:
        s_data = 0
    return s_data


def GetCoeff(vect):
    coord_start = grass.read_command("v.to.db", map=vect, option="start",
                                     type="line", flags="p").split("\n")[1]
    try:
        x_start = float(coord_start.split("|")[1])
        y_start = float(coord_start.split("|")[2])
        coord_end = grass.read_command("v.to.db", map=vect, option="end",
                                       type="line", flags="p").split("\n")[1]
        x_end = float(coord_end.split("|")[1])
        y_end = float(coord_end.split("|")[2])
        if (x_end - x_start) != 0:
            m = (y_end - y_start) / (x_end - x_start)
        else:
            m = 10**9
    except:
        m = 10**9
    return m


def AngulatComparison(f, processid, ref, osm, bf, list_lines, angle_thres):
    z = 0
    fdata = "fdata_" + processid
    fbuffer = "fbuffer_" + processid
    odata = "odata_" + processid
    patch = "patch_" + processid
    newfdata = "{da}_{su}".format(da=fdata, su=f)
    newbuffer = "{da}_{su}".format(da=fbuffer, su=f)
    newodata = "{da}_{su}".format(da=odata, su=f)
    grass.run_command("v.extract", input=ref, quiet=True,
                      output=newfdata, where="cat={st}".format(st=f))
    grass.run_command("g.copy",
                      vect="patch_{pr}_0_0,{su}_{fe}_0".format(pr=processid,
                                                               su=patch,
                                                               fe=f))
    if f in list_lines:
        grass.run_command("v.buffer", flags="c", distance=bf, quiet=True,
                          input=newfdata, output=newbuffer)
    else:
        grass.run_command("v.buffer", distance=bf, quiet=True,
                          input=newfdata, output=newbuffer)
    grass.run_command("v.overlay", ainput=osm, atype="line", quiet=True,
                      binput=newbuffer, output=newodata,
                      operator="and")
    lines = ((grass.read_command("v.info", flags="t", quiet=True,
                                 map=newodata)).split("\n")[2]).split("=")[1]
    if int(lines) == 0:
        grass.run_command("g.remove", type="vect", flags="f", quiet=True,
                          name=[newfdata, newbuffer, newodata])
    else:
        # Get REF angular coefficient
        list_subfeature = grass.read_command("v.db.select", map=newodata,
                                             columns="cat", flags="c",
                                             quiet=True).split("\n")[0:-1]
        m_ref = GetCoeff(newfdata)

        # Get OSM subfeatures angular coefficient
        for sf in list_subfeature:
            newnewodata = "{pre}_{suf}".format(pre=newodata, suf=sf)
            grass.run_command("v.extract", input=newodata,
                              output=newnewodata,
                              where="cat={st}".format(st=sf), quiet=True)
            m_osm = GetCoeff(newnewodata)


            new_angle = math.degrees(abs(math.atan((m_ref - m_osm) / (1 + m_ref * m_osm))))
            if new_angle <= angle_thres:
                newpatch = "{pr}_{il}_{su}".format(pr=patch, il=f, su=z)
                outpatch = "{pr}_{fe}_{st}".format(pr=patch, fe=f, st=sf)
                grass.run_command("v.patch", quiet=True,
                                  input="{fi},{se}".format(fi=newpatch,
                                                           se=newnewodata),
                                  output=outpatch)
                grass.run_command("g.remove", type="vect", flags="f",
                                  name="{fi},{se}".format(fi=newpatch,
                                                          se=newnewodata),
                                  quiet=True)
                z = sf
            else:
                grass.run_command("g.remove", type="vect",
                                  name=newnewodata, flags="f", quiet=True)
        grass.run_command("g.remove", type="vect", flags="f", quiet=True,
                          name=[newfdata, newbuffer, newodata])
    return 0


def spawn(func):
    def fun(q_in, q_out):
        while True:
            f, process, ref, osm, bf, list_lines, angle_thres = q_in.get()
            if f is None:
                break
            q_out.put(func(f, process, ref, osm, bf, list_lines, angle_thres))
    return fun


def main():
    osm = options["osm"]
    ref = options["ref"]
    bf = options["buffer"]
    angle_thres = options["angle_thres"]
    doug = options["douglas_thres"]
    out = options["output"]
    out_file = options["out_file"]
    nproc = int(options["nprocs"])

    # Check if input files exist
    if not grass.find_file(name=osm, element='vector')['file']:
        grass.fatal(_("Vector map <%s> not found") % osm)

    if not grass.find_file(name=ref, element='vector')['file']:
        grass.fatal(_("Vector map <%s> not found") % ref)

    # Prepare temporary map names
    processid = str(time.time()).replace(".", "_")
    ref_gen = "ref_gen_" + processid
    ref_split = "ref_split_" + processid
    osm_split = "osm_split_" + processid
    deg_points = "deg_points_" + processid
    degmin_points = "degmin_points_" + processid
    ref_degmin = "ref_degmin_" + processid

    outbuff = "outbuff_" + processid

    # Calculate length original data
    l_osm = length(osm)
    l_ref = length(ref)

    if l_ref == 0:
        grass.run_command("g.remove", flags="fr", type="vect", quiet=True,
                          pattern="{st}".format(st=processid))
        grass.fatal(_("No reference data for comparison"))

    if l_osm == 0:
        grass.run_command("g.remove", type="vect", flags="fr", quiet=True,
                          pattern="{st}".format(st=processid))
        grass.fatal(_("No OSM data for comparison"))


    # Generalize
    if doug:
        grass.run_command("v.generalize", input=ref, output=ref_gen,
                          method="douglas", threshold=doug, quiet=True)
        ref = ref_gen

    # Split REF dataset
    newrefsplit = "new_{spl}".format(spl=ref_split)
    grass.run_command("v.split", input=ref, output=ref_split, vertices=2,
                      quiet=True)
    grass.run_command('v.build.polylines', quiet=True, input=ref_split,
                      overwrite=grass.overwrite(), cats='same',
                      output=newrefsplit)

    grass.run_command("g.remove", type="vect", name=ref_split, flags="f",
                      quiet=True)
    grass.run_command("g.rename", vector="{inp},{out}".format(inp=newrefsplit,
                                                              out=ref_split))
    ref = ref_split

    # Split OSM datasets
    newosmsplit = "new_{spl}".format(spl=osm_split)
    grass.run_command("v.split", input=osm, output=osm_split, vertices=2,
                      quiet=True)
    grass.run_command('v.build.polylines', quiet=True, input=osm_split,
                      overwrite=grass.overwrite(), cats='same',
                      output=newosmsplit)
    grass.run_command("g.remove", type="vect", name=osm_split, flags="f",
                      quiet=True)
    grass.run_command("g.rename", vector="{inp},{out}".format(inp=newosmsplit,
                                                              out=osm_split))
    osm_orig = osm
    osm = osm_split
    # Calculate degree and extract REF category lines intersecting points with minimum value
    grass.run_command("v.net.centrality", input=ref, output=deg_points,
                      degree="degree", flags="a", quiet=True)
    list_values = (grass.read_command("v.db.select", map=deg_points,
                                      columns="degree", flags="c",
                                      quiet=True)).split("\n")[0:-1]
    degmin = min(map(float, list_values))

    grass.run_command("v.extract", input=deg_points, output=degmin_points,
                      where="degree={st}".format(st=degmin), quiet=True)
    grass.run_command("v.select", ainput=ref, binput=degmin_points,
                      output=ref_degmin, operator="overlap", quiet=True)
    list_lines = (grass.read_command("v.db.select", map=ref_degmin,
                                     columns="cat", flags="c",
                                     quiet=True)).split("\n")[0:-1]

    # Create new vector map
    grass.run_command("v.edit", map="patch_" + processid+"_0_0", tool="create",
                      quiet=True)

    list_feature = grass.read_command("v.db.select", map=ref, columns="cat",
                                      flags="c", quiet=True).split("\n")[0:-1]

    olddb = grass.db_connection()
    grass.run_command("db.connect", driver="pg", database="grassdata")
    grass.run_command("db.login", user="lucadelu", port="5432",
                      host="localhost", overwrite=True)

    # multiprocessing stuff for Angular coefficient Comparison
    q_in = Queue(1)
    q_out = Queue()
    procs = [Process(target=spawn(AngulatComparison), args=(q_in, q_out))
             for _ in range(nproc)]
    for proc in procs:
        proc.daemon = True
        proc.start()
    # for each file create the polygon of bounding box
    [q_in.put((f, processid, ref, osm, bf, list_lines,
               angle_thres)) for f in list_feature]
    # set the end of the cycle
    [q_in.put((None, None, None, None, None, None, None)) for proc in procs]
    [proc.join() for proc in procs]
    processed = [q_out.get() for _ in procs]
    errors = [p for p in processed if p]
    if errors:
        print "Some errors occurred during analysis"
        return 0

    grass.run_command("db.connect", driver=olddb['driver'],
                      database=olddb['database'])
    # Clean output map
    last_map = grass.read_command("g.list", type="vect", pattern="patch*",
                                  quiet=True).split("\n")[0:-1]
    finalpatch = "patch_{idd}_final".format(idd=processid)
    grass.run_command("v.patch", input=last_map, output=finalpatch,
                      quiet=True)
    grass.run_command("v.buffer", input=finalpatch, output=outbuff,
                      distance=0.0001, quiet=True)
    grass.run_command("v.overlay", ainput=osm_orig, atype="line",
                      binput=outbuff, output=out, operator="and",
                      flags="t", quiet=True)

    # Delete all maps
    grass.run_command("g.remove", type="vect", flags="f",
                      name=[deg_points, ref_degmin, degmin_points, ref_gen,
                            ref_split, osm_split, outbuff], quiet=True)

    grass.run_command("g.remove", flags="f", type="vect",
                      pattern="*{idd}*".format(idd=processid), quiet=True)

    # Calculate final map statistics
    l_osm_proc = length(out)
    diff_osm = l_osm - l_osm_proc
    diff_p_osm = diff_osm/l_osm*100
    diff_new = l_ref - l_osm_proc
    diff_p_new = diff_new/l_ref*100

    #  Write output file with statistics (if required)
    if len(out_file) > 0:
        fil=open(out_file, "w")
        fil.write("REF dataset length: %s m\n"%(round(l_ref,1)))
        fil.write("Original OSM dataset length: %s m\n"%(round(l_osm,1)))
        fil.write("Processed OSM dataset length: %s m\n"%(round(l_osm_proc,1)))
        fil.write("Difference between OSM original and processed datasets length: %s m (%s%%)\n"%(round(diff_osm,1),round(diff_p_osm,1)))
        fil.write("Difference between REF dataset and processed OSM dataset length: %s m (%s%%)\n"%(round(diff_new,1),round(diff_p_new,1)))
        fil.close()

    # Print statistics
    print("#####################################################################\n")
    print("Original OSM dataset length: %s m\n"%(round(l_osm,1)))
    print("Processed OSM dataset length: %s m\n"%(round(l_osm_proc,1)))
    print("Difference between OSM original and processed datasets length: %s m (%s%%)\n"%(round(diff_osm,1),round(diff_p_osm,1)))
    print("Difference between REF dataset and processed OSM dataset length: %s m (%s%%)\n"%(round(diff_new,1),round(diff_p_new,1)))
    print("#####################################################################\n")
    return 0

if __name__ == "__main__":
    options, flags = grass.parser()
    sys.exit(main())
