#!/usr/bin/env python3

import argparse
import datetime

import dmmlib

parser = argparse.ArgumentParser()
dmmlib.add_dmm_args(parser)
args = parser.parse_args()

now = datetime.datetime.now()
instr = dmmlib.Keysight34465A(host=args.dmm_host)
instr.write(f':SYST:DATE {now.year},{now.month},{now.day}')
instr.write(f':SYST:TIME {now.hour},{now.minute},{now.second}')
