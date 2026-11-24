package payment

import (
	"bytes"
	"encoding/hex"
	"math/big"
	"strings"
	"testing"

	"github.com/decred/dcrd/dcrec/secp256k1/v4/ecdsa"
)

func mustHex(t *testing.T, s string) []byte {
	t.Helper()
	b, err := hex.DecodeString(strings.ReplaceAll(strip0x(s), " ", ""))
	if err != nil {
		t.Fatalf("bad hex %q: %v", s, err)
	}
	return b
}

// recoverAddress recovers the signer of an r || s || v signature.
func recoverAddress(t *testing.T, sig, hash []byte) string {
	t.Helper()
	if len(sig) != 65 || (sig[64] != 27 && sig[64] != 28) {
		t.Fatalf("signature is not r||s||v with v in {27,28}: %x", sig)
	}
	compact := append([]byte{sig[64]}, sig[:64]...)
	pub, _, err := ecdsa.RecoverCompact(compact, hash)
	if err != nil {
		t.Fatalf("recover: %v", err)
	}
	return checksumAddress(keccak256(pub.SerializeUncompressed()[1:])[12:])
}

func TestChecksumAddressEIP55(t *testing.T) {
	for _, want := range []string{
		"0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
		"0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
		"0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
		"0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
	} {
		addr, err := parseAddress(strings.ToLower(want))
		if err != nil {
			t.Fatal(err)
		}
		if got := checksumAddress(addr); got != want {
			t.Errorf("checksum %s, want %s", got, want)
		}
	}
}

func TestKeyAddress(t *testing.T) {
	for key, want := range map[string]string{
		"0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318": "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23",
		"4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318":   "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23",
		hex.EncodeToString(keccak256([]byte("cow"))):                         "0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826",
	} {
		k, err := parseEVMKey(key)
		if err != nil {
			t.Fatal(err)
		}
		if got := k.checksumAddress(); got != want {
			t.Errorf("address of %s = %s, want %s", key, got, want)
		}
	}
	for _, bad := range []string{"", "0x12", strings.Repeat("00", 32), strings.Repeat("ff", 32), "zz" + strings.Repeat("00", 31)} {
		if _, err := parseEVMKey(bad); err == nil {
			t.Errorf("key %q accepted", bad)
		}
	}
}

// The EIP-712 specification's Mail example: digest and signature for the
// private key keccak256("cow").
func TestEIP712MailExample(t *testing.T) {
	types := map[string][]typedField{
		"Person": {{"name", "string"}, {"wallet", "address"}},
		"Mail":   {{"from", "Person"}, {"to", "Person"}, {"contents", "string"}},
	}
	td := typedData{
		Types:       types,
		PrimaryType: "Mail",
		Domain: map[string]any{
			"name": "Ether Mail", "version": "1", "chainId": big.NewInt(1),
			"verifyingContract": "0xCcCCccccCCCCcCCCCCCcCcCccCcCCCcCcccccccC",
		},
		Message: map[string]any{
			"from":     map[string]any{"name": "Cow", "wallet": "0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826"},
			"to":       map[string]any{"name": "Bob", "wallet": "0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB"},
			"contents": "Hello, Bob!",
		},
	}
	if got := encodeType("Mail", types); got != "Mail(Person from,Person to,string contents)Person(string name,address wallet)" {
		t.Errorf("encodeType = %s", got)
	}
	if got := hex.EncodeToString(keccak256([]byte(encodeType("Mail", types)))); got != "a0cedeb2dc280ba39b857546d74f5549c3a1d7bdc2dd96bf881f76108e23dac2" {
		t.Errorf("typeHash = %s", got)
	}
	withDomain := map[string][]typedField{"EIP712Domain": domainFields(td.Domain)}
	domainHash, err := hashStruct("EIP712Domain", withDomain, td.Domain)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(domainHash); got != "f2cee375fa42b42143804025fc449deafd50cc031ca257e0b194a650a912090f" {
		t.Errorf("domain separator = %s", got)
	}
	messageHash, err := hashStruct("Mail", types, td.Message)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(messageHash); got != "c52c0ee5d84264471806290a3f2c4cecfc5490626bf912d01f240d7a274b371e" {
		t.Errorf("hashStruct(message) = %s", got)
	}
	digest, err := td.digest()
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(digest); got != "be609aee343fb3c4b28e1df9e632fca64fcfaede20f02e86244efddf30957bd2" {
		t.Fatalf("digest = %s", got)
	}
	key, err := parseEVMKey(hex.EncodeToString(keccak256([]byte("cow"))))
	if err != nil {
		t.Fatal(err)
	}
	sig := key.sign(digest)
	want := mustHex(t, "4355c47d63924e8a72e509b65029052eb6c299d53a04e167c5775fd466751c9d"+
		"07299936d304c153f6443dfa05f40ff007d72911b6f72307f996231605b91562"+"1c")
	if !bytes.Equal(sig, want) {
		t.Errorf("signature = %x\nwant        %x", sig, want)
	}
	if got := recoverAddress(t, sig, digest); got != "0xCD2a3d9F938E13CD947Ec05AbC7FE734Df8DD826" {
		t.Errorf("recovered %s", got)
	}
}

func TestTransferWithAuthorizationTypeHash(t *testing.T) {
	types := map[string][]typedField{"TransferWithAuthorization": {
		{"from", "address"}, {"to", "address"}, {"value", "uint256"},
		{"validAfter", "uint256"}, {"validBefore", "uint256"}, {"nonce", "bytes32"},
	}}
	got := hex.EncodeToString(keccak256([]byte(encodeType("TransferWithAuthorization", types))))
	if got != "7c7c6cdb67a18743f49ec6fa9b35f50d52ed05cbed4cc592e13b44501c1a2267" {
		t.Errorf("TRANSFER_WITH_AUTHORIZATION_TYPEHASH = %s", got)
	}
}

// Vectors from the Ethereum RLP specification.
func TestRLPVectors(t *testing.T) {
	lorem := []byte("Lorem ipsum dolor sit amet, consectetur adipisicing elit")
	for name, c := range map[string]struct {
		item any
		want string
	}{
		"dog":         {[]byte("dog"), "83646f67"},
		"cat dog":     {rlpList{[]byte("cat"), []byte("dog")}, "c88363617483646f67"},
		"empty":       {[]byte{}, "80"},
		"empty list":  {rlpList{}, "c0"},
		"zero":        {big.NewInt(0), "80"},
		"0x00 byte":   {[]byte{0}, "00"},
		"15":          {uint64(15), "0f"},
		"1024":        {big.NewInt(1024), "820400"},
		"set theory":  {rlpList{rlpList{}, rlpList{rlpList{}}, rlpList{rlpList{}, rlpList{rlpList{}}}}, "c7c0c1c0c3c0c1c0"},
		"long string": {lorem, "b838" + hex.EncodeToString(lorem)},
	} {
		if got := hex.EncodeToString(rlpEncode(c.item)); got != c.want {
			t.Errorf("%s: %s, want %s", name, got, c.want)
		}
	}
}
