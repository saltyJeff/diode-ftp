from tests.common import *
from diode_ftp.header import hash_file
from diode_ftp import FileChunker, FileReassembler, HEADER_SIZE
from pathlib import Path
import random

def test_chunker(tmp_path: Path):
	chunker = FileChunker(PAYLOAD, chunk_size=8*1024)
	reassembled = tmp_path / 'payload_reassembled.txt'
	def get_file_by_hash(hash: bytes):
		return reassembled
	
	reassembler = FileReassembler(get_file_by_hash)
	with chunker.chunk_iterator() as chunk_it:
		chunks = list(chunk_it)
		for i, chunk in enumerate(chunks):
			# should only return True at the end
			assert reassembler.accept_chunk(chunk) == (i == len(chunks)-1)
	
	assert hash_file(PAYLOAD) == hash_file(reassembled), "File hashes should be the same"

def test_wonky_network(tmp_path: Path):
	chunker = FileChunker(PAYLOAD, chunk_size=16*1024)
	reassembled = tmp_path / 'payload_reassembled.txt'
	def get_file_by_hash(hash: bytes):
		return reassembled
	
	reassembler = FileReassembler(get_file_by_hash)

	# we're gonna test our "reassemble out-of-order with some lost packet theory"
	with chunker.chunk_iterator() as chunk_it:
		chunks = list(chunk_it)
		# duplicate chunks 3 times to stimulate redundancy
		transmit = chunks + chunks + chunks
		# random-sort to stimulate out-of-orderness
		random.shuffle(transmit)
		# remove the 1st chunk
		transmit = transmit[1:]

		# send it into our reassembler
		for chunk in chunks:
			reassembler.accept_chunk(chunk)
	
	assert hash_file(PAYLOAD) == hash_file(reassembled), "File hashes should be the same"

import os
def test_large_file(tmp_path: Path):
	chunker = FileChunker(BIG_FILE)
	copy = tmp_path / 'big.bin'
	def get_file_by_hash(hash: bytes):
		return copy
	
	reassembler = FileReassembler(get_file_by_hash)
	print('Test file created... beginning test')
	with chunker.chunk_iterator() as chunk_it:
		for i,chunk in enumerate(chunk_it):
			if i % 100 == 0:
				print(f'Sent {i} chunks')
			reassembler.accept_chunk(chunk, check_for_complete=False)
	assert BIG_HASH == hash_file(copy), "File hashes should be the same"