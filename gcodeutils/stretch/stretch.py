"""
This page is in the table of contents.
Stretch is very important Skeinforge plugin that allows you to partially compensate for the fact that extruded holes are smaller then they should be.  It stretches the threads to partially compensate for filament shrinkage when extruded.

The stretch manual page is at:
http://fabmetheus.crsndoo.com/wiki/index.php/Skeinforge_Stretch

Extruded holes are smaller than the model because while printing an arc the head is depositing filament on both sides of the arc but in the inside of the arc you actually need less material then on the outside of the arc. You can read more about this on the RepRap ArcCompensation page:
http://reprap.org/bin/view/Main/ArcCompensation

In general, stretch will widen holes and push corners out.  In practice the filament contraction will not be identical to the algorithm, so even once the optimal parameters are determined, the stretch script will not be able to eliminate the inaccuracies caused by contraction, but it should reduce them.

All the defaults assume that the thread sequence choice setting in fill is the edge being extruded first, then the loops, then the infill.  If the thread sequence choice is different, the optimal thread parameters will also be different.  In general, if the infill is extruded first, the infill would have to be stretched more so that even after the filament shrinkage, it would still be long enough to connect to the loop or edge.

Holes should be made with the correct area for their radius.  In other words, for example if your modeling program approximates a hole of radius one (area = pi) by making a square with the points at [(1,0), (0,1), (-1,0), (0,-1)] (area = 2), the radius should be increased by sqrt(pi/2).  This can be done in fabmetheus xml by writing:
radiusAreal='True'

in the attributes of the object or any parent of that object.  In other modeling programs, you'll have to this manually or make a script.  If area compensation is not done, then changing the stretch parameters to over compensate for too small hole areas will lead to incorrect compensation in other shapes.

==Operation==
The default 'Activate Stretch' checkbox is off.  When it is on, the functions described below will work, when it is off, the functions will not be called.

==Settings==
===Loop Stretch Over Perimeter Width===
Default is 0.1.

Defines the ratio of the maximum amount the loop aka inner shell threads will be stretched compared to the edge width, in general this value should be the same as the 'Perimeter Outside Stretch Over Perimeter Width' setting.

===Path Stretch Over Perimeter Width===
Default is zero.

Defines the ratio of the maximum amount the threads which are not loops, like the infill threads, will be stretched compared to the edge width.

===Perimeter===
====Perimeter Inside Stretch Over Perimeter Width====
Default is 0.32.

Defines the ratio of the maximum amount the inside edge thread will be stretched compared to the edge width, this is the most important setting in stretch.  The higher the value the more it will stretch the edge and the wider holes will be.  If the value is too small, the holes could be drilled out after fabrication, if the value is too high, the holes would be too wide and the part would have to junked.

====Perimeter Outside Stretch Over Perimeter Width====
Default is 0.1.

Defines the ratio of the maximum amount the outside edge thread will be stretched compared to the edge width, in general this value should be around a third of the 'Perimeter Inside Stretch Over Perimeter Width' setting.

===Stretch from Distance over Perimeter Width===
Default is two.

The stretch algorithm works by checking at each turning point on the extrusion path what the direction of the thread is at a distance of 'Stretch from Distance over Perimeter Width' times the edge width, on both sides, and moves the thread in the opposite direction.  So it takes the current turning-point, goes "Stretch from Distance over Perimeter Width" * "Perimeter Width" ahead, reads the direction at that point.  Then it goes the same distance in back in time, reads the direction at that other point.  It then moves the thread in the opposite direction, away from the center of the arc formed by these 2 points+directions.

The magnitude of the stretch increases with:
the amount that the direction of the two threads is similar and
by the '..Stretch Over Perimeter Width' ratio.

==Examples==
The following examples stretch the file Screw Holder Bottom.stl.  The examples are run in a terminal in the folder which contains Screw Holder Bottom.stl and stretch.py.

> python stretch.py
This brings up the stretch dialog.

> python stretch.py Screw Holder Bottom.stl
The stretch tool is parsing the file:
Screw Holder Bottom.stl
..
The stretch tool has created the file:
.. Screw Holder Bottom_stretch.gcode

"""

