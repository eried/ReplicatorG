"""
This page is in the table of contents.
Fillet rounds the corners slightly in a variety of ways.  This is to reduce corner blobbing and sudden extruder acceleration.

The fillet manual page is at:
http://www.bitsfrombytes.com/wiki/index.php?title=Skeinforge_Fillet

==Operation==
The default 'Activate Fillet' checkbox is off.  When it is on, the functions described below will work, when it is off, the functions will not be called.

==Settings==
===Fillet Procedure Choice===
Default is 'Bevel''.

====Arc Point====
When selected, the corners will be filleted with an arc using the gcode point form.

====Arc Radius====
When selected, the corners will be filleted with an arc using the gcode radius form.

====Arc Segment====
When selected, the corners will be filleted with an arc composed of several segments.

====Bevel====
When selected, the corners will be beveled.

===Corner Feed Rate over Operating Feed Rate===
Default is one.

Defines the ratio of the feed rate in corners over the operating feed rate.  With a high value the extruder will move quickly in corners, accelerating quickly and leaving a thin extrusion.  With a low value, the extruder will move slowly in corners, accelerating gently and leaving a thick extrusion.

===Fillet Radius over Perimeter Width===
Default is 0.35.

Defines the width of the fillet.

===Reversal Slowdown over Perimeter Width===
Default is 0.5.

Defines how far before a path reversal the extruder will slow down.  Some tools, like nozzle wipe, double back the path of the extruder and this option will add a slowdown point in that path so there won't be a sudden jerk at the end of the path.  If the value is less than 0.1 a slowdown will not be added.

===Use Intermediate Feed Rate in Corners===
Default is on.

When selected, the feed rate entering the corner will be the average of the old feed rate and the new feed rate.

==Examples==
The following examples fillet the file Screw Holder Bottom.stl.  The examples are run in a terminal in the folder which contains Screw Holder Bottom.stl and fillet.py.


> python fillet.py
This brings up the fillet dialog.


> python fillet.py Screw Holder Bottom.stl
The fillet tool is parsing the file:
Screw Holder Bottom.stl
..
The fillet tool has created the file:
.. Screw Holder Bottom_fillet.gcode


> python
Python 2.5.1 (r251:54863, Sep 22 2007, 01:43:31)
[GCC 4.2.1 (SUSE Linux)] on linux2
Type "help", "copyright", "credits" or "license" for more information.
>>> import fillet
>>> fillet.main()
This brings up the fillet dialog.


>>> fillet.writeOutput('Screw Holder Bottom.stl')
The fillet tool is parsing the file:
Screw Holder Bottom.stl
..
The fillet tool has created the file:
.. Screw Holder Bottom_fillet.gcode

"""

from __future__ import absolute_import
#Init has to be imported first because it has code to workaround the python bug where relative imports don't work if the module is imported as a main module.
import __init__

from fabmetheus_utilities import euclidean
from fabmetheus_utilities import gcodec
from fabmetheus_utilities.fabmetheus_tools import fabmetheus_interpret
from fabmetheus_utilities import settings
from fabmetheus_utilities.vector3 import Vector3
from skeinforge_application.skeinforge_utilities import skeinforge_craft
from skeinforge_application.skeinforge_utilities import skeinforge_polyfile
from skeinforge_application.skeinforge_utilities import skeinforge_profile
import math
import sys


__author__ = 'Enrique Perez (perez_enrique@yahoo.com)'
__date__ = '$Date: 2008/21/04 $'
__license__ = 'GPL 3.0'


def getCraftedText( fileName, text, filletRepository = None ):
	"Fillet a gcode linear move file or text."
	return getCraftedTextFromText( gcodec.getTextIfEmpty( fileName, text ), filletRepository )

def getCraftedTextFromText( gcodeText, filletRepository = None ):
	"Fillet a gcode linear move text."
	if gcodec.isProcedureDoneOrFileIsEmpty( gcodeText, 'fillet'):
		return gcodeText
	if filletRepository == None:
		filletRepository = settings.getReadRepository( FilletRepository() )
	if not filletRepository.activateFillet.value:
		return gcodeText
	if filletRepository.arcPoint.value:
		return ArcPointSkein().getCraftedGcode( filletRepository, gcodeText )
	elif filletRepository.arcRadius.value:
		return ArcRadiusSkein().getCraftedGcode( filletRepository, gcodeText )
	elif filletRepository.arcSegment.value:
		return ArcSegmentSkein().getCraftedGcode( filletRepository, gcodeText )
	elif filletRepository.bevel.value:
		return BevelSkein().getCraftedGcode( filletRepository, gcodeText )
	return gcodeText

