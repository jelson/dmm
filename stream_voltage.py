#!/usr/bin/env python3

import argparse
import dmmlib

parser = argparse.ArgumentParser()
dmmlib.add_dmm_args(parser)
parser.add_argument('-r', '--range', type=float, default=10,
                    help='Voltage range in volts (default: 10)')
args = parser.parse_args()

receiver = dmmlib.make_receiver(args, field_name='voltage_V')
instr = dmmlib.Keysight34465A(host=args.dmm_host)

instr.configure_dc_voltage(voltage_range=args.range,
                           sample_rate_hz=args.sample_rate,
                           auto_zero=False)
instr.stream(receiver, args.sample_rate)
