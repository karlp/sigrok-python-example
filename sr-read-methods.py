#!/usr/bin/env python3
"""
Grossly attempt to demonstrate how to run a sigrok acquisition loop
while still having your own main thread, and not having your thread
be a child of the sigrok main, but the other way around.

Intent is for allowing use of sigrok inside openhtf plugs
"""
import argparse
import logging
import queue
import signal
import threading
import time
logging.basicConfig(level=logging.DEBUG)

import sigrok.core as sr

DEFAULT_PORT = "/dev/serial/by-id/usb-Nuvoton_USB_Virtual_COM_001C213E0248-if00"

class Mine():
	def __init__(self, port, driver="korad-kaxxxxp"):
		self.context = sr.Context.create()
		logging.debug(f"Running with libsigrok {self.context.package_version} lib {self.context.lib_version}")
		self.context.log_level = sr.LogLevel.INFO
		d = self.context.drivers[driver] # TODO: check it found one
		d_opts = {sr.ConfigKey.CONN.identifier: port}
		devices = d.scan(**d_opts)
		self.device = devices[0] # TODO: check we found some?
		self.device.open() # TODO: check it did?
		self.session = self.context.create_session()
		self.session.add_device(self.device)
		self.latest = {}  # Careful with threaded access! ok for our use with single reader/writer, just for "fresh"
		logging.debug("Device %s %s (serial: %s) opened and added to session", self.device.vendor, self.device.model, self.device.serial_number())

	def srmain(self):
		logging.info("Starting sigrok session runner thread")
		self.putcount = 0
		def datafeed_in(dev, p):
			if p.type != sr.PacketType.ANALOG:
				return
			chan = p.payload.channels[0]
			self.latest[p.payload.mq] = p.payload.data[0][-1]
			#print(f"chan0 {chan.type}, {chan.name} value: {p.payload.data[0][-1]}, unit: {p.payload.unit}, mq: {p.payload.mq}")

		self.session.start()
		self.session.add_datafeed_callback(datafeed_in)
		self.session.run()
		logging.info("sr background thread exited, published %d data blobs", self.putcount)


	def start(self):
		self.sthread = threading.Thread(target=self.srmain)
		self.sthread.start()

	def stop(self):
		self.session.stop()
		self.sthread.join()
		self.device.close()


def read_object(port):
	"""
	Use an object that wraps up sigrok behind the scenes.
	Not claimed to be awesome, but at least works without exploding into
	too many pieces
	:param port:
	:return:
	"""
	me = Mine(port)
	me.start()
	try:
		while True:
			logging.info("Latest readings: %s", me.latest)
			time.sleep(1)
	except KeyboardInterrupt:
		logging.info("interrupted, stopping...")
	me.stop()


def read_on_demand(port):
	"""
	Don't even start an acquisition loop at all, just poll the device
	on a regular basis.  With this, you just get raw numbers back,
	not the "measured quantity objects, but hey, it's super simple!
	:param port:
	:return:
	"""
	context = sr.Context.create()
	print(f"Running with libsigrok {context.package_version} lib {context.lib_version}")
	context.log_level = sr.LogLevel.INFO

	driver = context.drivers["korad-kaxxxxp"]
	driver_options = {sr.ConfigKey.CONN.identifier: port}
	devices = driver.scan(**driver_options)
	device = devices[0]
	device.open()

	try:
		while True:
			v = device.config_get(sr.ConfigKey.VOLTAGE)
			i = device.config_get(sr.ConfigKey.CURRENT)
			print(f"Right now, voltage: {v} V, current: {i}")
			time.sleep(1)
	except KeyboardInterrupt:
		print("exiting...")
	device.close()