from __future__ import absolute_import
# Init has to be imported first because it has code to workaround the python bug where relative imports don't work if the module is imported as a main module.
# import __init__
import re

from .distanceFeedRate import DistanceFeedRate
from gcodeutils.gcoder import GCode, Layer
from .vector3 import Vector3

__author__ = 'Enrique Perez (perez_enrique@yahoo.com)'
__date__ = '$Date: 2008/21/04 $'
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'


def getIndexOfStartingWithSecond(letter, splitLine):
    'Get index of the first occurence of the given letter in the split line, starting with the second word.  Return - 1 if letter is not found'
    for wordIndex in xrange(1, len(splitLine)):
        word = splitLine[wordIndex]
        firstLetter = word[0]
        if firstLetter == letter:
            return wordIndex
    return - 1


def getDoubleFromCharacterSplitLine(character, splitLine):
    'Get the double value of the string after the first occurence of the character in the split line.'
    indexOfCharacter = getIndexOfStartingWithSecond(character, splitLine)
    if indexOfCharacter < 0:
        return None
    floatString = splitLine[indexOfCharacter][1:]
    try:
        return float(floatString)
    except ValueError:
        return None


def getDoubleFromCharacterSplitLineValue(character, splitLine, value):
    'Get the double value of the string after the first occurence of the character in the split line, if it does not exist return the value.'
    splitLineFloat = getDoubleFromCharacterSplitLine(character, splitLine)
    if splitLineFloat == None:
        return value
    return splitLineFloat


def getLocationFromSplitLine(oldLocation, splitLine, line):
    'Get the location from the split line.'
    if oldLocation == None:
        oldLocation = Vector3()
    return Vector3(
        getDoubleFromCharacterSplitLineValue('X', splitLine, oldLocation.x),
        getDoubleFromCharacterSplitLineValue('Y', splitLine, oldLocation.y),
        getDoubleFromCharacterSplitLineValue('Z', splitLine, oldLocation.z))


def getFirstWord(splitLine):
    'Get the first word of a split line.'
    if len(splitLine) > 0:
        return splitLine[0]
    return ''


def getSplitLineBeforeBracketSemicolon(line):
    'Get the split line before a bracket or semicolon.'
    if ';' in line:
        line = line[: line.find(';')]
    bracketIndex = line.find('(')
    if bracketIndex > 0:
        return line[: bracketIndex].split()
    return line.split()


def getDotProduct(firstComplex, secondComplex):
    'Get the dot product of a pair of complexes.'
    return firstComplex.real * secondComplex.real + firstComplex.imag * secondComplex.imag


def getCraftedTextFromText(gcodeText):
    "Stretch a gcode linear move text."
    return GCode(StretchFilter().filter(gcodeText).split('\n'))


class LineIteratorBackward:
    "Backward line iterator class."

    def __init__(self, isLoop, lineIndex, lines):
        self.firstLineIndex = None
        self.isLoop = isLoop
        self.lineIndex = lineIndex
        # self.lines = [l.raw for l in lines]
        self.lines = lines

    def getIndexBeforeNextDeactivate(self):
        "Get index two lines before the deactivate command."
        for lineIndex in xrange(self.lineIndex + 1, len(self.lines)):
            if self.lines[lineIndex].command == 'M103':
                return lineIndex - 2
        print('This should never happen in stretch, no deactivate command was found for this thread.')
        raise StopIteration, "You've reached the end of the line."

    def getNext(self):
        "Get next line going backward or raise exception."

        if self.lineIndex < 1:
            if self.isLoop:
                self.lineIndex = self.getIndexBeforeNextDeactivate()

        while self.lineIndex >= 0:
            if self.lineIndex == self.firstLineIndex:
                raise StopIteration, "You've reached the end of the line."
            if self.firstLineIndex == None:
                self.firstLineIndex = self.lineIndex
            nextLineIndex = self.lineIndex - 1
            line = self.lines[self.lineIndex]
            if line.command == 'M103':
                if self.isLoop:
                    nextLineIndex = self.getIndexBeforeNextDeactivate()
                else:
                    raise StopIteration, "You've reached the end of the line."
            if line.command == 'G1':
                if self.isBeforeExtrusion():
                    if self.isLoop:
                        nextLineIndex = self.getIndexBeforeNextDeactivate()
                    else:
                        raise StopIteration, "You've reached the end of the line."
                else:
                    self.lineIndex = nextLineIndex
                    return line.raw
            self.lineIndex = nextLineIndex

        if self.isLoop:
            nextLineIndex = self.getIndexBeforeNextDeactivate()

        raise StopIteration, "You've reached the end of the line."

    def isBeforeExtrusion(self):
        "Determine if index is two or more before activate command."
        linearMoves = 0
        for lineIndex in xrange(self.lineIndex + 1, len(self.lines)):
            line = self.lines[lineIndex]
            if line.command == 'G1':
                linearMoves += 1
            if line.command == 'M101':
                return linearMoves > 0
            if line.command == 'M103':
                return False
        print(
            'This should never happen in isBeforeExtrusion in stretch, no activate command was found for this thread.')
        return False


