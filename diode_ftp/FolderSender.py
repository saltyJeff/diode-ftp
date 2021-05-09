from os import PathLike
import os
from typing import Callable, Iterable, NamedTuple, List, Optional, Set, Tuple
from pathlib import Path
import socket
from glob import iglob
import tarfile
import tempfile
from diode_ftp.FileChunker import FileChunker
import time
from logging import getLogger
import shelve
from gitignore_parser.gitignore_parser import parse_gitignore
from si_prefix import si_format

FileMetadata = NamedTuple('FileMetadata', [('path', Path), ('size', int), ('mtime', float)])

class FolderSender():
	"""Synchronizes a folder on the transmission side"""
	def __init__(self, folder: PathLike,
			send_to: Tuple[str, int], transmit_socket: Optional[socket.socket] = None,
			chunk_size = 1400,
			max_bytes_per_second = 20000, transmit_repeats=2) -> None:
		"""Create a new Folder Sender.

		In the folder, we will automatically create a python shelf named .sender_sync_data

		Args:
			folder (PathLike): The folder you want to sync
			send_to (Tuple[str, int]): The IP address, Port that you want to sync to
			transmit_socket (Optional[socket.socket], optional): The socket to use for transmission.
				If you have an existing socket you want to use, pass it here.
				Otherwise, leave it to None to custom create a new socket. Defaults to None.
			chunk_size (int, optional): The maximum size for each chunk. Try to fit it in your MTU. Defaults to 1400.
			max_bytes_per_second (int, optional): Bandwidth limit. Set it to 0 for unlimited bandwidth. Defaults to 20000.
			transmit_repeats (int, optional): Number of times to retransmit each chunk. Defaults to 2.

		Raises:
			ValueError: Raises if the path to sync doesn't exist
		"""
		self.root = Path(folder).resolve()
		if not self.root.exists() or not self.root.is_dir():
			raise ValueError("The sync folder doesn't exist or is not a directory!")
		self.send_to = send_to
		if transmit_socket is None:
			self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		else:
			self.sock = transmit_socket
		self.chunk_size = chunk_size
		self.max_bytes_per_sec = max_bytes_per_second
		self.transmit_repeats = transmit_repeats
		self.log = getLogger(str(folder))

		diodeinclude_path = self.root / '.diodeinclude'
		if diodeinclude_path.exists():
			self.log.warning('A .diodeinclude file was found in the directory, will on send files matched by the include')
		self.log.warning(f'Network parameters: Chunk size of {chunk_size} bytes @ {si_format(max_bytes_per_second, precision=0)}bytes/s')
	
	def perform_sync(self):
		"""You may want to override this method if you would like to add intermediate steps
			For example, you may want to GZIP all the files before sending them.
		"""
		all_metadata = get_all_file_metadata(self.root)
		with self.shelf() as db:
			sent_files: Set[FileMetadata] = db.get('sent', set())
		# new files are detected rsync style:
		# we do a comparison of the previous 'sent' set and the new set of file metdata
		# any changes in mtime, path, or file size will trigger a retransmission
		changed_files = all_metadata - sent_files
		if len(changed_files) == 0:
			self.log.debug('no new files found')
			return
		self.log.info(f'Found {len(changed_files)} changed files')
		self.log.debug(f'Changed files:  {changed_files}')
		tar_path, included = self.tarball_files(changed_files)
		self.log.debug(f'Created new tarball: {tar_path}')
		chunker = self.get_chunker(tar_path)
		self.transmit_chunks(chunker)
		self.log.info(f'Transmitted tarball: {tar_path} (hash: {chunker.hash.hex()})')

		# do cleanup
		with self.shelf() as db:
			db['sent'] = included.union(sent_files)
		self.handle_sent(tar_path)

	def shelf(self):
		return shelve.open(str(self.root / '.sender_sync_data'))
	def tarball_files(self, files: Iterable[FileMetadata]):
		included: Set[FileMetadata] = set()
		with tempfile.NamedTemporaryFile('wb', suffix='.tar', delete=False, dir=self.root) as f:
			with tarfile.open(fileobj=f, mode='w', format=tarfile.GNU_FORMAT) as tarball:
				for file in files:
					try:
						tarball.add(self.root / file.path, arcname=str(file.path))
						included.add(file)
					except OSError:
						pass
			f.close()
			return Path(f.name), included
	def get_chunker(self, file: Path):
		return FileChunker(file, chunk_size=self.chunk_size)
	def transmit_chunks(self, chunker: FileChunker):
		total_bytes = 0
		start_time = time.monotonic()
		for copy in range(0, self.transmit_repeats):
			self.log.info(f'Sending copy {copy+1}/{self.transmit_repeats}')
			with chunker.chunk_iterator() as chunks:
				for chunk_idx, chunk in enumerate(chunks):
					total_bytes += len(chunk)
					self.sock.sendto(chunk, self.send_to)
					if self.max_bytes_per_sec != 0:
						time.sleep(len(chunk) / self.max_bytes_per_sec)
					self.log.debug(f'Sent copy {copy+1}/{self.transmit_repeats} of chunk {chunk_idx}')
			total_time = time.monotonic() - start_time
			self.log.info(f'Sent {si_format(total_bytes, precision=0)}bytes in {total_time}s ({si_format(total_bytes / (total_time+0.0001))}bytes/s)')
	def handle_sent(self, tarball: Path):
		self.log.debug(f'Deleting: {tarball}')
		os.unlink(tarball)

def get_all_file_metadata(root: Path, find_diodeinclude=True, ignore_hidden=True):
	"""Constructs a set of all the FileMetadata in a path

	Args:
		root (Path): The folder to generate a FileMetdata set for
		find_diodeinclude (bool, optional): Checks for the existence of a .diodeinclude.
			A .diodeinclude is basically a gitignore file, except that it specifies which files to sync.
			Defaults to True.
		ignore_hidden (bool, optional): Ignore files starting with '.' . Defaults to True.

	Returns:
		Set[FileMetadata]: The set of all filemetadata in the directory
	"""
	all_entries = root.iterdir()
	all_files = filter(lambda p: p.is_file(), all_entries)
	if ignore_hidden:
		all_files = filter(lambda p: not p.stem.startswith('.'), all_entries)
	if find_diodeinclude:
		diodeignore_path = root / '.diodeinclude'
		if diodeignore_path.exists():
			matcher = parse_gitignore(diodeignore_path, root)
			all_files = filter(matcher, all_entries)
	def file_to_metadata(file: Path):
		stat = file.stat()
		return FileMetadata(file.relative_to(root), stat.st_size, stat.st_mtime)
	all_metadata = map(file_to_metadata, all_files)
	return set(all_metadata)