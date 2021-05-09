import argparse
from time import sleep
from diode_ftp import FolderSender, FolderReceiver
import os
import asyncio
from logging import INFO, basicConfig

basicConfig(level=INFO)

def start_folder_sender():
	parser = argparse.ArgumentParser(description='Starts a folder sender')
	parser.add_argument('-f', '--folder', default=os.getcwd(), help='The folder to sync')
	parser.add_argument('-d', '--dest', default='127.0.0.1:8963', help='The destination host:port')
	parser.add_argument('-c', '--chunk-size', default=1400, type=int, help='The maximum size of each chunk')
	parser.add_argument('-l', '--limit', default=200000, type=int, help='The maxmimum bytes per second')
	parser.add_argument('-r', '--repeats', default=2, type=int, help='Number of times to duplicate each chunk')
	parser.add_argument('-i', '--interval', default=5, type=int, help='Seconds to wait between checking the folder for new files')
	args = parser.parse_args()
	send_host, send_port = args.dest.split(':')

	sender = FolderSender(args.folder, (send_host, int(send_port)),
		max_bytes_per_second=args.limit, transmit_repeats=args.repeats, chunk_size=args.chunk_size)
	
	while True:
		sender.perform_sync()
		sleep(args.interval)

def start_folder_receiver():
	parser = argparse.ArgumentParser(description='Starts a folder sender')
	parser.add_argument('-f', '--folder', default=os.getcwd(), help='The folder to sync')
	parser.add_argument('-k', '--keep-tars', default=False, action='store_true', help='Set flag to truncate files which are sent')
	parser.add_argument('-p', '--port', default=8963, help='port to listen to')
	args = parser.parse_args()

	def make_receiver():
		return FolderReceiver(args.folder, delete_tars=not args.keep_tars)
	
	while True:
		loop = asyncio.get_event_loop()
		t = loop.create_datagram_endpoint(make_receiver, local_addr=('0.0.0.0', args.port))
		loop.run_until_complete(t) # Server starts listening
		loop.run_forever()