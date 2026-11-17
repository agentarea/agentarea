package payment

import (
	"fmt"
	"math/big"
)

// rlpList is an RLP list; its items are []byte, *big.Int, uint64 or rlpList,
// encoded as pyrlp encodes bytes, ints (big-endian, no leading zeros, 0 is
// the empty string) and lists.
type rlpList []any

func rlpEncode(item any) []byte {
	switch v := item.(type) {
	case []byte:
		if len(v) == 1 && v[0] < 0x80 {
			return []byte{v[0]}
		}
		return append(rlpHeader(0x80, len(v)), v...)
	case *big.Int:
		if v.Sign() < 0 {
			panic("rlp: negative integer")
		}
		return rlpEncode(v.Bytes())
	case uint64:
		return rlpEncode(new(big.Int).SetUint64(v).Bytes())
	case rlpList:
		var body []byte
		for _, it := range v {
			body = append(body, rlpEncode(it)...)
		}
		return append(rlpHeader(0xc0, len(body)), body...)
	}
	panic(fmt.Sprintf("rlp: cannot encode %T", item))
}

func rlpHeader(offset byte, n int) []byte {
	if n < 56 {
		return []byte{offset + byte(n)}
	}
	size := big.NewInt(int64(n)).Bytes()
	return append([]byte{offset + 55 + byte(len(size))}, size...)
}
