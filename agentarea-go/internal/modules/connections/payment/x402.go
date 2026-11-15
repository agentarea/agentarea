package payment

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	walletapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/wallet/api"
)

const (
	x402DefaultNetwork     = "eip155:8453"
	x402DefaultTimeout     = 3600
	x402ValidityBuffer     = 600
	x402PaymentRequired    = "PAYMENT-REQUIRED"
	x402PaymentSignature   = "PAYMENT-SIGNATURE"
	x402PaymentIdentifier  = "payment-identifier"
	x402ExposeHeaders      = "PAYMENT-RESPONSE,X-PAYMENT-RESPONSE"
	x402PaymentIDMinLength = 16
	x402PaymentIDMaxLength = 128
)

var paymentIDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// x402Requirement is one PaymentRequirements of a v2 challenge, as pydantic
// validates it (fields by alias or by name).
type x402Requirement struct {
	Scheme            string
	Network           string
	Asset             string
	Amount            string
	PayTo             string
	MaxTimeoutSeconds int64
	Extra             orderedObject
}

type x402Required struct {
	Version    int64
	Resource   orderedObject
	Accepts    []x402Requirement
	Extensions orderedObject
}

func (p Protocols) quoteX402(w Wallet, ch Challenge, idempotencyKey string) (Quote, error) {
	if w.Type != walletapi.TypeX402 && w.Type != walletapi.TypeDual {
		return Quote{}, fmt.Errorf("%w: a %q wallet does not pay x402", ErrUnsupported, w.Type)
	}
	if w.Keys.X402PrivateKey() == "" {
		return Quote{}, fmt.Errorf("%w: the wallet has no x402 key", ErrUnsupported)
	}
	key, err := parseEVMKey(w.Keys.X402PrivateKey())
	if err != nil {
		return Quote{}, err
	}
	network := x402DefaultNetwork
	if v, ok := w.X402Config["network"]; ok && v != nil {
		s, isString := v.(string)
		if !isString {
			return Quote{}, fmt.Errorf("x402_config.network %v is not a string", v)
		}
		if s != "" {
			network = s
		}
	}

	required, err := parseX402Required(ch.Header.Get(x402PaymentRequired))
	if err != nil {
		return Quote{}, err
	}
	if required.Version == 1 {
		return Quote{}, fmt.Errorf("%w: x402 v1 challenges are not paid", ErrUnsupported)
	}
	var req *x402Requirement
	matched := false
	for i := range required.Accepts {
		r := &required.Accepts[i]
		if r.Scheme != "exact" || !networkMatches(r.Network, network) {
			continue
		}
		matched = true
		if address, _, _, known := x402DefaultAsset(r.Network); known && strings.EqualFold(address, r.Asset) {
			req = r
			break
		}
	}
	if !matched {
		return Quote{}, fmt.Errorf("%w: no exact x402 requirement on %s", ErrUnsupported, network)
	}
	if req == nil {
		return Quote{}, fmt.Errorf("no exact x402 requirement on %s pays in that network's USD stablecoin", network)
	}
	if method, _ := req.Extra.get("assetTransferMethod"); string(bytes.TrimSpace(method)) == `"permit2"` {
		return Quote{}, fmt.Errorf("%w: permit2 x402 payments are not paid", ErrUnsupported)
	}

	amount, err := atomicToUSD(req.Amount, 6)
	if err != nil {
		return Quote{}, err
	}
	value, ok := pyIntText(req.Amount)
	if !ok || value.Sign() < 0 {
		return Quote{}, fmt.Errorf("x402 amount %q is not a whole number of atomic units", req.Amount)
	}
	chainID, err := evmChainID(req.Network)
	if err != nil {
		return Quote{}, err
	}
	accepted, name, version, err := eip712Domain(*req)
	if err != nil {
		return Quote{}, err
	}
	extensions, err := withPaymentIdentifier(required.Extensions, idempotencyKey)
	if err != nil {
		return Quote{}, err
	}
	reqCopy := *req
	return Quote{
		Protocol:  walletapi.ProtocolX402,
		Amount:    amount,
		Recipient: req.PayTo,
		Metadata:  map[string]any{"network": req.Network, "scheme": "exact"},
		answer: func(context.Context) (http.Header, error) {
			payload, err := p.x402Payload(key, reqCopy, value, chainID, name, version, accepted, required.Resource, extensions)
			if err != nil {
				return nil, err
			}
			h := http.Header{}
			h.Set(x402PaymentSignature, base64.StdEncoding.EncodeToString(payload))
			h.Set("Access-Control-Expose-Headers", x402ExposeHeaders)
			return h, nil
		},
	}, nil
}

