import asyncio
from diode_ftp.FolderReceiver import FolderReceiver
from diode_ftp.header import hash_file
from diode_ftp.FolderSender import FolderSender
from pathlib import Path
import os
import threading
import logging

logging.basicConfig(level=logging.INFO)

PARENT = Path(__file__).parent
PAYLOAD = PARENT / 'payload.txt'
PAYLOAD_HASH = hash_file(PAYLOAD)
TEST_PORT_START = 8989

def create_big_file(path: os.PathLike, kilobytes: int):
	path = Path(path)
	path.touch()
	with open(path, 'ab') as file:
		for _ in range(kilobytes):
			contents = os.urandom(1024)
			file.write(contents)

def get_available_port():
	global TEST_PORT_START
	port = TEST_PORT_START
	TEST_PORT_START += 1
	return port

BIG_FILE = PARENT / '.tmp_big.bin'
if not BIG_FILE.exists():
	create_big_file(BIG_FILE, 10)
BIG_HASH = hash_file(BIG_FILE)