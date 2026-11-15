package payment

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"net/http"
	"regexp"
	"strings"
	"unicode/utf8"

	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

const (
	mppMethodTempo        = "tempo"
	mppIntentCharge       = "charge"
	mppMaxHeaderPayload   = 16 * 1024
	mppDefaultDecimals    = 6
	mppPaymentSchemeLower = "payment "
)

// authParam is _parsing._AUTH_PARAM_RE: key="quoted" or key=token.
var authParam = regexp.MustCompile(`([a-zA-Z_][\p{L}\p{N}_-]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))`)

var quotedEscape = regexp.MustCompile(`\\(.)`)

// mppChallenge is pympp's Challenge.
type mppChallenge struct {
	ID          string
	Method      string
	Intent      string
	Request     map[string]any
	Realm       string
	RequestB64  string
	Digest      string
	Expires     string
	Description string
	Opaque      map[string]any
}

// mppB64Decode is _parsing._b64_decode: base64url JSON object, 16 KiB at most.
func mppB64Decode(encoded string) (map[string]any, error) {
	if len(encoded) > mppMaxHeaderPayload {
		return nil, errors.New("header payload exceeds maximum size")
	}
	raw, err := pyB64Decode(encoded+strings.Repeat("=", (4-len(encoded)%4)%4), true)
	if err != nil || !utf8.Valid(raw) {
		return nil, errors.New("invalid base64 or JSON encoding")
	}
	v, err := decodeJSON(raw)
	if err != nil {
		return nil, errors.New("invalid base64 or JSON encoding")
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("expected JSON object")
	}
	return obj, nil
}

// parseMPPChallenge is Challenge.from_www_authenticate.
func parseMPPChallenge(header string) (mppChallenge, error) {
	header = strings.TrimSpace(header)
	if !strings.HasPrefix(strings.ToLower(header), mppPaymentSchemeLower) {
		return mppChallenge{}, errors.New("expected 'Payment' authentication scheme")
	}
	params := map[string]string{}
	rest := strings.TrimSpace(header[len(mppPaymentSchemeLower):])
	for _, m := range authParam.FindAllStringSubmatchIndex(rest, -1) {
		key := rest[m[2]:m[3]]
		if _, dup := params[key]; dup {
			return mppChallenge{}, fmt.Errorf("duplicate parameter: %s", key)
		}
		if m[4] >= 0 {
			params[key] = quotedEscape.ReplaceAllString(rest[m[4]:m[5]], "$1")
		} else {
			params[key] = rest[m[6]:m[7]]
		}
	}
	ch := mppChallenge{
		ID: params["id"], Realm: params["realm"], Method: params["method"], Intent: params["intent"],
		RequestB64: params["request"], Digest: params["digest"], Expires: params["expires"],
		Description: params["description"],
	}
	for _, f := range [][2]string{{"id", ch.ID}, {"realm", ch.Realm}, {"method", ch.Method}, {"intent", ch.Intent}, {"request", ch.RequestB64}} {
		if f[1] == "" {
			return mppChallenge{}, fmt.Errorf("missing '%s' field", f[0])
		}
	}
	var err error
	if ch.Request, err = mppB64Decode(ch.RequestB64); err != nil {
		return mppChallenge{}, err
	}
	if opaque := params["opaque"]; opaque != "" {
		if ch.Opaque, err = mppB64Decode(opaque); err != nil {
			return mppChallenge{}, err
		}
	}
	return ch, nil
}

func b64urlNoPad(s string) string {
	return base64.RawURLEncoding.EncodeToString([]byte(s))
}

// authorization is Credential(challenge=ch.to_echo(), payload, source)
// .to_authorization().
func (ch mppChallenge) authorization(payload map[string]any, source string) (string, error) {
	echo := map[string]any{
		"id": ch.ID, "realm": ch.Realm, "method": ch.Method, "intent": ch.Intent, "request": ch.RequestB64,
	}
	if ch.Expires != "" {
		echo["expires"] = ch.Expires
	}
	if ch.Digest != "" {
		echo["digest"] = ch.Digest
	}
	if ch.Opaque != nil {
		opaque, err := pyDumps(ch.Opaque, false)
		if err != nil {
			return "", err
		}
		echo["opaque"] = b64urlNoPad(opaque)
	}
	credential := map[string]any{"challenge": echo, "payload": payload}
	if source != "" {
		credential["source"] = source
	}
	text, err := pyDumps(credential, true)
	if err != nil {
		return "", err
	}
	return "Payment " + b64urlNoPad(text), nil
}