func networkMatches(network, pattern string) bool {
	if strings.HasSuffix(pattern, ":*") {
		return strings.HasPrefix(network, pattern[:len(pattern)-1])
	}
	return network == pattern
}

// evmChainID is get_evm_chain_id: the number after "eip155:".
func evmChainID(network string) (*big.Int, error) {
	if !strings.HasPrefix(network, "eip155:") {
		return nil, fmt.Errorf("unsupported network format: %s (expected eip155:CHAIN_ID)", network)
	}
	n, ok := pyIntText(strings.Split(network, ":")[1])
	if !ok {
		return nil, fmt.Errorf("invalid CAIP-2 network format: %s", network)
	}
	return n, nil
}

// x402DefaultAsset is x402's NETWORK_CONFIGS default_asset table (address,
// EIP-712 name and version). Its address is the only asset paid on the
// network: amounts are read as six-decimal USD.
func x402DefaultAsset(network string) (address, name, version string, ok bool) {
	switch network {
	case "eip155:8453":
		return "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "USD Coin", "2", true
	case "eip155:84532":
		return "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "USDC", "2", true
	case "eip155:4326":
		return "0xFAfDdbb3FC7688494971a79cc65DCa3EF82079E7", "MegaUSD", "1", true
	case "eip155:143":
		return "0x754704Bc059F8C67012fEd69BC8A327a5aafb603", "USD Coin", "2", true
	}
	return "", "", "", false
}

// eip712Domain is ExactEvmScheme._sign_authorization's domain lookup. A
// non-empty extra without a name gets the asset table's name and version
// written into it, as Python mutates requirements.extra; accepted is the
// requirement as the payload echoes it.
func eip712Domain(req x402Requirement) (accepted orderedObject, name, version string, err error) {
	extra := req.Extra
	if _, hasName := extra.get("name"); !hasName {
		address, assetName, assetVersion, known := x402DefaultAsset(req.Network)
		if !known || !strings.EqualFold(address, req.Asset) {
			return nil, "", "", errors.New("EIP-712 domain parameters (name, version) required in extra")
		}
		if len(extra) > 0 {
			extra = extra.with("name", mustJSON(assetName)).with("version", mustJSON(assetVersion))
		}
		name, version = assetName, assetVersion
	} else {
		rawName, _ := extra.get("name")
		if err := json.Unmarshal(rawName, &name); err != nil || isJSONNull(rawName) {
			return nil, "", "", errors.New("x402 extra.name is not a string")
		}
		version = "1"
		if rawVersion, ok := extra.get("version"); ok {
			if err := json.Unmarshal(rawVersion, &version); err != nil || isJSONNull(rawVersion) {
				return nil, "", "", errors.New("x402 extra.version is not a string")
			}
		}
	}
	if extra == nil {
		extra = orderedObject{}
	}
	accepted = orderedObject{
		{"scheme", mustJSON(req.Scheme)},
		{"network", mustJSON(req.Network)},
		{"asset", mustJSON(req.Asset)},
		{"amount", mustJSON(req.Amount)},
		{"payTo", mustJSON(req.PayTo)},
		{"maxTimeoutSeconds", json.RawMessage(strconv.FormatInt(req.MaxTimeoutSeconds, 10))},
		{"extra", mustJSON(extra)},
	}
	return accepted, name, version, nil
}

// withPaymentIdentifier is append_payment_identifier_to_extensions run by the
// before-payment hook: only when the challenge declared the extension.
func withPaymentIdentifier(extensions orderedObject, id string) (orderedObject, error) {
	if len(extensions) == 0 {
		return extensions, nil
	}
	rawExt, ok := extensions.get(x402PaymentIdentifier)
	if !ok {
		return extensions, nil
	}
	ext, err := parseOrderedObject(rawExt)
	if err != nil || len(ext) == 0 {
		return extensions, nil
	}
	rawInfo, _ := ext.get("info")
	info, err := parseOrderedObject(rawInfo)
	if err != nil || len(info) == 0 {
		return extensions, nil
	}
	required, _ := info.get("required")
	if r := string(bytes.TrimSpace(required)); r != "true" && r != "false" {
		return extensions, nil
	}
	if len(id) < x402PaymentIDMinLength || len(id) > x402PaymentIDMaxLength || !paymentIDPattern.MatchString(id) {
		return nil, fmt.Errorf("invalid payment ID %q: 16-128 characters of letters, digits, hyphens and underscores", id)
	}
	info = info.with("id", mustJSON(id))
	ext = ext.with("info", mustJSON(info))
	return extensions.with(x402PaymentIdentifier, mustJSON(ext)), nil
}

