package payment

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"math/big"
	"strings"
)

// Tempo (pympp methods/tempo, pytempo models.py): the type-0x76 transaction a
// charge credential carries, the 0x78 fee payer envelope and the TIP-20
// transfer calldata.

const (
	tempoTxType          = 0x76
	tempoFeePayerType    = 0x78
	tempoDefaultGasLimit = 1_000_000
	tempoGasHeadroom     = 5_000
	tempoFeePayerWindow  = 25

	tempoMainnetChainID = 4217
	tempoMainnetRPC     = "https://rpc.tempo.xyz"
	tempoTestnetChainID = 42431
	tempoTestnetRPC     = "https://rpc.moderato.tempo.xyz"

	tip20Transfer         = "a9059cbb"
	tip20TransferWithMemo = "95777d59"
	attributionVersion    = 0x01
)

// tempoChainRPC is pympp's CHAIN_RPC_URLS.
func tempoChainRPC(chainID *big.Int) (string, bool) {
	if chainID == nil || !chainID.IsInt64() {
		return "", false
	}
	switch chainID.Int64() {
	case tempoMainnetChainID:
		return tempoMainnetRPC, true
	case tempoTestnetChainID:
		return tempoTestnetRPC, true
	}
	return "", false
}

// Tempo's USD stablecoins (pympp _defaults PATH_USD and USDC), six decimals each.
const (
	tempoPathUSD = "0x20c0000000000000000000000000000000000000"
	tempoUSDC    = "0x20C000000000000000000000b9537d11c60E8b50"
)

// tempoUSD reports whether currency is a USD stablecoin of the chain: USDC
// and pathUSD on mainnet, pathUSD on the testnet.
func tempoUSD(chainID *big.Int, currency string) bool {
	if chainID == nil || !chainID.IsInt64() {
		return false
	}
	switch chainID.Int64() {
	case tempoMainnetChainID:
		return strings.EqualFold(currency, tempoUSDC) || strings.EqualFold(currency, tempoPathUSD)
	case tempoTestnetChainID:
		return strings.EqualFold(currency, tempoPathUSD)
	}
	return false
}

func expiringNonceKey() *big.Int {
	return new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 256), big.NewInt(1))
}

// tempoTx is a TempoTransaction with one call, no access list, no
// authorization list and no key authorization: what create_credential builds.
type tempoTx struct {
	ChainID          *big.Int
	MaxPriorityFee   *big.Int
	MaxFee           *big.Int
	GasLimit         *big.Int
	CallTo           []byte
	CallValue        *big.Int
	CallData         []byte
	NonceKey         *big.Int
	Nonce            *big.Int
	ValidBefore      *big.Int
	ValidAfter       *big.Int
	FeeToken         []byte
	AwaitingFeePayer bool
}

func (t tempoTx) validate() error {
	switch {
	case t.ChainID.Sign() <= 0:
		return errors.New("tempo: chain_id must be > 0")
	case t.GasLimit.Sign() <= 0:
		return errors.New("tempo: gas_limit must be > 0")
	case t.MaxPriorityFee.Sign() < 0, t.MaxFee.Sign() < 0:
		return errors.New("tempo: fees must be >= 0")
	case t.MaxFee.Sign() != 0 && t.MaxPriorityFee.Cmp(t.MaxFee) > 0:
		return errors.New("tempo: max_priority_fee_per_gas cannot exceed max_fee_per_gas")
	case t.Nonce.Sign() < 0, t.NonceKey.Sign() < 0, t.CallValue.Sign() < 0:
		return errors.New("tempo: nonce, nonce_key and call value must be >= 0")
	case len(t.CallTo) != 20:
		return errors.New("tempo: the call needs a 20-byte to address")
	case t.ValidBefore != nil && t.ValidAfter != nil && t.ValidAfter.Cmp(t.ValidBefore) > 0:
		return errors.New("tempo: valid_after cannot be greater than valid_before")
	}
	return nil
}