// mppMethod is the tempo(...) method the MCP path builds from mpp_config.
type mppMethod struct {
	rpcURL  string
	chainID *big.Int
}

func newMPPMethod(cfg map[string]any) (mppMethod, error) {
	var m mppMethod
	if v, ok := cfg["chain_id"]; ok && v != nil {
		n, err := configInt(v)
		if err != nil {
			return mppMethod{}, fmt.Errorf("mpp_config.chain_id: %w", err)
		}
		m.chainID = big.NewInt(n)
	}
	if v, ok := cfg["rpc_url"]; ok && v != nil {
		s, isString := v.(string)
		if !isString {
			return mppMethod{}, fmt.Errorf("mpp_config.rpc_url %v is not a string", v)
		}
		m.rpcURL = s
		return m, nil
	}
	if m.chainID == nil || m.chainID.Sign() == 0 {
		m.rpcURL = tempoMainnetRPC
		return m, nil
	}
	url, known := tempoChainRPC(m.chainID)
	if !known {
		return mppMethod{}, fmt.Errorf("unknown mpp_config.chain_id %s: set mpp_config.rpc_url for custom chains", m.chainID)
	}
	m.rpcURL = url
	return m, nil
}

func (p Protocols) quoteMPP(w Wallet, ch Challenge) (Quote, error) {
	if w.Type != walletapi.TypeMPP && w.Type != walletapi.TypeDual {
		return Quote{}, fmt.Errorf("%w: a %q wallet does not pay MPP", ErrUnsupported, w.Type)
	}
	if w.Keys.MPPTempoKey() == "" {
		return Quote{}, fmt.Errorf("%w: the wallet has no Tempo key", ErrUnsupported)
	}
	key, err := parseEVMKey(w.Keys.MPPTempoKey())
	if err != nil {
		return Quote{}, err
	}
	method, err := newMPPMethod(w.MPPConfig)
	if err != nil {
		return Quote{}, err
	}

	var challenge *mppChallenge
	for _, header := range ch.Header.Values("WWW-Authenticate") {
		if !strings.HasPrefix(strings.ToLower(header), mppPaymentSchemeLower) {
			continue
		}
		parsed, err := parseMPPChallenge(header)
		if err != nil {
			continue
		}
		if parsed.Method == mppMethodTempo {
			challenge = &parsed
			break
		}
	}
	if challenge == nil {
		return Quote{}, fmt.Errorf("%w: no tempo MPP challenge", ErrUnsupported)
	}
	if challenge.Expires != "" {
		expired, err := p.mppExpired(challenge.Expires)
		if err != nil {
			return Quote{}, err
		}
		if expired {
			return Quote{}, fmt.Errorf("%w: the MPP challenge expired at %s", ErrUnsupported, challenge.Expires)
		}
	}
	if challenge.Intent != mppIntentCharge {
		return Quote{}, fmt.Errorf("%w: unsupported MPP intent %q", ErrUnsupported, challenge.Intent)
	}

	chain := quoteChain(method, challenge.Request)
	if currency, _ := challenge.Request["currency"].(string); !tempoUSD(chain, currency) {
		return Quote{}, fmt.Errorf("MPP currency %q is not a USD stablecoin of Tempo chain %v", currency, chain)
	}
	if v, ok := w.MPPConfig["decimals"]; ok {
		decimals, err := configInt(v)
		if err != nil {
			return Quote{}, fmt.Errorf("mpp_config.decimals: %w", err)
		}
		if decimals != mppDefaultDecimals {
			return Quote{}, fmt.Errorf("mpp_config.decimals %d is not the %d of Tempo's USD stablecoins", decimals, mppDefaultDecimals)
		}
	}
	amount, err := atomicToUSD(challenge.Request["amount"], mppDefaultDecimals)
	if err != nil {
		return Quote{}, err
	}
	recipient := ""
	if r := challenge.Request["recipient"]; pyTruthy(r) {
		recipient = pyStr(r)
	} else if r := challenge.Request["payTo"]; pyTruthy(r) {
		recipient = pyStr(r)
	}
	budget, ok := w.MPPConfig["session_budget_usd"]
	if !ok || budget == nil {
		return Quote{}, errors.New("mpp_config.session_budget_usd is required to pay over MPP")
	}
	limit, err := decimalFromConfig(budget)
	if err != nil {
		return Quote{}, fmt.Errorf("mpp_config.session_budget_usd: %w", err)
	}
	c := *challenge
	return Quote{
		Protocol:  walletapi.ProtocolMPP,
		Amount:    amount,
		Recipient: recipient,
		Limit:     &limit,
		Metadata:  map[string]any{"payment_method": mppIntentCharge},
		answer: func(ctx context.Context) (http.Header, error) {
			auth, err := p.mppCredential(ctx, key, method, c, chain)
			if err != nil {
				return nil, err
			}
			h := http.Header{}
			h.Set("Authorization", auth)
			return h, nil
		},
	}, nil
}