class LineIteratorForward(LineIteratorBackward):
    "Forward line iterator class."

    def getIndexJustAfterActivate(self):
        "Get index just after the activate command."
        for lineIndex in xrange(self.lineIndex - 1, 0, - 1):
            if self.lines[lineIndex].command == 'M101':
                return lineIndex + 1
        print('This should never happen in stretch, no activate command was found for this thread.')
        raise StopIteration, "You've reached the end of the line."

    def getNext(self):
        "Get next line or raise exception."
        while self.lineIndex < len(self.lines):
            if self.lineIndex == self.firstLineIndex:
                raise StopIteration, "You've reached the end of the line."
            if self.firstLineIndex == None:
                self.firstLineIndex = self.lineIndex
            nextLineIndex = self.lineIndex + 1
            line = self.lines[self.lineIndex]
            if line.command == 'M103':
                if self.isLoop:
                    nextLineIndex = self.getIndexJustAfterActivate()
                else:
                    raise StopIteration, "You've reached the end of the line."
            self.lineIndex = nextLineIndex
            if line.command == 'G1':
                return line.raw
        raise StopIteration, "You've reached the end of the line."


class StretchRepository:
    "A class to handle the stretch settings."

    def __init__(self):
        "Set the default settings, execute title & settings fileName."
        self.activateStretch = True  # Activate Stretch
        self.crossLimitDistanceOverEdgeWidth = 5.0  # Cross Limit Distance Over Perimeter Width (ratio)
        self.loopStretchOverEdgeWidth = 0.11  # Loop Stretch Over Perimeter Width (ratio)
        self.pathStretchOverEdgeWidth = 0.0  # Path Stretch Over Perimeter Width (ratio)
        self.edgeInsideStretchOverEdgeWidth = 0.32  # Perimeter Inside Stretch Over Perimeter Width (ratio)
        self.edgeOutsideStretchOverEdgeWidth = 0.1  # Perimeter Outside Stretch Over Perimeter Width (ratio)
        self.stretchFromDistanceOverEdgeWidth = 2.0  # Stretch From Distance Over Perimeter Width (ratio)


