import argparse
import logging
import sys
import os
import re
from multiprocessing import Process


from gcodeutils.filter.relative_extrusion import GCodeToRelativeExtrusionFilter
from gcodeutils.gcoder import GCode
from gcodeutils.filter.arc_optimizer import GCodeArcOptimizerFilter

__author__ = 'Eyck Jentzsch <eyck@jepemuc.de>'

def worker(tempFile):
    logging.info("Parsing gcode...")
    gcode = GCode(open(tempFile).readlines())
    GCodeArcOptimizerFilter().filter(gcode)
    gcode.write(open(tempFile, 'w') )

def main():
    """command line entry point"""
    parser = argparse.ArgumentParser(description='Modify GCode program to account arcs and replace the G1 with G2/G3')

    parser.add_argument('infile', nargs='?', type=argparse.FileType('r'), default=sys.stdin,
                        help='Program filename to be modified. Defaults to standard input.')
    parser.add_argument('outfile', nargs='?', type=argparse.FileType('w'), default=sys.stdout,
                        help='Modified program. Defaults to standard output.')
    parser.add_argument('--inplace', '-i', action='store_true', help='Modify file inplace')

    parser.add_argument('--verbose', '-v', action='count', default=1, help='Verbose mode')
    parser.add_argument('--quiet', '-q', action='count', default=0, help='Quiet mode')
    parser.add_argument('--compact', '-c', action='store_true', help='Removes white spaces and decimal places. Comments are not affected')

    args = parser.parse_args()

    # count verbose and quiet flags to determine logging level
    args.verbose -= args.quiet

    if args.verbose > 1:
        logging.root.setLevel(logging.DEBUG)
    elif args.verbose > 0:
        logging.root.setLevel(logging.INFO)

    logging.basicConfig(format="%(levelname)s:%(message)s")
    
    cpus = len(os.sched_getaffinity(0))
    logging.info("Number of CPUs %s" % cpus)
    
    for line in args.infile:
        if line.startswith(";LAYER_COUNT"):
            layers = (int) (line.split(":")[1])
            logging.info("Number of Layers: %s" % layers)

    layersPerThread = (int) (layers / cpus) + 1
    logging.info("Number of Layers Per Thread: %s" % layersPerThread)
    
    args.infile.seek(0)
    
    gcodes = []
    tempFiles = []
    procs = []
    i = 0
    tempFiles.append(open(args.infile.name + str(i), 'w'))
    for line in args.infile:
        if line.startswith(";LAYER:"):
            layerNum = int(line.split(":")[1])
            if layerNum > (i + 1) * layersPerThread:
                tempFiles[i].close()
                i += 1
                tempFiles.append(open(args.infile.name + str(i), 'w'))
        tempFiles[i].write(line)
    tempFiles[i].close()
        
    for tempFile in tempFiles:
        p = Process(target=worker, args=(tempFile.name,))
        procs.append(p)
        p.start()
        
    for proc in procs:
        proc.join()
    # write back modified gcode
    outFile = open(args.infile.name, 'w') if args.inplace is True and args.infile != sys.stdin else args.outfile
    
    for tempFile in tempFiles:
        tempFile = open(tempFile.name)
        for line in tempFile:
            if args.compact:
                lines = line.split(";")
                lines[0] = re.sub("(F\\d+)(\\.\\d+)", "\\1", lines[0])
                lines[0] = re.sub(" ", "", lines[0])
                if len(lines) > 1:
                    line = lines[0] + ";" + lines[1]
                else:
                    line = lines[0]
                outFile.write(line)
            else:
                outFile.write(line)
            
        os.remove(tempFile.name)
    outFile.flush()
    outFile.close()
if __name__ == "__main__":
    main()


    