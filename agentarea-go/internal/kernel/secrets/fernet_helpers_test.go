package secrets

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
)

func decodeToken(token string) ([]byte, error) { return base64.URLEncoding.DecodeString(token) }

func resign(f *Fernet, raw []byte) string {
	body := raw[:len(raw)-fernetMAC]
	h := hmac.New(sha256.New, f.signing)
	h.Write(body)
	return base64.URLEncoding.EncodeToString(h.Sum(append([]byte{}, body...)))
}
