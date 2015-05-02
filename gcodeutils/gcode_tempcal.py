#!/usr/bin/env python
# encoding: utf-8
"""Add temperature gradient to gcode program to create unattended temprature calibration program"""
from __future__ import print_function
from __future__ import division

import argparse
import logging
import sys

__author__ = 'Olivier Jolly <olivier@pcedev.com>'

from gcoder import GCode  # pylint: disable=relative-import


class GCodeTempGradient(object):  # pylint: disable=too-many-instance-attributes
    """Alter gcode to inject temperature changes along Z"""

    ABSOLUTE_MIN_TEMPERATURE = 150
    ABSOLUTE_MAX_TEMPERATURE = 250

    def __init__(self, gcode, start_temp, end_temp, min_z_change, **kwargs):
        self.gcode = gcode
        self.start_temp = start_temp
        self.end_temp = end_temp
        self.min_z_change = min_z_change

        self.zmax = gcode.zmax
        self.zmin = None

        self.last_target_temperature = None
        self.current_z = None


    def generate_temperature_gcode(self, temperature):
        """Return a gcode line for the given temperature, under condition that the temperature
        is between the security absolute temperature bounds and that the temperature rounded
        to the nearest 0.1°C is different from the previous one (to avoid spurious gcode generation
        in vase mode)"""
        if self.ABSOLUTE_MIN_TEMPERATURE <= temperature <= self.ABSOLUTE_MAX_TEMPERATURE:
            # round the temperature to the nearest 0.1°C first
            rounded_temperature = "%.1f" % temperature

            return "M104 S{}".format(rounded_temperature)

        return ""

    def _parse_gcode(self):
        """parse gcode to detect Z bounds"""
        for layer_idx, layer in enumerate(self.gcode.all_layers):

            # don't parse layer without any instruction
            if layer:
                current_z = layer[0].current_z

                if current_z is not None:
                    logging.debug("layer #%d altitude is %.2fmm", layer_idx, current_z)

                # Keep the lowest Z which is above the minimum height (used to keep the slicer first layers
                # temperature for adhesion)
                if self.zmin is None and current_z is not None and current_z > self.min_z_change:
                    self.zmin = current_z

        # Make sure that the sliced model is high enough to be usable
        if self.zmin is None:
            raise RuntimeError("Height is too small to create temperature gradient (no layer found ?)")

        logging.info(
            "temperature gradient from %.1f°C, altitude %.2fmm to %.1f°C, altitude %.2fmm ", self.start_temp, self.zmin,
            self.end_temp, self.zmax)

        if self.zmin >= self.zmax:
            raise RuntimeError("Height is too small to create temperature gradient (all operation are below {}mm ?)",
                               self.min_z_change)


    def write(self, output_file=sys.stdout):
        """Write the modified GCode"""

        self._parse_gcode()

        # spit back the original GCode with temperature GCode injected accordingly to their Z
        for layer_idx, layer in enumerate(self.gcode.all_layers):

            if layer:
                self.current_z = layer[0].current_z

                if self.current_z and self.zmin <= self.current_z <= self.zmax:

                    raw_target_temp = self.get_temp_for_current_layer()
                    if raw_target_temp is not None:
                        target_temp = round(raw_target_temp, 1)

                        # don't generate temperature change if same as last layer
                        if target_temp != self.last_target_temperature:
                            self.last_target_temperature = target_temp

                            logging.debug("target temp for layer #%d (height %.2fmm) is %.1f°C", layer_idx,
                                          self.current_z, target_temp)
                            print(self.generate_temperature_gcode(target_temp), file=output_file)

                for line in layer:
                    print(line.raw, file=output_file)

    def get_temp_for_current_layer(self):
        """return the target temperature for the current Z (as found in self.current_z)"""
        raise NotImplementedError


class GCodeContinuousTempGradient(GCodeTempGradient):
    """Change continuously temperature. Only makes sense with precise and fast hotends."""

    def __init__(self, gcode, **kwargs):
        super(GCodeContinuousTempGradient, self).__init__(gcode, **kwargs)
        self.delta_temp_per_z = None


    def _parse_gcode(self):
        super(GCodeContinuousTempGradient, self)._parse_gcode()

        # precompute temperature change per Z unit
        self.delta_temp_per_z = (self.end_temp - self.start_temp) / (self.zmax - self.zmin)

    def get_temp_for_current_layer(self):
        return self.start_temp + self.delta_temp_per_z * (self.current_z - self.zmin)


class GCodeStepTempGradient(GCodeTempGradient):
    """Change temperature by a given number of steps"""

    def __init__(self, gcode, **kwargs):
        super(GCodeStepTempGradient, self).__init__(gcode, **kwargs)
        self.steps = kwargs['steps']

        self.step_end_temp = self.end_temp + (self.end_temp - self.start_temp) / self.steps
        self.steps += 1

    def get_temp_for_current_layer(self):
        progress = int(((self.current_z - self.zmin) / (self.zmax - self.zmin)) * self.steps) / self.steps
        return max(self.end_temp, self.start_temp + progress * (self.step_end_temp - self.start_temp))


def main():
    """command line entry point"""
    parser = argparse.ArgumentParser(description='Add temperature gradient to gcode program')
    parser.add_argument('start_temp', type=int)
    parser.add_argument('end_temp', type=int)
    parser.add_argument('infile', nargs='?', type=argparse.FileType('r'), default=sys.stdin)
    parser.add_argument('outfile', nargs='?', type=argparse.FileType('w'), default=sys.stdout)

    parser.add_argument('--min_z_change', type=float, default=0.1)

    temperature_control = parser.add_argument_group('temperature control')
    temperature_control.add_argument('--continuous', '-c', action='store_const', const=GCodeContinuousTempGradient,
                                     dest='gcode_grad_class', default=GCodeStepTempGradient)
    temperature_control.add_argument('--steps', '-s', default=10)

    parser.add_argument('--verbose', '-v', action='count', default=1)
    parser.add_argument('--quiet', '-q', action='count', default=0)

    args = parser.parse_args()

    # count verbose and quiet flags to determine logging level
    args.verbose -= args.quiet

    if args.verbose > 1:
        logging.root.setLevel(logging.DEBUG)
    elif args.verbose > 0:
        logging.root.setLevel(logging.INFO)

    logging.basicConfig(format="%(levelname)s:%(message)s")

    # read original GCode
    gcode = GCode(args.infile.readlines())

    # Alter and write back modified GCode
    temp_gradient = args.gcode_grad_class(gcode=gcode, **vars(args))
    temp_gradient.write(args.outfile)


if __name__ == "__main__":
    main()