def read_threaded(port):
	"""
	Runs a sigrok acquisition loop in it's own thread so you can
	do your own thing while still getting data.
	:return:
	"""
	context = sr.Context.create()
	print(f"Running with libsigrok {context.package_version} lib {context.lib_version}")
	context.log_level = sr.LogLevel.INFO

	driver = context.drivers["korad-kaxxxxp"]
	driver_options = {sr.ConfigKey.CONN.identifier: port}
	devices = driver.scan(**driver_options)
	device = devices[0]
	device.open()

	myconfigs = [
		(sr.ConfigKey.VOLTAGE_TARGET, 11.5),
		(sr.ConfigKey.CURRENT_LIMIT, 0.5),
		(sr.ConfigKey.ENABLED, True),
	]
	for key, value in myconfigs:
		device.config_set(key, key.parse_string(str(value)))

	session = context.create_session()
	session.add_device(device)

	def datafeed_in(dev, p):
		if p.type != sr.PacketType.ANALOG:
			return
		chan = p.payload.channels[0]
		print(f"chan0 {chan.type}, {chan.name} value: {p.payload.data[0][-1]}, unit: {p.payload.unit}, mq: {p.payload.mq}")
	signal.signal(signal.SIGINT, lambda signum, frame: session.stop())

	def srthread():
		session.start()
		session.add_datafeed_callback(datafeed_in)
		session.run() # Blocking call
		logging.info("Finished srthread")
		device.close()

	stmain = threading.Thread(target=srthread)
	stmain.start()
	while True:
		time.sleep(1)
		logging.info("hoho, doing nothing in our main loop")
		if not session.is_running(): break
	stmain.join()
	logging.info("finished both now")


def read_naiive(port):
	"""
	Just step through the sigrok API piece by piece and start an acquisition loop
	Inspired by the https://github.com/martinling/sigrok-cli-python
	:return:
	"""
	context = sr.Context.create()
	print(f"Running with libsigrok {context.package_version} lib {context.lib_version}")
	context.log_level = sr.LogLevel.INFO

	driver = context.drivers["korad-kaxxxxp"]
	driver_options = {sr.ConfigKey.CONN.identifier: port}
	devices = driver.scan(**driver_options)
	device = devices[0]
	device.open()

	myconfigs = [
		(sr.ConfigKey.VOLTAGE_TARGET, 11.5),
		(sr.ConfigKey.CURRENT_LIMIT, 0.5),
		(sr.ConfigKey.ENABLED, True),
	]
	for key, value in myconfigs:
		device.config_set(key, key.parse_string(str(value)))

	session = context.create_session()
	session.add_device(device)
	session.start()

	# This will format nicely, with units and things.
	output = context.output_formats["analog"].create_output(device)
	def datafeed_in(dev, p):
		#print(f"type: {p.type}")
		if p.type != sr.PacketType.ANALOG:
			return
		chan = p.payload.channels[0]
		print(f"chan0 {chan.type}, {chan.name} value: {p.payload.data[0][-1]}, unit: {p.payload.unit}, mq: {p.payload.mq}")
	#print("data is", p.payload.data)
	#text = output.receive(p)
	#print(text, end='')

	session.add_datafeed_callback(datafeed_in)

	signal.signal(signal.SIGINT, lambda signum, frame: session.stop())
	session.run()
	device.close()


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument("--simple", help="Run simple naiive acquisition loop", action="store_true")
	parser.add_argument("--bg_thread", help="Run acquisition loop in a background thread", action="store_true")
	parser.add_argument("--on_demand", help="Don't run an acquisition loop at all, just poll on demand", action="store_true")
	parser.add_argument("--object", help="Like bg thread, but wrapped in an object", action="store_true")
	parser.add_argument("-d", "--device", help="Serial port connected to the power supply", default=DEFAULT_PORT)
	opts = parser.parse_args()
	if opts.simple:
		read_naiive(opts.device)
	elif opts.bg_thread:
		read_threaded(opts.device)
	elif opts.on_demand:
		read_on_demand(opts.device)
	elif opts.object:
		read_object(opts.device)
	else:
		# argparse choices are "neater" but the help is uglier :(
		print("ERROR: You must select one of the run methods!")
		parser.print_usage()
		parser.exit(1)