def getNewRepository():
	"Get the repository constructor."
	return FilletRepository()

def writeOutput( fileName = ''):
	"Fillet a gcode linear move file. Depending on the settings, either arcPoint, arcRadius, arcSegment, bevel or do nothing."
	fileName = fabmetheus_interpret.getFirstTranslatorFileNameUnmodified(fileName)
	if fileName != '':
		skeinforge_craft.writeChainTextWithNounMessage( fileName, 'fillet')


class BevelSkein:
	"A class to bevel a skein of extrusions."
	def __init__(self):
		self.distanceFeedRate = gcodec.DistanceFeedRate()
		self.extruderActive = False
		self.feedRateMinute = 960.0
		self.filletRadius = 0.2
		self.lineIndex = 0
		self.lines = None
		self.oldFeedRateMinute = None
		self.oldLocation = None
		self.shouldAddLine = True

	def addLinearMovePoint( self, feedRateMinute, point ):
		"Add a gcode linear move, feedRate and newline to the output."
		self.distanceFeedRate.addLine( self.distanceFeedRate.getLinearGcodeMovementWithFeedRate( feedRateMinute, point.dropAxis(2), point.z ) )

	def getCornerFeedRate(self):
		"Get the corner feed rate, which may be based on the intermediate feed rate."
		feedRateMinute = self.feedRateMinute
		if self.filletRepository.useIntermediateFeedRateInCorners.value:
			if self.oldFeedRateMinute != None:
				feedRateMinute = 0.5 * ( self.oldFeedRateMinute + self.feedRateMinute )
		return feedRateMinute * self.cornerFeedRateOverOperatingFeedRate

	def getCraftedGcode( self, filletRepository, gcodeText ):
		"Parse gcode text and store the bevel gcode."
		self.cornerFeedRateOverOperatingFeedRate = filletRepository.cornerFeedRateOverOperatingFeedRate.value
		self.lines = gcodec.getTextLines(gcodeText)
		self.filletRepository = filletRepository
		self.parseInitialization( filletRepository )
		for self.lineIndex in xrange( self.lineIndex, len( self.lines ) ):
			line = self.lines[ self.lineIndex ]
			self.parseLine(line)
		return self.distanceFeedRate.output.getvalue()

	def getExtruderOffReversalPoint( self, afterSegment, afterSegmentComplex, beforeSegment, beforeSegmentComplex, location ):
		"If the extruder is off and the path is reversing, add intermediate slow points."
		if self.filletRepository.reversalSlowdownDistanceOverPerimeterWidth.value < 0.1:
			return None
		if self.extruderActive:
			return None
		reversalBufferSlowdownDistance = self.reversalSlowdownDistance * 2.0
		afterSegmentComplexLength = abs( afterSegmentComplex )
		if afterSegmentComplexLength < reversalBufferSlowdownDistance:
			return None
		beforeSegmentComplexLength = abs( beforeSegmentComplex )
		if beforeSegmentComplexLength < reversalBufferSlowdownDistance:
			return None
		afterSegmentComplexNormalized = afterSegmentComplex / afterSegmentComplexLength
		beforeSegmentComplexNormalized = beforeSegmentComplex / beforeSegmentComplexLength
		if euclidean.getDotProduct( afterSegmentComplexNormalized, beforeSegmentComplexNormalized ) < 0.95:
			return None
		slowdownFeedRate = self.feedRateMinute * 0.5
		self.shouldAddLine = False
		beforePoint = euclidean.getPointPlusSegmentWithLength( self.reversalSlowdownDistance * abs( beforeSegment ) / beforeSegmentComplexLength, location, beforeSegment )
		self.addLinearMovePoint( self.feedRateMinute, beforePoint )
		self.addLinearMovePoint( slowdownFeedRate, location )
		afterPoint = euclidean.getPointPlusSegmentWithLength( self.reversalSlowdownDistance * abs( afterSegment ) / afterSegmentComplexLength, location, afterSegment )
		self.addLinearMovePoint( slowdownFeedRate, afterPoint )
		return afterPoint

	def getNextLocation(self):
		"Get the next linear move.  Return none is none is found."
		for afterIndex in xrange( self.lineIndex + 1, len( self.lines ) ):
			line = self.lines[ afterIndex ]
			splitLine = gcodec.getSplitLineBeforeBracketSemicolon(line)
			if gcodec.getFirstWord(splitLine) == 'G1':
				nextLocation = gcodec.getLocationFromSplitLine(self.oldLocation, splitLine)
				return nextLocation
		return None

	def linearMove( self, splitLine ):
		"Bevel a linear move."
		location = gcodec.getLocationFromSplitLine(self.oldLocation, splitLine)
		self.feedRateMinute = gcodec.getFeedRateMinute( self.feedRateMinute, splitLine )
		if self.oldLocation != None:
			nextLocation = self.getNextLocation()
			if nextLocation != None:
				location = self.splitPointGetAfter( location, nextLocation )
		self.oldLocation = location
		self.oldFeedRateMinute = self.feedRateMinute

	def parseInitialization( self, filletRepository ):
		"Parse gcode initialization and store the parameters."
		for self.lineIndex in xrange( len( self.lines ) ):
			line = self.lines[ self.lineIndex ]
			splitLine = gcodec.getSplitLineBeforeBracketSemicolon(line)
			firstWord = gcodec.getFirstWord(splitLine)
			self.distanceFeedRate.parseSplitLine( firstWord, splitLine )
			if firstWord == '(</extruderInitialization>)':
				self.distanceFeedRate.addLine('(<procedureDone> fillet </procedureDone>)')
				return
			elif firstWord == '(<perimeterWidth>':
				perimeterWidth = abs( float(splitLine[1]) )
				self.curveSection = 0.7 * perimeterWidth
				self.filletRadius = perimeterWidth * filletRepository.filletRadiusOverPerimeterWidth.value
				self.minimumRadius = 0.1 * perimeterWidth
				self.reversalSlowdownDistance = perimeterWidth * filletRepository.reversalSlowdownDistanceOverPerimeterWidth.value
			self.distanceFeedRate.addLine(line)

	def parseLine(self, line):
		"Parse a gcode line and add it to the bevel gcode."
		self.shouldAddLine = True
		splitLine = gcodec.getSplitLineBeforeBracketSemicolon(line)
		if len(splitLine) < 1:
			return
		firstWord = splitLine[0]
		if firstWord == 'G1':
			self.linearMove(splitLine)
		elif firstWord == 'M101':
			self.extruderActive = True
		elif firstWord == 'M103':
			self.extruderActive = False
		if self.shouldAddLine:
			self.distanceFeedRate.addLine(line)

	def splitPointGetAfter( self, location, nextLocation ):
		"Bevel a point and return the end of the bevel.   should get complex for radius"
		if self.filletRadius < 2.0 * self.minimumRadius:
			return location
		afterSegment = nextLocation - location
		afterSegmentComplex = afterSegment.dropAxis(2)
		afterSegmentComplexLength = abs( afterSegmentComplex )
		thirdAfterSegmentLength = 0.333 * afterSegmentComplexLength
		if thirdAfterSegmentLength < self.minimumRadius:
			return location
		beforeSegment = self.oldLocation - location
		beforeSegmentComplex = beforeSegment.dropAxis(2)
		beforeSegmentComplexLength = abs( beforeSegmentComplex )
		thirdBeforeSegmentLength = 0.333 * beforeSegmentComplexLength
		if thirdBeforeSegmentLength < self.minimumRadius:
			return location
		extruderOffReversalPoint = self.getExtruderOffReversalPoint( afterSegment, afterSegmentComplex, beforeSegment, beforeSegmentComplex, location )
		if extruderOffReversalPoint != None:
			return extruderOffReversalPoint
		bevelRadius = min( thirdAfterSegmentLength, self.filletRadius )
		bevelRadius = min( thirdBeforeSegmentLength, bevelRadius )
		self.shouldAddLine = False
		beforePoint = euclidean.getPointPlusSegmentWithLength( bevelRadius * abs( beforeSegment ) / beforeSegmentComplexLength, location, beforeSegment )
		self.addLinearMovePoint( self.feedRateMinute, beforePoint )
		afterPoint = euclidean.getPointPlusSegmentWithLength( bevelRadius * abs( afterSegment ) / afterSegmentComplexLength, location, afterSegment )
		self.addLinearMovePoint( self.getCornerFeedRate(), afterPoint )
		return afterPoint


