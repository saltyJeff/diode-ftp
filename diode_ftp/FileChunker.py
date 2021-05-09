from os import PathLike
from os.path import getsize
from typing import Iterable, Iterator
from diode_ftp.header import HEADER_SIZE, create_header, hash_file, Header

class FileChunker(Iterable):
	"""Represents the chunking of a file"""

	def __init__(self, file_path: PathLike, chunk_size: int=1400) -> None:
		"""Creates a file chunker

		Args:
			file_path (PathLike): Path to the file you would like to chunk
			chunk_size (int, optional): The maximum size of each chunk (including the 48-byte header). Defaults to 1400, roughly the Ethernet-IPV4-UDP max packet size.
		"""
		assert chunk_size > HEADER_SIZE
		self.chunk_data_size = chunk_size - HEADER_SIZE
		self.total_chunks = ((getsize(file_path) + self.chunk_data_size - 1) // self.chunk_data_size)
		self.file_path = file_path
		self.hash = hash_file(file_path)
	def chunk_iterator(self):
		"""Gets the chunk iterator for the file

		Returns:
			Iterator[bytes]: An iterator object which will go through chunk by chunk
		"""
		return self.__iter__()
	def __iter__(self):
		return FileChunkIterator(self)

class FileChunkIterator(Iterator[bytes]):
	def __init__(self, owner: FileChunker) -> None:
		self.owner = owner
	def __enter__(self):
		self.file = open(self.owner.file_path, 'rb', buffering=self.owner.chunk_data_size)
		return self
	def __exit__(self, exception_type, exception_value, exception_traceback):
		self.file.close()
		self.file = None
	def __next__(self):
		assert self.file != None, "File Chunk Iterator can only be run within a `with` statement"
		offset = self.file.tell()
		file_data = self.file.read(self.owner.chunk_data_size)
		if len(file_data) == 0:
			raise StopIteration()
		return create_header(
			Header(self.owner.hash,
				offset,
				offset // self.owner.chunk_data_size,
				self.owner.total_chunks)) + file_data