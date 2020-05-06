#!/usr/bin/python

import os
import time
import argparse
import sqlite3
import queue
import threading

from section_conversion import convertSection
from blob_writer import writeBlob

from quarry.types.nbt import RegionFile
from quarry.types.registry import OpaqueRegistry
from quarry.types.chunk import BlockArray

# Iterate over all mca files
def mcaIterator(mca_path,mca_filename):
    registry = OpaqueRegistry(None)
    with RegionFile(mca_path+mca_filename) as region_file:
        for chunk_x in range(0,32):
            for chunk_z in range(0,32):
                try: chunk = region_file.load_chunk(chunk_x,chunk_z)
                except ValueError as e: continue
                for section in chunk.value[''].value['Level'].value['Sections'].value:
                    try: blocks = BlockArray.from_nbt(section,registry)
                    except KeyError as e: continue
                    yield {
                        'mca' : mca_filename,
                        'x' : chunk_x,
                        'z' : chunk_z,
                        'y' : int.from_bytes(section.value['Y'].to_bytes(),'big'),
                        'blocks' : blocks,
                    }

#Copied from world_format.txt
def getBlockAsInteger(p):
    return int64(p[2]*16777216 + p[1]*4096 + p[0])

def int64(u):
    while u >= 2**63:
        u -= 2**64
    while u <= -2**63:
        u += 2**64
    return u
                    
# Main
if __name__ == '__main__':
    # Parse args
    parser = argparse.ArgumentParser(description='Convert maps from Minecraft to Minetest.',epilog="""
    This script uses quarry library from barneygale to read mca files.
    More details at https://quarry.readthedocs.io/en/latest
    """)
    parser.add_argument('input',help='Minecraft input world folder')
    parser.add_argument('output',help='Output folder for the generated world. Must not exist.')
    #parser.add_argument("--threads","-t",type=int,default=1,help="Number of worker threads")
    args = parser.parse_args()
    
    # Create world structure
    try: os.makedirs(args.output)
    except FileExistsError:
        print("Output folder must not exist.")
        exit()
    
    with open(args.output+"/world.mt",'w') as world_mt:
        world_mt.write(
            "enable_damage = false\n" +\
            "creative_mode = true\n" +\
            "gameid = minetest\n" +\
            "backend = sqlite3\n" +\
            "auth_backend = sqlite3\n" +\
            "player_backend = sqlite3\n" +\
            "")
    os.makedirs(args.output+"/worldmods/mc2mt")
    with open(args.output+"/worldmods/mc2mt/init.lua",'w') as map_meta:
        map_meta.write(
            'minetest.set_mapgen_params({water_level = -2})\n' +\
            'minetest.set_mapgen_params({chunksize = 1})\n' +\
            'minetest.set_mapgen_params({mgname = "singlenode"})\n' +\
            'minetest.register_on_generated(function(minp, maxp, seed)\n' +\
            '        local vm = minetest.get_voxel_manip(minp, maxp)\n' +\
            '        vm:update_liquids()\n' +\
            '        vm:write_to_map()\n' +\
            'end)\n' +\
            "")

    # Database
    connection = sqlite3.connect(args.output+"/map.sqlite")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS `blocks` (`pos` INT NOT NULL PRIMARY KEY, `data` BLOB);")
    

    # Conversion
    num_saved = 0
    start_time = time.time()
    biggest_chunk = (0,0)
    num_mca = len(os.listdir(args.input+"/region"))
    mca_filenames =  os.listdir(args.input+"/region")
    for i in range(len(mca_filenames)):
        print("Converting",mca_filenames[i],"file",i,"of",num_mca)
        for found_section in mcaIterator(args.input+"/region/",mca_filenames[i]):
            converted_section = convertSection(found_section)
            pos = converted_section['pos']
            blob = writeBlob(converted_section)
            key = getBlockAsInteger(pos)
            cursor.execute("INSERT INTO blocks VALUES (?,?)",(key,blob))
            print(f"Blocks saved:",num_saved,end="\r")
            num_saved += 1
            if not num_saved%128: connection.commit()
            if len(blob) > biggest_chunk[1]: biggest_chunk = (pos,len(blob))
        
    # End
    connection.commit()
    connection.close()
    print("All",num_saved,"blocks saved!")
    print("Biggest chunk is at",*[i*16 for i in biggest_chunk[0]])
    elapsed_time = ( time.time()-start_time ) / 60 
    print("Conversion ended in",f"{elapsed_time:.02f}","m")