class ArcSegmentSkein( BevelSkein ):
	"A class to arc segment a skein of extrusions."
	def addArc( self, afterCenterDifferenceAngle, afterPoint, beforeCenterSegment, beforePoint, center ):
		"Add arc segments to the filleted skein."
		absoluteDifferenceAngle = abs( afterCenterDifferenceAngle )
#		steps = int( math.ceil( absoluteDifferenceAngle * 1.5 ) )
		steps = int( math.ceil( min( absoluteDifferenceAngle * 1.5, absoluteDifferenceAngle * abs( beforeCenterSegment ) / self.curveSection ) ) )
		stepPlaneAngle = euclidean.getWiddershinsUnitPolar( afterCenterDifferenceAngle / steps )
		for step in xrange( 1, steps ):
			beforeCenterSegment = euclidean.getRoundZAxisByPlaneAngle( stepPlaneAngle, beforeCenterSegment )
			arcPoint = center + beforeCenterSegment
			self.addLinearMovePoint( self.getCornerFeedRate(), arcPoint )
		self.addLinearMovePoint( self.getCornerFeedRate(), afterPoint )

	def splitPointGetAfter( self, location, nextLocation ):
		"Fillet a point into arc segments and return the end of the last segment."
		if self.filletRadius < 2.0 * self.minimumRadius:
			return location
		afterSegment = nextLocation - location
		afterSegmentComplex = afterSegment.dropAxis(2)
		thirdAfterSegmentLength = 0.333 * abs( afterSegmentComplex )
		if thirdAfterSegmentLength < self.minimumRadius:
			return location
		beforeSegment = self.oldLocation - location
		beforeSegmentComplex = beforeSegment.dropAxis(2)
		thirdBeforeSegmentLength = 0.333 * abs( beforeSegmentComplex )
		if thirdBeforeSegmentLength < self.minimumRadius:
			return location
		extruderOffReversalPoint = self.getExtruderOffReversalPoint( afterSegment, afterSegmentComplex, beforeSegment, beforeSegmentComplex, location )
		if extruderOffReversalPoint != None:
			return extruderOffReversalPoint
		bevelRadius = min( thirdAfterSegmentLength, self.filletRadius )
		bevelRadius = min( thirdBeforeSegmentLength, bevelRadius )
		self.shouldAddLine = False
		beforePoint = euclidean.getPointPlusSegmentWithLength( bevelRadius * abs( beforeSegment ) / abs( beforeSegmentComplex ), location, beforeSegment )
		self.addLinearMovePoint( self.feedRateMinute, beforePoint )
		afterPoint = euclidean.getPointPlusSegmentWithLength( bevelRadius * abs( afterSegment ) / abs( afterSegmentComplex ), location, afterSegment )
		afterPointComplex = afterPoint.dropAxis(2)
		beforePointComplex = beforePoint.dropAxis(2)
		locationComplex = location.dropAxis(2)
		midpoint = 0.5 * ( afterPoint + beforePoint )
		midpointComplex = midpoint.dropAxis(2)
		midpointMinusLocationComplex = midpointComplex - locationComplex
		midpointLocationLength = abs( midpointMinusLocationComplex )
		if midpointLocationLength < 0.01 * self.filletRadius:
			self.addLinearMovePoint( self.getCornerFeedRate(), afterPoint )
			return afterPoint
		midpointAfterPointLength = abs( midpointComplex - afterPointComplex )
		midpointCenterLength = midpointAfterPointLength * midpointAfterPointLength / midpointLocationLength
		radius = math.sqrt( midpointCenterLength * midpointCenterLength + midpointAfterPointLength * midpointAfterPointLength )
		centerComplex = midpointComplex + midpointMinusLocationComplex * midpointCenterLength / midpointLocationLength
		center = Vector3( centerComplex.real, centerComplex.imag, midpoint.z )
		afterCenterComplex = afterPointComplex - centerComplex
		beforeCenter = beforePoint - center
		angleDifference = euclidean.getAngleDifferenceByComplex( afterCenterComplex, beforeCenter.dropAxis() )
		self.addArc( angleDifference, afterPoint, beforeCenter, beforePoint, center )
		return afterPoint


