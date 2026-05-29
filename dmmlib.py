#!/usr/bin/env python3

import datetime
import numpy as np
import pyvisa
import socket
import time


class Keysight34465A:
    def __init__(self, host):
        rm = pyvisa.ResourceManager()
        self.instr = rm.open_resource(f'TCPIP::{host}::inst0::INSTR')
        self.instr.write('*RST')
        self.has_error()
        del self.instr.timeout
        print(self.query('*IDN?'))

    def has_error(self):
        errors = []
        while True:
            err = self.instr.query("SYST:ERR?")
            if 'No error' in err:
                if len(errors) == 0:
                    return None
                else:
                    return ";".join(errors)
            else:
                errors.append(err.strip())

    def write(self, q):
        self.instr.write(q)
        err = self.has_error()
        if err:
            raise Exception(err)

    def query(self, q):
        return self.instr.query(q).strip()

    def measure_current(self, current_range=None):
        """One-shot DC current measurement in amps; autoranges unless a range is given."""
        rng = 'AUTO' if current_range is None else current_range
        return float(self.query(f':MEAS:CURR:DC? {rng}'))

    def _aperture_from_sample_rate(self, sample_rate_hz):
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        return 1 / sample_rate_hz

    def _configure_dc(self, function, measurement_range=None, aperture=None,
                      sample_rate_hz=None, auto_zero=None):
        if aperture is not None and sample_rate_hz is not None:
            raise ValueError("set either aperture or sample_rate_hz, not both")

        rng = 'AUTO' if measurement_range is None else measurement_range
        self.write(f':CONF:{function}:DC {rng}')

        if sample_rate_hz is not None:
            aperture = self._aperture_from_sample_rate(sample_rate_hz)

        if aperture is not None:
            self.write(f':{function}:APER:ENAB ON')
            self.write(f':{function}:DC:APER {aperture}')

        if auto_zero is not None:
            auto_zero_setting = 'ON' if auto_zero else 'OFF'
            self.write(f':SENS:{function}:DC:ZERO:AUTO {auto_zero_setting}')

    def configure_dc_current(self, current_range=None, aperture=None,
                             sample_rate_hz=None, auto_zero=None):
        """Set up DC current measurement once; autoranges unless a range is
        given. If aperture (seconds) is set, each reading integrates over it.
        If sample_rate_hz is set, aperture is set to one sample period. Then
        call read() or stream() repeatedly without reconfiguring."""
        self._configure_dc('CURR', measurement_range=current_range,
                           aperture=aperture, sample_rate_hz=sample_rate_hz,
                           auto_zero=auto_zero)

    def configure_dc_voltage(self, voltage_range=None, aperture=None,
                             sample_rate_hz=None, auto_zero=None):
        """Set up DC voltage measurement once; autoranges unless a range is
        given. If aperture (seconds) is set, each reading integrates over it.
        If sample_rate_hz is set, aperture is set to one sample period. Then
        call read() or stream() repeatedly without reconfiguring."""
        self._configure_dc('VOLT', measurement_range=voltage_range,
                           aperture=aperture, sample_rate_hz=sample_rate_hz,
                           auto_zero=auto_zero)

    def read(self):
        """Trigger and return one reading in the configured function."""
        return float(self.query(':READ?'))

    def stream(self, receiver, sample_rate_hz):
        self.write(':TRIG:DELAY 0')
        self.write(':TRIG:COUN INF')
        self.write(':INIT:IMM')

        sec_per_sample = self._aperture_from_sample_rate(sample_rate_hz)
        prev = time.time()
        total_samples = 0
        while True:
            res = self.query(f':DATA:REMOVE? {sample_rate_hz}, WAIT')
            t = time.time() - prev
            prev = time.time()

            samples = res.split(',')
            num_samples = len(samples)

            times = np.arange(
                total_samples * sec_per_sample,
                (num_samples + total_samples) * sec_per_sample,
                sec_per_sample)

            float_samples = [float(s) for s in samples]
            receiver.receive(times, float_samples)
            total_samples += num_samples

            mean = np.mean(float_samples)
            print(f"{total_samples} ({total_samples*sec_per_sample:.1f}s) total: got {num_samples} samples in {t:.2f}s; {num_samples/t:.1f}Hz; mean {mean:.6g}")

        self.write(':ABOR')


class FileReceiver:
    def __init__(self, filename, field_name):
        self.out = open(filename, "w")
        self.out.write(f"# start time: {datetime.datetime.now()}\n")
        self.out.write(f"time,{field_name}\n")

    def receive(self, times, values):
        lines = [f"{t:.5f},{v}\n" for t, v in zip(times, values)]
        self.out.write("".join(lines))


class MultiReceiver:
    def __init__(self, receivers):
        self.receivers = receivers

    def receive(self, times, values):
        for receiver in self.receivers:
            receiver.receive(times, values)


class PlotJugglerReceiver:
    MAX_UDP_SIZE = 64000  # Stay well under 65535 limit

    def __init__(self, host, port, field_name, sample_rate_hz,
                 max_rate_hz=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect((host, port))
        self.field_name = field_name
        if max_rate_hz is None or max_rate_hz <= 0 or max_rate_hz >= sample_rate_hz:
            self.stride = 1
        else:
            self.stride = max(1, round(sample_rate_hz / max_rate_hz))

    def receive(self, times, values):
        def send_batch():
            msg = f'[{",".join(batch)}]'
            self.sock.send(msg.encode())

        batch = []
        batch_size = 2  # Account for opening '[' and closing ']'

        for t, v in zip(times[::self.stride], values[::self.stride]):
            record = f'{{"timestamp":{float(t)},"{self.field_name}":{v}}}'
            record_size = len(record) + 1  # +1 for comma separator

            if batch_size + record_size > self.MAX_UDP_SIZE and batch:
                # Send current batch and start new one
                send_batch()
                batch = []
                batch_size = 2

            batch.append(record)
            batch_size += record_size

        # Send any remaining records
        if batch:
            send_batch()


def add_dmm_args(parser):
    parser.add_argument('-d', '--dmm-host', type=str, default='dmm',
                        help='DMM hostname (default: dmm)')
    parser.add_argument('-o', '--outfile', help='File for output', type=str)
    parser.add_argument('-p', '--plotjuggler',
                        help='Stream to PlotJuggler via UDP (host:port)', type=str)
    parser.add_argument('--plotjuggler-rate', type=int, default=1000,
                        help='Maximum PlotJuggler preview rate in Hz; set 0 '
                             'for full rate (default: 1000)')
    parser.add_argument('-s', '--sample-rate', type=int, default=5000,
                        help='Sample rate in Hz (default: 5000)')


def make_receiver(args, field_name):
    if not args.outfile and not args.plotjuggler:
        raise SystemExit("error: at least one of --outfile or --plotjuggler is required")

    receivers = []
    if args.outfile:
        receivers.append(FileReceiver(args.outfile, field_name))
    if args.plotjuggler:
        host, port = args.plotjuggler.rsplit(':', 1)
        receivers.append(PlotJugglerReceiver(
            host, int(port), field_name,
            sample_rate_hz=args.sample_rate,
            max_rate_hz=args.plotjuggler_rate))

    if len(receivers) == 1:
        return receivers[0]
    return MultiReceiver(receivers)
