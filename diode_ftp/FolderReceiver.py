from diode_ftp.bitset import bitset
from os import PathLike
import os
from typing import Set, Tuple, Union
from pathlib import Path
import tarfile
import asyncio
from diode_ftp.header import HEADER_SIZE, Header, hash_file, parse_header
from logging import getLogger
import shelve
from threading import Thread
from queue import SimpleQueue

class FolderReceiver(asyncio.DatagramProtocol):
	"""Synchronizes a folder on the reception side.
		Uses Asyncio to reduce idle resource usage"""
	def __init__(self, folder: PathLike,
			delete_tars: bool = True) -> None:
		"""Creates a Folder Receiver.
		Unlike FolderSender, this is implemented as an asyncio protocol.
		You will need to use asyncio methods to set your socket and port.

		In the folder, we will automatically create a python shelf named .receiver_sync_data

		Args:
			folder (PathLike): The folder you want to sync to
			delete_tars (bool, optional): Deletes tars after they have completed. Defaults to True.

		Raises:
			ValueError: The folder to sync to doesn't exist
		"""
		super().__init__()
		self.root = Path(folder).resolve()
		if not self.root.exists():
			raise ValueError("The sync folder doesn't exist!")
		self.delete_tars = delete_tars
		self.log = getLogger(str(folder))
		self.queue: SimpleQueue[memoryview] = SimpleQueue()
		self.worker = FolderReceiverWorker(self)
		self.worker.start()
	def connection_made(self, transport) -> None:
		self.transport = transport
	def shelf(self):
		return shelve.open(str(self.root / '.receiver_sync_data'))
	def datagram_received(self, frame: bytes, addr: Tuple[str, int]) -> None:
		if(len(frame) < HEADER_SIZE):
			self.log.warn(f'Received a too-small frame from {addr}')
			return
		frame_data = memoryview(frame)
		self.queue.put(frame_data)
	def get_tar_path(self, header: Header):
		return self.root / f'{header.hash.hex()}.tar'


class FolderReceiverWorker(Thread):
	def __init__(self, owner: FolderReceiver) -> None:
		super().__init__()
		self.owner = owner
		self.daemon = True
	def connection_made(self, transport) -> None:
		self.transport = transport
	def run(self) -> None:
		# to reduce overhead of processing already-completed files, we cache the hashes of
		# already done files in known_complete
		known_complete: Set[bytes] = set()
		while frame_data := self.owner.queue.get():
			# this is the critical loop. Any cool ideas u got to reduce this execution time goes here
			# TODO: speed up critical loop
			header = parse_header(frame_data[0:HEADER_SIZE])
			chunk_data = frame_data[HEADER_SIZE:]
			file_complete = False

			# now we check the known_complete set to check if the file is complete with 0 filesystem access
			if header.hash in known_complete:
				continue

			with self.owner.shelf() as db:
				# If a hash yields "true", then the file with that hash is complete.
				# Else, it yields a set of the indicies already received
				chunk_set: Union[bool, bitset] = db.get(header.hash.hex(), bitset(header.total))
				if isinstance(chunk_set, bool):
					# add to cache. We want to restrict the size of known_complete to not run out of ram
					if len(known_complete) > 10:
						known_complete = set([header.hash])
					else:
						known_complete.add(header.hash)
					self.owner.log.debug('Received a chunk for a file we already completed')
					continue
				if chunk_set[header.index]:
					self.owner.log.debug('Received a chunk that we already have')
					continue
				tarball_path = self.owner.get_tar_path(header)
				self.write_chunk(header, chunk_data, tarball_path)
				chunk_set[header.index] = True
				num_chunks = len(chunk_set)
				if num_chunks == header.total:
					db[header.hash.hex()] = True
					file_complete = True
				else:
					db[header.hash.hex()] = chunk_set
			if not file_complete:
				pct_prev = int(100 * (num_chunks - 1) / header.total) if num_chunks > 0 else 0
				pct_complete = int(100 * num_chunks / header.total)
				if pct_prev // 10 != pct_complete // 10:
					self.owner.log.info(f'Received {pct_complete}% of {header.hash.hex()}')
				self.owner.log.debug(f'Received {num_chunks}/{header.total} total chunks for {header.hash.hex()}')
				continue
			self.owner.log.info(f'{header.hash.hex()} Complete')
			self.extract_tarball(tarball_path)
			self.owner.log.info(f'Extracted tarball {str(tarball_path)}')
			self.handle_received(tarball_path)
	def write_chunk(self, header: Header, data: memoryview, file: Path):
		with open(str(file), mode='a+b') as f:
			f.seek(header.offset)
			f.write(data)
	def extract_tarball(self, tar_file: Path, validate_hash=True):
		if validate_hash:
			file_hash = hash_file(tar_file).hex()
			expected_hash = tar_file.stem
			if file_hash != expected_hash:
				self.owner.log.warn(f'TARBALL HAS ALL REQUIRED CHUNKS, BUT HASHES DO NOT MATCH! (expect {tar_file} to hash to {file_hash})')
		tarball = tarfile.open(tar_file, format=tarfile.GNU_FORMAT)
		tarball.extractall(self.owner.root)
		tarball.close()
	def handle_received(self, tarball: Path):
		if self.owner.delete_tars:
			os.unlink(tarball)