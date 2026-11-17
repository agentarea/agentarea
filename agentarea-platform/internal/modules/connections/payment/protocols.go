package payment

import (
	"context"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"
	"unicode/utf8"

	walletapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/wallet/api"
)

// Quote reads the challenge of a 402 for w; protocol is
// walletapi.DetectProtocol's answer ("x402" or "mpp"). ErrUnsupported
// (wrapped) when w cannot pay it; any other error is a challenge that could
// not be read.
func (p Protocols) Quote(_ context.Context, protocol string, w Wallet, ch Challenge, idempotencyKey string) (Quote, error) {
	switch protocol {
	case walletapi.ProtocolX402:
		return p.quoteX402(w, ch, idempotencyKey)
	case walletapi.ProtocolMPP:
		return p.quoteMPP(w, ch)
	}
	return Quote{}, fmt.Errorf("%w: unknown payment protocol %q", ErrUnsupported, protocol)
}

// Receipt is the settlement reference a retried answer carries: x402
// PAYMENT-RESPONSE / X-PAYMENT-RESPONSE (base64 JSON: "transaction", then
// "txHash", then "transaction_hash"), MPP X-MPP-Receipt (pympp
// parse_payment_receipt: externalId or reference; else JSON txHash /
// transactionHash). "" when none.
func Receipt(protocol string, h http.Header) string {
	switch protocol {
	case walletapi.ProtocolX402:
		return x402Receipt(h)
	case walletapi.ProtocolMPP:
		return mppReceipt(h)
	}
	return ""
}

func x402Receipt(h http.Header) string {
	raw := h.Get("PAYMENT-RESPONSE")
	if raw == "" {
		raw = h.Get("X-PAYMENT-RESPONSE")
	}
	if raw == "" {
		return ""
	}
	decoded, err := pyB64Decode(raw, false)
	if err != nil || !utf8.Valid(decoded) {
		return ""
	}
	v, err := decodeJSON(decoded)
	if err != nil {
		return ""
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return ""
	}
	return firstTruthy(obj, "transaction", "txHash", "transaction_hash")
}

func mppReceipt(h http.Header) string {
	raw := h.Get("X-MPP-Receipt")
	if raw == "" {
		return ""
	}
	if ref, ok := parseMPPReceipt(raw); ok {
		return ref
	}
	v, err := decodeJSON([]byte(raw))
	if err != nil {
		return ""
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return ""
	}
	return firstTruthy(obj, "txHash", "transactionHash")
}

// parseMPPReceipt is parse_payment_receipt followed by the transport's
// external_id-or-reference read.
func parseMPPReceipt(header string) (string, bool) {
	data, err := mppB64Decode(strings.TrimSpace(header))
	if err != nil {
		return "", false
	}
	for _, k := range []string{"status", "timestamp", "reference", "method"} {
		if _, ok := data[k]; !ok {
			return "", false
		}
	}
	if status, _ := data["status"].(string); status != "success" {
		return "", false
	}
	if _, _, err := parseISO(pyStr(data["timestamp"])); err != nil {
		return "", false
	}
	if ext := data["externalId"]; pyTruthy(ext) {
		return pyStr(ext), true
	}
	return pyStr(data["reference"]), true
}

func firstTruthy(obj map[string]any, keys ...string) string {
	for _, k := range keys {
		if v := obj[k]; pyTruthy(v) {
			return pyStr(v)
		}
	}
	return ""
}

func hexLower(b []byte) string { return hex.EncodeToString(b) }

func parseHexData(s string) ([]byte, error) {
	b, err := hex.DecodeString(strip0x(s))
	if err != nil {
		return nil, fmt.Errorf("%q is not hex data", s)
	}
	return b, nil
}
