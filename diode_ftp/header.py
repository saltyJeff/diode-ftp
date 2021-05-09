from os import PathLike
import hashlib
import struct
from typing import NamedTuple, Union

HEADER_FMT = '!20sQII'
HEADER_STRUCT = struct.Struct(HEADER_FMT)
HEADER_SIZE = HEADER_STRUCT.size

Header = NamedTuple('DiodeFTPHeader', [
	('hash', bytes),
	('offset', int),
	('index', int),
	('total', int)])

def create_header(header: Header):
	return HEADER_STRUCT.pack(header.hash, header.offset, header.index, header.total)

def parse_header(header: bytes):
	hash, offset, index, total = HEADER_STRUCT.unpack(header)
	return Header(hash, offset, index, total)

def hash_file(path: Union[PathLike, str]):
	"""hashes a file

	Args:
		path (PathLike): The file to hash

	Returns:
		bytes: the hash of the file
	"""
	# see: https://stackoverflow.com/questions/22058048/hashing-a-file-in-python
	BUF_SIZE = 8 * 1024
	sha1 = hashlib.sha1()
	with open(path, 'rb') as f:
		while True:
			data = f.read(BUF_SIZE)
			if not data:
				break
			sha1.update(data)
	return sha1.digest()