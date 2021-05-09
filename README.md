# Diode File Transfer Protocol
This library aims to implement a network fault-resistant file transfer protocol across a [data diode](https://en.wikipedia.org/wiki/Unidirectional_network)

Created for the UCLA BALBOA project, where data files need to be downlinked from a baloon (in the sky) to the ground, with nothing in between

# Overview
* We want to be able to send a file across a data diode, and re-assemble it on the other side
	- The file can be a variety of types (video, binary proprietary format, text)
* The physical layer is somewhat lossy, but does have link-layer error detection
* Network flow works only one way, so we can't use anything TCP-like
* The custom layer works at the UDP layer, so we must also use UDP
	- This means no in order or packet recieved guarantees
	- We do get a checksum to ensure the packet isn't too corrupted

# Protocol
## Sender-side
1. Split the original file into chunks of a user-defined size
2. At the start of each chunk of data, prepend the following header (big endian):
	- SHA1 of the entire original file data (20 bytes)
	- The offset of this chunk's data with respect to the original file data in bytes (8 bytes)
	- The index (0-indexed) of this chunk (4 bytes)
	- The total number of chunks (4 bytes)
	- **this comes out to a constant 36 bytes of overhead**
3. Send the chunk, with both its header and data

## Receiver-side
1. Recieve a chunk
2. Find the user-provided temporary path for the chunk's hash, `TMP_FILE`
3. Write in the chunk's data into `TMP_FILE` at the chunk's specified offset
4. Hash `TMP_FILE`, and return if `hash(TMP_FILE) == chunk_hash`

## WHY R U STILL USING SHA-1
We apply file hashes only to identify files, not as a security measure. We are only interested in hashes being distinct enough to prevent reasonable duplicates, and SHA1 has been enough to serve git well.

## Features
Overhead is given by `HEADER_SZ * # of Chunks`, or equivalently: `36 * ORIGINAL_SIZE / (CHUNK_SIZE - 36)`.

The number of chunks is saved as a `uint_32`, which can support up to 4-ish billion chunks. The max supported file size is dependent on your chunk size.

The user can specify the size of each chunk. For custom communications infrastructure like ours, this allows the user to ensure each chunk can fit within a link-layer frame

Chunks can be transmitted multiple times, for redundancy

A possible (unimplemented) duplicate resolution algorithm is below:
1. Use the hash to identify which file the chunk belongs to
2. Use the offset and size to read the existing data stored in the file:
	- If the file is new or the chunk has never been written:
		- Write the chunk into the correct position
	- If the CRC of the existing data is the same as the CRC of the chunk's data:
		- Drop the chunk, it's a duplicate
	- Else
		- Store the chunk in the `sus` set
3. Once you believe you've recieved a all the frames, substitute each possible candidate in the `sus` bin until the file and its hash match

Obviously, this algorithm will add `O(2^n)` complexity where `n = |sus|`.

Because of the nature of our network layer (UDP will kick any corrupted frames), the current implementation will just write any new chunks that come in

## Drawbacks
* This protocol doesn't take into consideration that the transmitted chunk has been corrupted or improperly tampered
* Relies on other layers to provide framing and error detection:
	- We will be transmitting using UDP (which has checksum) and a custom radio link-layer (which has forward error correction and provides framing)
* Can't guarantee correctness, but this is a limitation of the fact that data is unidirectional

## Usage
```python
from diode_ftp import FileChunker, FileReassembler, CHUNK_HEADER_SIZE

# on the transmit side
transmitFile = 'i_want_to_TX_this.txt'
chunker = FileChunker(transmitFile, chunk_size=1024)

with chunker.chunk_iterator() as chunk_it:
	for chunk in chunk_it:
		send(chunk) # replace with whatever your actual networking send() function is

# on the receive side
def get_file_by_hash(hash: bytes):
	return f'where_i_want_the_file_to_be/{hash.hex()}.reassemble'
reassembler = FileReassembler(get_file_by_hash)

for chunk in network_recieve(): # replace with however you're recieving the chunks
	reassembler.accept_chunk(chunk) # will return True if the file is completed by the new chunk
```

# Higher-Level folder synchronization
At a higher level, we can use the protocol to synchronize folders on the remote (sender) and local (receiver) targets.

## Sender-side
1. Every N seconds, perform a user-defined glob relative to `sync_folder` and get a list of `new_files`
	- In the provided implementation, this is done using the default Rsync algorithm
2. Tar `new_files` into a single file, and chunkify it
3. Send the chunks over the network

## Receiver-side
1. Receive the chunks and reassemble them as per the protocol above into a tar
2. If the file is complete:
	- Untar the file, relative to `sync_folder`

## Usage
We provide 2 high-level classes, `FolderSender` and `FolderReceiver`. Generate documentation to see how they are used and created.

You can also check the test folder to see how to set them up in different threads

# Other Notes
## Generating source code documentation:
You can generate source code docs with [pdoc3](https://pdoc3.github.io/pdoc/) (`pip install pdoc3`):
```
pdoc --html diode_ftp -o docs
```