func (p Protocols) x402Payload(key evmKey, req x402Requirement, value, chainID *big.Int, name, version string,
	accepted, resource, extensions orderedObject,
) ([]byte, error) {
	if p.Rand == nil || p.Now == nil {
		return nil, errors.New("payment protocols need Rand and Now")
	}
	nonce := make([]byte, 32)
	if _, err := io.ReadFull(p.Rand, nonce); err != nil {
		return nil, fmt.Errorf("x402 nonce: %w", err)
	}
	timeout := req.MaxTimeoutSeconds
	if timeout == 0 {
		timeout = x402DefaultTimeout
	}
	now := p.Now().Unix()
	validAfter, validBefore := now-x402ValidityBuffer, now+timeout
	from := key.checksumAddress()
	td := typedData{
		Types: map[string][]typedField{"TransferWithAuthorization": {
			{"from", "address"}, {"to", "address"}, {"value", "uint256"},
			{"validAfter", "uint256"}, {"validBefore", "uint256"}, {"nonce", "bytes32"},
		}},
		PrimaryType: "TransferWithAuthorization",
		Domain:      map[string]any{"name": name, "version": version, "chainId": chainID, "verifyingContract": req.Asset},
		Message: map[string]any{
			"from": from, "to": req.PayTo, "value": value,
			"validAfter": big.NewInt(validAfter), "validBefore": big.NewInt(validBefore), "nonce": nonce,
		},
	}
	digest, err := td.digest()
	if err != nil {
		return nil, err
	}
	type authorization struct {
		From        string `json:"from"`
		To          string `json:"to"`
		Value       string `json:"value"`
		ValidAfter  string `json:"validAfter"`
		ValidBefore string `json:"validBefore"`
		Nonce       string `json:"nonce"`
	}
	type inner struct {
		Authorization authorization `json:"authorization"`
		Signature     string        `json:"signature"`
	}
	payload := struct {
		X402Version int           `json:"x402Version"`
		Payload     inner         `json:"payload"`
		Accepted    orderedObject `json:"accepted"`
		Resource    orderedObject `json:"resource,omitempty"`
		Extensions  orderedObject `json:"extensions,omitempty"`
	}{
		X402Version: 2,
		Payload: inner{
			Authorization: authorization{
				From: from, To: req.PayTo, Value: req.Amount,
				ValidAfter: strconv.FormatInt(validAfter, 10), ValidBefore: strconv.FormatInt(validBefore, 10),
				Nonce: "0x" + hex.EncodeToString(nonce),
			},
			Signature: "0x" + hex.EncodeToString(key.sign(digest)),
		},
		Accepted:   accepted,
		Resource:   resource,
		Extensions: extensions,
	}
	return marshalNoEscape(payload)
}

func mustJSON(v any) json.RawMessage {
	b, err := marshalNoEscape(v)
	if err != nil {
		panic(err)
	}
	return b
}

// decodeX402Header reads PAYMENT-REQUIRED: JSON, or base64 / base64url JSON.
func decodeX402Header(raw string) ([]byte, error) {
	text := strings.TrimSpace(raw)
	if text == "" {
		return nil, errors.New("the 402 has no PAYMENT-REQUIRED header")
	}
	if strings.HasPrefix(text, "{") {
		return []byte(text), nil
	}
	decoded, err := pyB64Decode(text+strings.Repeat("=", (4-len(text)%4)%4), true)
	if err != nil {
		return nil, fmt.Errorf("PAYMENT-REQUIRED is not base64: %w", err)
	}
	if !utf8.Valid(decoded) {
		return nil, errors.New("PAYMENT-REQUIRED is not UTF-8")
	}
	return decoded, nil
}

