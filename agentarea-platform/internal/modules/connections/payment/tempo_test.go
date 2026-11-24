package payment

import (
	"bytes"
	"encoding/hex"
	"math/big"
	"strings"
	"testing"
)

// The expected bytes below are assembled by hand from pytempo's
// TempoTransaction field lists (models.py _signing_hash_sender, encode) and
// pympp's encode_fee_payer_envelope, field by field, with RLP headers
// counted by hand; only the signature comes from the code under test, and
// it must recover to the sender over the hand-assembled signing preimage.

const (
	vecCurrency  = "20c0000000000000000000000000000000000000"
	vecRecipient = "1111111111111111111111111111111111111111"
	vecTransfer  = "a9059cbb" + "000000000000000000000000" + vecRecipient +
		"0000000000000000000000000000000000000000000000000000000000002710"
	// chain 4217, priority fee 1, max fee 1, gas 1_000_000, one call to the
	// currency with value 0 and the transfer calldata, no access list.
	vecHead = "821079" + "01" + "01" + "830f4240" +
		"f85e" + "f85c" + "94" + vecCurrency + "80" + "b844" + vecTransfer +
		"c0"
)

func cowKey(t *testing.T) evmKey {
	t.Helper()
	k, err := parseEVMKey(hex.EncodeToString(keccak256([]byte("cow"))))
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func vectorTx(t *testing.T) tempoTx {
	t.Helper()
	currency := mustHex(t, vecCurrency)
	return tempoTx{
		ChainID: big.NewInt(4217), MaxPriorityFee: big.NewInt(1), MaxFee: big.NewInt(1),
		GasLimit: big.NewInt(1_000_000), CallTo: currency, CallValue: new(big.Int),
		CallData: mustHex(t, vecTransfer), NonceKey: new(big.Int), Nonce: big.NewInt(5),
		FeeToken: currency,
	}
}

func TestTIP20Calldata(t *testing.T) {
	got, err := tip20Calldata("0x"+strings.ToUpper(vecRecipient), big.NewInt(10000), "")
	if err != nil || got != "0x"+vecTransfer {
		t.Errorf("transfer = %s, %v", got, err)
	}
	memo := strings.Repeat("AB", 32)
	got, err = tip20Calldata("0x"+vecRecipient, big.NewInt(10000), "0x"+memo)
	want := "0x95777d59" + vecTransfer[8:] + strings.ToLower(memo)
	if err != nil || got != want {
		t.Errorf("transferWithMemo = %s, %v", got, err)
	}
	for _, c := range []struct {
		to, memo string
		amount   int64
	}{
		{vecRecipient, "", 1}, {"0x" + vecRecipient, "0x12", 1}, {"0x" + vecRecipient, "", -1}, {"0x12", "", 1},
	} {
		if _, err := tip20Calldata(c.to, big.NewInt(c.amount), c.memo); err == nil {
			t.Errorf("%+v accepted", c)
		}
	}
}

func TestTempoTransactionVector(t *testing.T) {
	key := cowKey(t)
	tx := vectorTx(t)
	tail := "94" + vecCurrency + "80" + "c0"
	preimage := mustHex(t, "76"+"f885"+vecHead+"80"+"05"+"80"+"80"+tail)
	hash, err := tx.senderSigningHash()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(hash, keccak256(preimage)) {
		t.Fatalf("signing hash %x, want keccak(%x)", hash, preimage)
	}
	sig := key.sign(hash)
	if got := recoverAddress(t, sig, keccak256(preimage)); got != key.checksumAddress() {
		t.Fatalf("signature recovers to %s", got)
	}
	want := "76" + "f8c8" + vecHead + "80" + "05" + "80" + "80" + "94" + vecCurrency + "80" + "c0" +
		"b841" + hex.EncodeToString(sig)
	if got := hex.EncodeToString(tx.encode(sig)); got != want {
		t.Errorf("encoded\n%s\nwant\n%s", got, want)
	}
}

func TestTempoFeePayerVector(t *testing.T) {
	key := cowKey(t)
	tx := vectorTx(t)
	tx.NonceKey, tx.Nonce, tx.FeeToken, tx.AwaitingFeePayer = expiringNonceKey(), new(big.Int), nil, true
	tx.ValidBefore = big.NewInt(1_700_000_025)
	head := vecHead + "a0" + strings.Repeat("ff", 32) + "80" + "846553f119" + "80"
	preimage := mustHex(t, "76"+"f895"+head+"80"+"00"+"c0")
	hash, err := tx.senderSigningHash()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(hash, keccak256(preimage)) {
		t.Fatalf("signing hash %x, want keccak(%x)", hash, preimage)
	}
	sig := key.sign(hash)
	if got := recoverAddress(t, sig, keccak256(preimage)); got != key.checksumAddress() {
		t.Fatalf("signature recovers to %s", got)
	}
	want := "78" + "f8ec" + head + "80" + "94" + hex.EncodeToString(key.address[:]) + "c0" +
		"b841" + hex.EncodeToString(sig)
	if got := hex.EncodeToString(tx.feePayerEnvelope(key.address[:], sig)); got != want {
		t.Errorf("envelope\n%s\nwant\n%s", got, want)
	}
}

func TestTempoTransactionValidates(t *testing.T) {
	for name, mutate := range map[string]func(*tempoTx){
		"zero chain":        func(tx *tempoTx) { tx.ChainID = new(big.Int) },
		"priority over max": func(tx *tempoTx) { tx.MaxPriorityFee = big.NewInt(2) },
		"zero gas":          func(tx *tempoTx) { tx.GasLimit = new(big.Int) },
		"negative nonce":    func(tx *tempoTx) { tx.Nonce = big.NewInt(-1) },
	} {
		tx := vectorTx(t)
		mutate(&tx)
		if _, err := tx.senderSigningHash(); err == nil {
			t.Errorf("%s: signed", name)
		}
	}
}

func TestAttributionMemoLayout(t *testing.T) {
	memo, err := attributionMemo(bytes.NewReader([]byte{1, 2, 3, 4, 5, 6, 7}), "api.example.com", "")
	if err != nil {
		t.Fatal(err)
	}
	want := "0x" + hex.EncodeToString(keccak256([]byte("mpp"))[:4]) + "01" +
		hex.EncodeToString(keccak256([]byte("api.example.com"))[:10]) + strings.Repeat("00", 10) + "01020304050607"
	if memo != want || len(memo) != 66 {
		t.Errorf("memo %s, want %s", memo, want)
	}
}
