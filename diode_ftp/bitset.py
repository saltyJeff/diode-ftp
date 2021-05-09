class bitset():
	def __init__(self, len: int) -> None:
		self.len = len
		self.bytes = bytearray(calc_bitset_length(len))
		self.zeros = 0
	def __getitem__(self, key: int):
		the_byte = self.bytes[key // 8]
		return (the_byte & (1 << (key % 8))) != 0
	def __setitem__(self, key: int, value: bool):
		original_value = self[key]
		if value:				
			self.bytes[key // 8] |= 1 << (key % 8)
		else:
			self.bytes[key // 8] &= ~(1 << (key % 8))
		if original_value == False and value == True:
			self.zeros += 1
		elif original_value == True and value == False:
			self.zeros -= 1
	def __len__(self):
		return self.zeros

def calc_bitset_length(len: int):
	return (len + 7) // 8