// mppExpired is the transport's _challenge_expired: an unreadable expires is
// not expired; a naive one cannot be compared and fails, as in Python.
func (p Protocols) mppExpired(expires string) (bool, error) {
	t, aware, err := parseISO(expires)
	if err != nil {
		return false, nil
	}
	if !aware {
		return false, fmt.Errorf("MPP challenge expires %q has no time zone", expires)
	}
	if p.Now == nil {
		return false, errors.New("payment protocols need Now")
	}
	return t.Before(p.Now()), nil
}

// mppCredential is TempoMethod.create_credential.
func (p Protocols) mppCredential(ctx context.Context, key evmKey, method mppMethod, ch mppChallenge, chain *big.Int) (string, error) {
	if p.Rand == nil || p.Now == nil {
		return "", errors.New("payment protocols need Rand and Now")
	}
	request := ch.Request
	details, _ := request["methodDetails"].(map[string]any)
	useFeePayer := details != nil && pyTruthy(details["feePayer"])

	nonceKey := new(big.Int)
	if v, ok := request["nonce_key"]; ok {
		var parsed bool
		if s, isString := v.(string); isString && strings.HasPrefix(s, "0x") {
			nonceKey, parsed = pyHexInt(s)
		} else if isString {
			nonceKey, parsed = pyIntText(s)
		} else if n, isNumber := v.(json.Number); isNumber {
			nonceKey, parsed = new(big.Int).SetString(string(n), 10)
		}
		if !parsed {
			return "", fmt.Errorf("MPP nonce_key %v is not an integer", v)
		}
	}

	memo := ""
	memoValue, hasMemo := details["memo"]
	if details == nil || !hasMemo || memoValue == nil {
		var err error
		if memo, err = attributionMemo(p.Rand, ch.Realm, ""); err != nil {
			return "", err
		}
	} else {
		s, isString := memoValue.(string)
		if !isString {
			return "", fmt.Errorf("MPP methodDetails.memo %v is not a string", memoValue)
		}
		memo = s
	}

	rpcURL := method.rpcURL
	var expected *big.Int
	if details != nil {
		if v, ok := details["chainId"]; ok && v != nil {
			if n, ok := pyInt(v); ok {
				if url, known := tempoChainRPC(n); known {
					rpcURL, expected = url, n
				}
			}
		}
	}
	if expected == nil {
		expected = chain
	}
	if rpcURL == "" {
		return "", errors.New("mpp_config.rpc_url is empty")
	}

	amount, err := mppAtomicAmount(request["amount"])
	if err != nil {
		return "", err
	}
	currency, ok := request["currency"].(string)
	if !ok {
		return "", errors.New("MPP request has no currency")
	}
	recipient, ok := request["recipient"].(string)
	if !ok {
		return "", errors.New("MPP request has no recipient")
	}
	currencyAddr, err := parseAddress(currency)
	if err != nil {
		return "", fmt.Errorf("MPP currency: %w", err)
	}
	data, err := tip20Calldata(recipient, amount, memo)
	if err != nil {
		return "", err
	}
	dataBytes, err := parseHexData(data)
	if err != nil {
		return "", err
	}

	sender := key.checksumAddress()
	chainID, err := p.rpcQuantity(ctx, rpcURL, "eth_chainId", []any{})
	if err != nil {
		return "", err
	}
	onChainNonce, err := p.rpcQuantity(ctx, rpcURL, "eth_getTransactionCount", []any{sender, "pending"})
	if err != nil {
		return "", err
	}
	gasPrice, err := p.rpcQuantity(ctx, rpcURL, "eth_gasPrice", []any{})
	if err != nil {
		return "", err
	}
	if expected != nil && chainID.Cmp(expected) != 0 {
		return "", fmt.Errorf("chain ID mismatch: RPC returned %s, expected %s from challenge", chainID, expected)
	}

	tx := tempoTx{
		ChainID: chainID, MaxPriorityFee: gasPrice, MaxFee: gasPrice,
		CallTo: currencyAddr, CallValue: new(big.Int), CallData: dataBytes,
		NonceKey: nonceKey, Nonce: onChainNonce, FeeToken: currencyAddr,
	}
	if useFeePayer {
		tx.NonceKey, tx.Nonce, tx.FeeToken, tx.AwaitingFeePayer = expiringNonceKey(), new(big.Int), nil, true
		tx.ValidBefore = big.NewInt(p.Now().Unix() + tempoFeePayerWindow)
	}
	tx.GasLimit = big.NewInt(tempoDefaultGasLimit)
	estimated, err := p.rpcQuantity(ctx, rpcURL, "eth_estimateGas",
		[]any{map[string]any{"from": sender, "to": currency, "data": data}, "latest"})
	if err != nil {
		slog.WarnContext(ctx, "tempo gas estimate failed; using the static limit", "error", err)
	} else if withHeadroom := new(big.Int).Add(estimated, big.NewInt(tempoGasHeadroom)); withHeadroom.Cmp(tx.GasLimit) > 0 {
		tx.GasLimit = withHeadroom
	}

	hash, err := tx.senderSigningHash()
	if err != nil {
		return "", err
	}
	sig := key.sign(hash)
	var raw []byte
	if useFeePayer {
		raw = tx.feePayerEnvelope(key.address[:], sig)
	} else {
		raw = tx.encode(sig)
	}
	return ch.authorization(
		map[string]any{"type": "transaction", "signature": "0x" + hexLower(raw)},
		fmt.Sprintf("did:pkh:eip155:%s:%s", chainID, sender),
	)
}

// quoteChain is the Tempo chain a charge goes to: the challenge's known
// chainId, else mpp_config.chain_id, else mainnet when the RPC is its; nil
// when only a custom RPC names it.
func quoteChain(method mppMethod, request map[string]any) *big.Int {
	if details, _ := request["methodDetails"].(map[string]any); details != nil && details["chainId"] != nil {
		if n, ok := pyInt(details["chainId"]); ok {
			if _, known := tempoChainRPC(n); known {
				return n
			}
		}
	}
	if method.chainID != nil && method.chainID.Sign() != 0 {
		return method.chainID
	}
	if method.rpcURL == tempoMainnetRPC {
		return big.NewInt(tempoMainnetChainID)
	}
	return nil
}

// mppAtomicAmount is int(request["amount"]).
func mppAtomicAmount(v any) (*big.Int, error) {
	switch x := v.(type) {
	case string:
		if n, ok := pyIntText(x); ok {
			return n, nil
		}
	case json.Number:
		if n, ok := new(big.Int).SetString(string(x), 10); ok {
			return n, nil
		}
	case nil:
		return nil, errors.New("MPP request has no amount")
	}
	return nil, fmt.Errorf("MPP amount %v is not a whole number of atomic units", v)
}