func parseX402Required(header string) (x402Required, error) {
	data, err := decodeX402Header(header)
	if err != nil {
		return x402Required{}, err
	}
	obj, err := parseOrderedObject(data)
	if err != nil {
		return x402Required{}, fmt.Errorf("PAYMENT-REQUIRED is not a JSON object: %w", err)
	}
	out := x402Required{Version: 2}
	if raw, ok := field(obj, "x402Version", "x402_version"); ok {
		if out.Version, err = laxInt(raw); err != nil {
			return x402Required{}, fmt.Errorf("x402Version: %w", err)
		}
	}
	if out.Version == 1 {
		return out, nil
	}
	rawAccepts, ok := field(obj, "accepts", "accepts")
	if !ok {
		return x402Required{}, errors.New("PAYMENT-REQUIRED has no accepts")
	}
	var accepts []json.RawMessage
	if err := json.Unmarshal(rawAccepts, &accepts); err != nil || isJSONNull(rawAccepts) {
		return x402Required{}, errors.New("PAYMENT-REQUIRED accepts is not a list")
	}
	for i, raw := range accepts {
		r, err := parseX402Requirement(raw)
		if err != nil {
			return x402Required{}, fmt.Errorf("accepts[%d]: %w", i, err)
		}
		out.Accepts = append(out.Accepts, r)
	}
	if raw, ok := field(obj, "resource", "resource"); ok && !isJSONNull(raw) {
		if out.Resource, err = parseResource(raw); err != nil {
			return x402Required{}, fmt.Errorf("resource: %w", err)
		}
	}
	if raw, ok := field(obj, "extensions", "extensions"); ok && !isJSONNull(raw) {
		if out.Extensions, err = parseOrderedObject(raw); err != nil {
			return x402Required{}, fmt.Errorf("extensions: %w", err)
		}
	}
	return out, nil
}

func parseX402Requirement(raw json.RawMessage) (x402Requirement, error) {
	obj, err := parseOrderedObject(raw)
	if err != nil {
		return x402Requirement{}, err
	}
	var r x402Requirement
	for _, f := range []struct {
		alias, name string
		dst         *string
	}{
		{"scheme", "scheme", &r.Scheme}, {"network", "network", &r.Network}, {"asset", "asset", &r.Asset},
		{"amount", "amount", &r.Amount}, {"payTo", "pay_to", &r.PayTo},
	} {
		v, ok := field(obj, f.alias, f.name)
		if !ok {
			return x402Requirement{}, fmt.Errorf("%s is required", f.alias)
		}
		if err := strictString(v, f.dst); err != nil {
			return x402Requirement{}, fmt.Errorf("%s: %w", f.alias, err)
		}
	}
	v, ok := field(obj, "maxTimeoutSeconds", "max_timeout_seconds")
	if !ok {
		return x402Requirement{}, errors.New("maxTimeoutSeconds is required")
	}
	if r.MaxTimeoutSeconds, err = laxInt(v); err != nil {
		return x402Requirement{}, fmt.Errorf("maxTimeoutSeconds: %w", err)
	}
	if v, ok := field(obj, "extra", "extra"); ok {
		if r.Extra, err = parseOrderedObject(v); err != nil {
			return x402Requirement{}, fmt.Errorf("extra: %w", err)
		}
	}
	return r, nil
}

func parseResource(raw json.RawMessage) (orderedObject, error) {
	obj, err := parseOrderedObject(raw)
	if err != nil {
		return nil, err
	}
	var url string
	v, ok := field(obj, "url", "url")
	if !ok {
		return nil, errors.New("url is required")
	}
	if err := strictString(v, &url); err != nil {
		return nil, fmt.Errorf("url: %w", err)
	}
	out := orderedObject{{"url", mustJSON(url)}}
	for _, f := range [][2]string{{"description", "description"}, {"mimeType", "mime_type"}} {
		v, ok := field(obj, f[0], f[1])
		if !ok || isJSONNull(v) {
			continue
		}
		var s string
		if err := strictString(v, &s); err != nil {
			return nil, fmt.Errorf("%s: %w", f[0], err)
		}
		out = append(out, objectMember{f[0], mustJSON(s)})
	}
	return out, nil
}

// field reads a pydantic field: by its camelCase alias, else by its name.
func field(obj orderedObject, alias, name string) (json.RawMessage, bool) {
	if v, ok := obj.get(alias); ok {
		return v, true
	}
	return obj.get(name)
}

func strictString(raw json.RawMessage, dst *string) error {
	if isJSONNull(raw) || bytes.TrimSpace(raw)[0] != '"' {
		return errors.New("not a string")
	}
	return json.Unmarshal(raw, dst)
}

// laxInt is pydantic's lax int: an integer, a float with no fraction, or a
// string holding an integer.
func laxInt(raw json.RawMessage) (int64, error) {
	v, err := decodeJSON(raw)
	if err != nil {
		return 0, err
	}
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return i, nil
		}
		f, err := x.Float64()
		if err != nil || f != float64(int64(f)) {
			return 0, errors.New("not an integer")
		}
		return int64(f), nil
	case string:
		n, ok := pyIntText(x)
		if !ok || !n.IsInt64() {
			return 0, errors.New("not an integer")
		}
		return n.Int64(), nil
	case bool:
		if x {
			return 1, nil
		}
		return 0, nil
	}
	return 0, errors.New("not an integer")
}