class StretchFilter:
    "A class to stretch a skein of extrusions."

    EDGE_WIDTH_REGEXP = re.compile(r'\(<edgeWidth> ([\.\d]+)')

    def __init__(self):
        self.distanceFeedRate = DistanceFeedRate()
        self.edgeWidth = 0.4
        self.extruderActive = False
        self.feedRateMinute = 959.0
        self.isLoop = False
        self.oldLocation = None
        self.gcode = None
        self.current_layer = None
        self.line_number_in_layer = 0
        self.stretchRepository = StretchRepository()

        self.thread_maximum_absolute_stretch = 0

    def filter(self, gcodeText):
        "Parse gcode text and store the stretch gcode."
        self.gcode = GCode(gcodeText.split('\n'))
        # self.stretchRepository = stretchRepository

        init_done = False

        for self.current_layer_index, self.current_layer in enumerate(self.gcode.all_layers):
            for self.line_number_in_layer, line in enumerate(self.current_layer):
                if init_done:
                    self.parse_line(line)
                else:
                    init_done = self.parse_initialisation_line(line)

        return self.distanceFeedRate.output.getvalue()

    def getCrossLimitedStretch(self, crossLimitedStretch, crossLineIterator, locationComplex):
        "Get cross limited relative stretch for a location."
        try:
            line = crossLineIterator.getNext()
        except StopIteration:
            return crossLimitedStretch
        splitLine = getSplitLineBeforeBracketSemicolon(line)
        pointComplex = getLocationFromSplitLine(self.oldLocation, splitLine, line).dropAxis()
        pointMinusLocation = locationComplex - pointComplex
        pointMinusLocationLength = abs(pointMinusLocation)
        if pointMinusLocationLength <= self.crossLimitDistanceFraction:
            return crossLimitedStretch
        parallelNormal = pointMinusLocation / pointMinusLocationLength
        parallelStretch = getDotProduct(parallelNormal, crossLimitedStretch) * parallelNormal
        if pointMinusLocationLength > self.crossLimitDistance:
            return parallelStretch
        crossNormal = complex(parallelNormal.imag, - parallelNormal.real)
        crossStretch = getDotProduct(crossNormal, crossLimitedStretch) * crossNormal
        crossPortion = (self.crossLimitDistance - pointMinusLocationLength) / self.crossLimitDistanceRemainder
        return parallelStretch + crossStretch * crossPortion

    def getRelativeStretch(self, locationComplex, lineIterator):
        "Get relative stretch for a location."
        lastLocationComplex = locationComplex
        oldTotalLength = 0.0
        pointComplex = locationComplex
        totalLength = 0.0
        while 1:
            try:
                line = lineIterator.getNext()
            except StopIteration:
                locationMinusPoint = locationComplex - pointComplex
                locationMinusPointLength = abs(locationMinusPoint)
                if locationMinusPointLength > 0.0:
                    return locationMinusPoint / locationMinusPointLength
                return complex()
            splitLine = getSplitLineBeforeBracketSemicolon(line)
            firstWord = splitLine[0]
            pointComplex = getLocationFromSplitLine(self.oldLocation, splitLine, line).dropAxis()
            locationMinusPoint = lastLocationComplex - pointComplex
            locationMinusPointLength = abs(locationMinusPoint)
            totalLength += locationMinusPointLength
            if totalLength >= self.stretchFromDistance:
                distanceFromRatio = (self.stretchFromDistance - oldTotalLength) / locationMinusPointLength
                totalPoint = distanceFromRatio * pointComplex + (1.0 - distanceFromRatio) * lastLocationComplex
                locationMinusTotalPoint = locationComplex - totalPoint
                return locationMinusTotalPoint / self.stretchFromDistance
            lastLocationComplex = pointComplex
            oldTotalLength = totalLength

    def getStretchedLine(self, splitLine, line):
        "Get stretched gcode line."
        location = getLocationFromSplitLine(self.oldLocation, splitLine, line)
        self.feedRateMinute = line.f or self.feedRateMinute
        self.oldLocation = location
        if self.extruderActive and self.thread_maximum_absolute_stretch > 0.0:
            return self.getStretchedLineFromIndexLocation(self.line_number_in_layer - 1, self.line_number_in_layer + 1,
                                                          location)
        if self.isJustBeforeExtrusion() and self.thread_maximum_absolute_stretch > 0.0:
            return self.getStretchedLineFromIndexLocation(self.line_number_in_layer - 1, self.line_number_in_layer + 1,
                                                          location)
        return line.raw

    def getStretchedLineFromIndexLocation(self, indexPreviousStart, indexNextStart, location):
        "Get stretched gcode line from line index and location."
        crossIteratorForward = LineIteratorForward(self.isLoop, indexNextStart, self.current_layer)
        crossIteratorBackward = LineIteratorBackward(self.isLoop, indexPreviousStart, self.current_layer)
        iteratorForward = LineIteratorForward(self.isLoop, indexNextStart, self.current_layer)
        iteratorBackward = LineIteratorBackward(self.isLoop, indexPreviousStart, self.current_layer)
        locationComplex = location.dropAxis()
        relativeStretch = self.getRelativeStretch(locationComplex, iteratorForward) + self.getRelativeStretch(
            locationComplex, iteratorBackward)
        relativeStretch *= 0.8
        relativeStretch = self.getCrossLimitedStretch(relativeStretch, crossIteratorForward, locationComplex)
        relativeStretch = self.getCrossLimitedStretch(relativeStretch, crossIteratorBackward, locationComplex)
        relativeStretchLength = abs(relativeStretch)
        if relativeStretchLength > 1.0:
            relativeStretch /= relativeStretchLength
        absoluteStretch = relativeStretch * self.thread_maximum_absolute_stretch
        stretchedPoint = location.dropAxis() + absoluteStretch
        return self.distanceFeedRate.getLinearGcodeMovementWithFeedRate(self.feedRateMinute, stretchedPoint, location.z)

    def isJustBeforeExtrusion(self):
        "Determine if activate command is before linear move command."
        for line in self.current_layer[self.line_number_in_layer + 1:]:
            if line.command == 'G1' or line.command == 'M103':
                return False
            if line.command == 'M101':
                return True
        return False

    def parse_initialisation_line(self, line):
        self.distanceFeedRate.parseSplitLine(line.raw)
        if line.raw == '(</extruderInitialization>)':
            return True
        match = self.EDGE_WIDTH_REGEXP.match(line.raw)
        if match:
            edgeWidth = float(match.group(1))
            self.crossLimitDistance = self.edgeWidth * self.stretchRepository.crossLimitDistanceOverEdgeWidth
            self.loopMaximumAbsoluteStretch = self.edgeWidth * self.stretchRepository.loopStretchOverEdgeWidth
            self.pathAbsoluteStretch = self.edgeWidth * self.stretchRepository.pathStretchOverEdgeWidth
            self.edgeInsideAbsoluteStretch = self.edgeWidth * self.stretchRepository.edgeInsideStretchOverEdgeWidth
            self.edgeOutsideAbsoluteStretch = self.edgeWidth * self.stretchRepository.edgeOutsideStretchOverEdgeWidth
            self.stretchFromDistance = self.stretchRepository.stretchFromDistanceOverEdgeWidth * edgeWidth
            self.thread_maximum_absolute_stretch = self.pathAbsoluteStretch
            self.crossLimitDistanceFraction = 0.333333333 * self.crossLimitDistance
            self.crossLimitDistanceRemainder = self.crossLimitDistance - self.crossLimitDistanceFraction
        self.distanceFeedRate.addLine(line.raw)
        return False

    def parse_line(self, line):
        """Parse a gcode line and add it to the stretch skein."""
        splitLine = getSplitLineBeforeBracketSemicolon(line.raw)
        command = splitLine[0]
        if command == 'G1':
            self.distanceFeedRate.addLine(self.getStretchedLine(splitLine, line))
            return
        elif command == 'M101':
            self.extruderActive = True
        elif command == 'M103':
            self.extruderActive = False
            self.set_stretch_to_path()
        elif self.is_loop_begin(line):
            self.isLoop = True
            self.thread_maximum_absolute_stretch = self.loopMaximumAbsoluteStretch
        elif self.is_loop_end(line):
            self.set_stretch_to_path()
        elif self.is_inner_edge_begin(line):
            self.isLoop = True
            self.thread_maximum_absolute_stretch = self.edgeInsideAbsoluteStretch
        elif self.is_outer_edge_begin(line):
            self.isLoop = True
            self.thread_maximum_absolute_stretch = self.edgeOutsideAbsoluteStretch
        elif self.is_edge_end(line):
            self.set_stretch_to_path()

        self.distanceFeedRate.addLine(line.raw)

    def set_stretch_to_path(self):
        """Set the thread stretch to path stretch and is loop false."""
        self.isLoop = False
        self.thread_maximum_absolute_stretch = self.pathAbsoluteStretch

    def is_loop_begin(self, line):
        return line.raw.startswith("(<loop>")

    def is_loop_end(self, line):
        return line.raw.startswith("(</loop>)")

    def is_inner_edge_begin(self, line):
        return line.raw.startswith("(<edge>") and not line.raw.startswith("(<edge> outer")

    def is_outer_edge_begin(self, line):
        return line.raw.startswith("(<edge> outer")

    def is_edge_end(self, line):
        return line.raw.startswith("(/edge>)")