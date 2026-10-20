// Package secrets reads source credentials from the platform's database secret
// backend: Fernet tokens in encrypted_secrets, scoped by workspace.
package secrets

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
)

// Fernet decrypts tokens made by Python's cryptography.fernet.
type Fernet struct {
	signing    []byte
	encryption []byte
}

// NewFernet reads a urlsafe-base64 Fernet key.
func NewFernet(key string) (*Fernet, error) {
	raw, err := base64.URLEncoding.DecodeString(key)
	if err != nil {
		return nil, fmt.Errorf("fernet key is not urlsafe base64: %w", err)
	}
	if len(raw) != 32 {
		return nil, fmt.Errorf("fernet key is %d bytes, want 32", len(raw))
	}
	return &Fernet{signing: raw[:16], encryption: raw[16:]}, nil
}

const (
	fernetVersion  = 0x80
	headerLen      = 1 + 8 + aes.BlockSize
	macLen         = sha256.Size
	minFernetBytes = headerLen + aes.BlockSize + macLen
)

// Decrypt checks the token's HMAC and returns its plaintext. Token age is not
// checked: stored secrets do not expire.
func (f *Fernet) Decrypt(token string) ([]byte, error) {
	data, err := base64.URLEncoding.DecodeString(token)
	if err != nil {
		return nil, fmt.Errorf("fernet token is not urlsafe base64: %w", err)
	}
	if len(data) < minFernetBytes || (len(data)-headerLen-macLen)%aes.BlockSize != 0 {
		return nil, errors.New("fernet token has a bad length")
	}
	if data[0] != fernetVersion {
		return nil, fmt.Errorf("fernet token version %#x is not supported", data[0])
	}
	signed, mac := data[:len(data)-macLen], data[len(data)-macLen:]
	h := hmac.New(sha256.New, f.signing)
	h.Write(signed)
	if !hmac.Equal(mac, h.Sum(nil)) {
		return nil, errors.New("fernet token signature does not match the key")
	}
	block, err := aes.NewCipher(f.encryption)
	if err != nil {
		return nil, fmt.Errorf("fernet cipher: %w", err)
	}
	iv, ciphertext := signed[9:headerLen], signed[headerLen:]
	plaintext := make([]byte, len(ciphertext))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plaintext, ciphertext)
	return unpad(plaintext)
}

func unpad(data []byte) ([]byte, error) {
	n := int(data[len(data)-1])
	if n == 0 || n > aes.BlockSize || n > len(data) {
		return nil, errors.New("fernet plaintext has bad padding")
	}
	for _, b := range data[len(data)-n:] {
		if int(b) != n {
			return nil, errors.New("fernet plaintext has bad padding")
		}
	}
	return data[:len(data)-n], nil
}
