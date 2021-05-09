from diode_ftp.header import HEADER_SIZE, hash_file, parse_header
from typing import Callable, Union
from os import PathLike

class FileReassembler():
	"""Reassembles a chunked file"""

	def __init__(self, get_file_by_hash: Callable[[bytes], PathLike]) -> None:
		"""Instantiates a new File Reassembler

		Args:
			get_file_by_hash (Callable[[bytes], PathLike]): A function which will return a file path for a given hash.
				The file will be opened in 'a+b' mode. You must ensure the parent director(ies) exist
		"""
		self.get_file_by_hash = get_file_by_hash
	def accept_chunk(self, chunk: Union[bytes, memoryview], check_for_complete=True):
		"""Accepts a chunk and writes it to the associated file
		Args:
			chunk (bytes): The chunk
			check_for_complete (bool, optional): Set to True 
				if you want the method to return True 
				if the file is completed by this chunk. Defaults to True.

		Raises:
			RuntimeError: The chunk is too small

		Returns:
			bool: Always False if check_for_complete is False.
				Otherwise, True if the file is completed by this chunk
		"""
		if len(chunk) < HEADER_SIZE:
			raise RuntimeError('Recieved a chunk without a header')
		# use memoryview so we don't allocate any new memory
		if isinstance(chunk, bytes):
			chunk = memoryview(chunk)
		header = parse_header(chunk[0:HEADER_SIZE])
		data = chunk[HEADER_SIZE:]
		path = self.get_file_by_hash(header.hash)

		# TODO: this code naively just writes whatever data it recieves. We can optimize layer
		with open(path, mode='a+b') as f:
			f.seek(header.offset)
			f.write(data)
		return check_for_complete and (hash_file(path) == header.hash)