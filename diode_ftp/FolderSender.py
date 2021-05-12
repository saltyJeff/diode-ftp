from os import PathLike
import os
from typing import Callable, Dict, Iterable, NamedTuple, List, Optional, Set, Tuple, Union
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
default_sender_log = getLogger('folder_sender')

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
		
		renamer_to_file = {
			lambda p: (self.root / p, str(p)): changed_files
		}
		tar_path, included = tarball_files(renamer_to_file)
		self.log.debug(f'Created new tarball: {tar_path}')
		chunker = self.get_chunker(tar_path)
		transmit_chunks(chunker, self.sock, self.send_to, self.max_bytes_per_sec, self.transmit_repeats, self.log)
		self.log.info(f'Transmitted tarball: {tar_path} (hash: {chunker.hash.hex()})')

		# do cleanup
		with self.shelf() as db:
			db['sent'] = included.union(sent_files)
		self.handle_sent(tar_path)

	def shelf(self):
		return shelve.open(str(self.root / '.sender_sync_data'))
	def get_chunker(self, file: Path):
		return FileChunker(file, chunk_size=self.chunk_size)
	def handle_sent(self, tarball: Path):
		self.log.debug(f'Deleting: {tarball}')
		os.unlink(tarball)

ResolveAbsoluteAndAliasFunc = Callable[[Path], Tuple[Union[str, Path], str]]
def tarball_files(resolver_to_file: Dict[ResolveAbsoluteAndAliasFunc, Iterable[FileMetadata]],
			tar_dir: Path=None):
	included: Set[FileMetadata] = set()
	with tempfile.NamedTemporaryFile('wb', suffix='.tar', delete=False, dir=tar_dir) as f:
		with tarfile.open(fileobj=f, mode='w', format=tarfile.GNU_FORMAT) as tarball:
			for resolver, files in resolver_to_file.items():
				for file in files:
					try:
						absolute_path, alias_name = resolver(file.path)
						tarball.add(absolute_path, arcname=alias_name)
						included.add(file)
					except OSError:
						pass
		f.close()
		return Path(f.name), included

def transmit_chunks(chunker: FileChunker, sock: socket.socket, send_to: Tuple[str, int], max_bytes_per_sec=0, num_repeats=2, log=default_sender_log):
	total_bytes = 0
	start_time = time.monotonic()
	for copy in range(0, num_repeats):
		log.info(f'Sending copy {copy+1}/{num_repeats}')
		with chunker.chunk_iterator() as chunks:
			for chunk_idx, chunk in enumerate(chunks):
				total_bytes += len(chunk)
				sock.sendto(chunk, send_to)
				if max_bytes_per_sec != 0:
					time.sleep(len(chunk) / max_bytes_per_sec)
				log.debug(f'Sent copy {copy+1}/{num_repeats} of chunk {chunk_idx}')
		total_time = time.monotonic() - start_time
		log.info(f'Sent {si_format(total_bytes, precision=0)}bytes in {total_time}s ({si_format(total_bytes / (total_time+0.0001))}bytes/s)')

def get_all_file_metadata(root: Path, rel_to_root=True, find_diodeinclude=True, ignore_hidden=True, follow_links=True):
	def file_to_metadata(file_path_str: str):
		file_path = Path(file_path_str)
		stat = file_path.stat()
		return FileMetadata(Path(file_path).relative_to(root) if rel_to_root else file_path.resolve(), stat.st_size, stat.st_mtime)
	
	metadata: Set[FileMetadata] = set()
	matcher = None
	if find_diodeinclude:
		diodeignore_path = root / '.diodeinclude'
		if diodeignore_path.exists():
			matcher = parse_gitignore(diodeignore_path, root)
	for dir_name, _, files in os.walk(root, followlinks=follow_links):
		if ignore_hidden:
			files = filter(lambda p: not p.startswith('.'), files)
		if matcher is not None:
			files = filter(lambda p: matcher(os.path.join(dir_name, p)), files)
		files_metadata = map(lambda p: file_to_metadata(os.path.join(dir_name, p)), files)
		metadata.update(files_metadata)
	return metadata