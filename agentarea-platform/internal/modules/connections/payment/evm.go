package payment

import (
	"encoding/hex"
	"errors"
	"fmt"
	"strings"

	"github.com/decred/dcrd/dcrec/secp256k1/v4"
	"github.com/decred/dcrd/dcrec/secp256k1/v4/ecdsa"
	"golang.org/x/crypto/sha3"
)

func keccak256(parts ...[]byte) []byte {
	h := sha3.NewLegacyKeccak256()
	for _, p := range parts {
		h.Write(p)
	}
	return h.Sum(nil)
}

// evmKey is a secp256k1 private key read as eth_account's Account.from_key
// reads one: 32 bytes of hex, 0x-prefixed or not.
type evmKey struct {
	priv    *secp256k1.PrivateKey
	address [20]byte
}

func parseEVMKey(text string) (evmKey, error) {
	raw, err := hex.DecodeString(strip0x(strings.TrimSpace(text)))
	if err != nil || len(raw) != 32 {
		return evmKey{}, errors.New("the wallet key is not a 32-byte hex secp256k1 key")
	}
	var scalar secp256k1.ModNScalar
	if overflow := scalar.SetByteSlice(raw); overflow || scalar.IsZero() {
		return evmKey{}, errors.New("the wallet key is out of the secp256k1 range")
	}
	priv := secp256k1.NewPrivateKey(&scalar)
	k := evmKey{priv: priv}
	copy(k.address[:], keccak256(priv.PubKey().SerializeUncompressed()[1:])[12:])
	return k, nil
}

func (k evmKey) checksumAddress() string { return checksumAddress(k.address[:]) }

// sign returns r || s || v with v = 27 or 28 and a low s, as eth_account's
// unsafe_sign_hash does.
func (k evmKey) sign(hash []byte) []byte {
	compact := ecdsa.SignCompact(k.priv, hash, false)
	out := make([]byte, 65)
	copy(out, compact[1:])
	out[64] = compact[0]
	return out
}

// checksumAddress is EIP-55.
func checksumAddress(addr []byte) string {
	lower := hex.EncodeToString(addr)
	sum := keccak256([]byte(lower))
	var b strings.Builder
	b.WriteString("0x")
	for i, c := range lower {
		nibble := sum[i/2]
		if i%2 == 0 {
			nibble >>= 4
		}
		if c >= 'a' && nibble&0x0f >= 8 {
			b.WriteRune(c - 32)
		} else {
			b.WriteRune(c)
		}
	}
	return b.String()
}

func strip0x(s string) string {
	if len(s) >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X') {
		return s[2:]
	}
	return s
}

// parseAddress reads a 20-byte hex address, 0x-prefixed or not, any case.
func parseAddress(s string) ([]byte, error) {
	raw, err := hex.DecodeString(strip0x(s))
	if err != nil || len(raw) != 20 {
		return nil, fmt.Errorf("%q is not a 20-byte hex address", s)
	}
	return raw, nil
}