class ArcPointSkein( ArcSegmentSkein ):
	"A class to arc point a skein of extrusions."
	def addArc( self, afterCenterDifferenceAngle, afterPoint, beforeCenterSegment, beforePoint, center ):
		"Add an arc point to the filleted skein."
		if afterCenterDifferenceAngle == 0.0:
			return
		afterPointMinusBefore = afterPoint - beforePoint
		centerMinusBefore = center - beforePoint
		firstWord = 'G3'
		if afterCenterDifferenceAngle < 0.0:
			firstWord = 'G2'
		centerMinusBeforeComplex = centerMinusBefore.dropAxis(2)
		if abs( centerMinusBeforeComplex ) <= 0.0:
			return
		deltaZ = abs( afterPointMinusBefore.z )
		radius = abs( centerMinusBefore )
		arcDistanceZ = complex( abs( afterCenterDifferenceAngle ) * radius, afterPointMinusBefore.z )
		distance = abs( arcDistanceZ )
		if distance <= 0.0:
			return
		line = self.distanceFeedRate.getFirstWordMovement( firstWord, afterPointMinusBefore ) + self.getRelativeCenter( centerMinusBeforeComplex )
		cornerFeedRate = self.getCornerFeedRate()
		if cornerFeedRate != None:
			line += ' F' + self.distanceFeedRate.getRounded( self.distanceFeedRate.getZLimitedFeedRate( deltaZ, distance, cornerFeedRate ) )
		self.distanceFeedRate.addLine(line)

	def getRelativeCenter( self, centerMinusBeforeComplex ):
		"Get the relative center."
		return ' I%s J%s' % ( self.distanceFeedRate.getRounded( centerMinusBeforeComplex.real ), self.distanceFeedRate.getRounded( centerMinusBeforeComplex.imag ) )