func optionalUint(v *big.Int) any {
	if v == nil {
		return []byte{}
	}
	return v
}

func (t tempoTx) head() rlpList {
	return rlpList{
		t.ChainID, t.MaxPriorityFee, t.MaxFee, t.GasLimit,
		rlpList{rlpList{t.CallTo, t.CallValue, t.CallData}},
		rlpList{},
		t.NonceKey, t.Nonce,
		optionalUint(t.ValidBefore), optionalUint(t.ValidAfter),
	}
}

func (t tempoTx) feeToken() []byte {
	if t.FeeToken == nil {
		return []byte{}
	}
	return t.FeeToken
}

// senderSigningHash is _signing_hash_sender: with a fee payer the fee token
// is left out and the fee payer slot holds 0x00.
func (t tempoTx) senderSigningHash() ([]byte, error) {
	if err := t.validate(); err != nil {
		return nil, err
	}
	fields := t.head()
	if t.AwaitingFeePayer {
		fields = append(fields, []byte{}, []byte{0x00})
	} else {
		fields = append(fields, t.feeToken(), []byte{})
	}
	fields = append(fields, rlpList{})
	return keccak256([]byte{tempoTxType}, rlpEncode(fields)), nil
}

// encode is TempoTransaction.encode of the sender-signed transaction with no
// fee payer signature: 0x76 || rlp(fields).
func (t tempoTx) encode(senderSig []byte) []byte {
	fields := append(t.head(), t.feeToken(), []byte{}, rlpList{}, senderSig)
	return append([]byte{tempoTxType}, rlpEncode(fields)...)
}

// feePayerEnvelope is encode_fee_payer_envelope: 0x78 || rlp(fields) with
// the sender address in the fee payer signature slot.
func (t tempoTx) feePayerEnvelope(sender, senderSig []byte) []byte {
	fields := append(t.head(), t.feeToken(), sender, rlpList{}, senderSig)
	return append([]byte{tempoFeePayerType}, rlpEncode(fields)...)
}

// tip20Calldata is _encode_transfer / _encode_transfer_with_memo.
func tip20Calldata(to string, amount *big.Int, memo string) (string, error) {
	if len(to) < 2 || (to[:2] != "0x" && to[:2] != "0X") {
		return "", fmt.Errorf("recipient %q is not a 0x address", to)
	}
	if _, err := parseAddress(to); err != nil {
		return "", err
	}
	if amount.Sign() < 0 || amount.BitLen() > 256 {
		return "", fmt.Errorf("amount %s is not a uint256", amount)
	}
	toPadded := fmt.Sprintf("%064s", strings.ToLower(to[2:]))
	amountPadded := fmt.Sprintf("%064s", amount.Text(16))
	if memo == "" {
		return "0x" + tip20Transfer + toPadded + amountPadded, nil
	}
	memoClean := strings.TrimPrefix(memo, "0x")
	if len(memoClean) != 64 {
		return "", fmt.Errorf("memo must be exactly 32 bytes (64 hex chars), got %d", len(memoClean))
	}
	if _, err := hex.DecodeString(memoClean); err != nil {
		return "", errors.New("memo is not hex")
	}
	return "0x" + tip20TransferWithMemo + toPadded + amountPadded + strings.ToLower(memoClean), nil
}

// attributionMemo is _attribution.encode: TAG, version, server and client
// fingerprints, 7 random bytes.
func attributionMemo(rand io.Reader, serverID, clientID string) (string, error) {
	buf := make([]byte, 32)
	copy(buf[0:4], keccak256([]byte("mpp"))[:4])
	buf[4] = attributionVersion
	copy(buf[5:15], keccak256([]byte(serverID))[:10])
	if clientID != "" {
		copy(buf[15:25], keccak256([]byte(clientID))[:10])
	}
	if _, err := io.ReadFull(rand, buf[25:32]); err != nil {
		return "", fmt.Errorf("attribution nonce: %w", err)
	}
	return "0x" + hex.EncodeToString(buf), nil
}
