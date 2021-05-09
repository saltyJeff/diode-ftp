from diode_ftp.header import hash_file
from diode_ftp.FolderSender import FolderSender
from diode_ftp.FolderReceiver import FolderReceiver
from pathlib import Path
from shutil import Error, copy2
from tests.common import *
import asyncio
import time

def create_send_rcv_folder(root: Path):
	send = root / 'send'
	rcv = root / 'rcv'
	send.mkdir()
	rcv.mkdir()
	print(send, rcv)
	return send, rcv

def do_sync_in_bkgd(send: Path, rcv: Path):
	port = get_available_port()
	sender = FolderSender(send, send_to=('127.0.0.1', port))
	receiver = FolderReceiver(rcv)

	def sender_thread():
		sender.perform_sync()
	def receiver_thread():
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		t = loop.create_datagram_endpoint(lambda: receiver, local_addr=('0.0.0.0', port))
		loop.run_until_complete(t)
		loop.run_forever()
	
	send_proc = threading.Thread(target=receiver_thread, daemon=True)
	rcv_proc = threading.Thread(target=sender_thread, daemon=True)

	send_proc.start()
	rcv_proc.start()

def test_folder_sync(tmp_path: Path):
	send, rcv = create_send_rcv_folder(tmp_path)
	copy2(PAYLOAD, send / 'payload.txt')
	copy2(BIG_FILE, send / 'big.bin')
	do_sync_in_bkgd(send, rcv)
	start = time.monotonic()
	while time.monotonic() - start < 60:
		# give it up to 60 seconds to sync
		try:
			assert hash_file(rcv / 'payload.txt') == PAYLOAD_HASH, "File hashes should be the same"
			assert hash_file(rcv / 'big.bin') == BIG_HASH, "File hashes should be the same"
			return
		except Exception as e:
			pass
			# print('Could not check hashes because of: ', e)
		
	assert False, "timeout for the folder sync to complete"

def test_diodeinclude(tmp_path: Path):
	send, rcv = create_send_rcv_folder(tmp_path)
	copy2(PAYLOAD, send / 'payload.txt')
	copy2(PAYLOAD, send / 'payload.md')
	# only send the markdown file
	(send / '.diodeinclude').write_text('*.md')
	
	do_sync_in_bkgd(send, rcv)
	start = time.monotonic()
	while time.monotonic() - start < 60:
		# give it up to 60 seconds to sync
		try:
			assert hash_file(rcv / 'payload.md') == PAYLOAD_HASH, "File hashes should be the same"
			assert not (rcv / 'payload.txt').exists(), "We should not send *.txt files"
			return
		except Exception as e:
			pass
			# print('Could not check hashes because of: ', e)
		
	assert False, "timeout for the folder sync to complete"