class ArcRadiusSkein( ArcPointSkein ):
	"A class to arc radius a skein of extrusions."
	def getRelativeCenter( self, centerMinusBeforeComplex ):
		"Get the relative center."
		radius = abs( centerMinusBeforeComplex )
		return ' R' + ( self.distanceFeedRate.getRounded(radius) )


class FilletRepository:
	"A class to handle the fillet settings."
	def __init__(self):
		"Set the default settings, execute title & settings fileName."
		skeinforge_profile.addListsToCraftTypeRepository('skeinforge_application.skeinforge_plugins.craft_plugins.fillet.html', self )
		self.fileNameInput = settings.FileNameInput().getFromFileName( fabmetheus_interpret.getGNUTranslatorGcodeFileTypeTuples(), 'Open File to be Filleted', self, '')
		self.openWikiManualHelpPage = settings.HelpPage().getOpenFromAbsolute('http://www.bitsfrombytes.com/wiki/index.php?title=Skeinforge_Fillet')
		self.activateFillet = settings.BooleanSetting().getFromValue('Activate Fillet', self, False )
		self.filletProcedureChoiceLabel = settings.LabelDisplay().getFromName('Fillet Procedure Choice: ', self )
		filletLatentStringVar = settings.LatentStringVar()
		self.arcPoint = settings.Radio().getFromRadio( filletLatentStringVar, 'Arc Point', self, False )
		self.arcRadius = settings.Radio().getFromRadio( filletLatentStringVar, 'Arc Radius', self, False )
		self.arcSegment = settings.Radio().getFromRadio( filletLatentStringVar, 'Arc Segment', self, False )
		self.bevel = settings.Radio().getFromRadio( filletLatentStringVar, 'Bevel', self, True )
		self.cornerFeedRateOverOperatingFeedRate = settings.FloatSpin().getFromValue( 0.8, 'Corner Feed Rate over Operating Feed Rate (ratio):', self, 1.2, 1.0 )
		self.filletRadiusOverPerimeterWidth = settings.FloatSpin().getFromValue( 0.25, 'Fillet Radius over Perimeter Width (ratio):', self, 0.65, 0.35 )
		self.reversalSlowdownDistanceOverPerimeterWidth = settings.FloatSpin().getFromValue( 0.3, 'Reversal Slowdown Distance over Perimeter Width (ratio):', self, 0.7, 0.5 )
		self.useIntermediateFeedRateInCorners = settings.BooleanSetting().getFromValue('Use Intermediate Feed Rate in Corners', self, True )
		self.executeTitle = 'Fillet'

	def execute(self):
		"Fillet button has been clicked."
		fileNames = skeinforge_polyfile.getFileOrDirectoryTypesUnmodifiedGcode( self.fileNameInput.value, fabmetheus_interpret.getImportPluginFileNames(), self.fileNameInput.wasCancelled )
		for fileName in fileNames:
			writeOutput(fileName)


def main():
	"Display the fillet dialog."
	if len( sys.argv ) > 1:
		writeOutput(' '.join( sys.argv[1 :] ) )
	else:
		settings.startMainLoopFromConstructor( getNewRepository() )

if __name__ == "__main__":
	main()
