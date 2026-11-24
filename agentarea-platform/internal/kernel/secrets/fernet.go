package secrets

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"time"
)

const (
	fernetVersion = 0x80
	fernetHeader  = 1 + 8 + aes.BlockSize
	fernetMAC     = sha256.Size
	fernetMinLen  = fernetHeader + aes.BlockSize + fernetMAC
)

// Fernet is the cryptography package's Fernet with one key: AES-128-CBC with
// PKCS7 padding, HMAC-SHA256 over version|timestamp|iv|ciphertext, the token
// urlsafe-base64 with padding. The key is the urlsafe-base64 text of 32 bytes
// (16 signing, 16 encryption). There is no rotation: Python holds a single key
// and a changed key makes every stored row undecryptable.
type Fernet struct {
	signing    []byte
	encryption []byte
	now        func() time.Time
}

// ParseFernetKey checks a key without keeping it.
func ParseFernetKey(key string) error {
	_, err := NewFernet(key)
	return err
}

// NewFernet reads a Fernet key exactly as cryptography's Fernet(key) does, so
// the key a deployment runs with keeps working. The error never carries the key.
func NewFernet(key string) (*Fernet, error) {
	raw, err := pyURLSafeB64Decode(key)
	if err != nil {
		return nil, errors.New("fernet key is not urlsafe base64")
	}
	if len(raw) != 32 {
		return nil, fmt.Errorf("fernet key is %d bytes, want 32", len(raw))
	}
	return &Fernet{signing: raw[:16], encryption: raw[16:], now: time.Now}, nil
}

// Encrypt returns a token Python's Fernet(key).decrypt accepts.
func (f *Fernet) Encrypt(plaintext []byte) (string, error) {
	iv := make([]byte, aes.BlockSize)
	if _, err := rand.Read(iv); err != nil {
		return "", fmt.Errorf("fernet iv: %w", err)
	}
	return f.encryptWithIV(plaintext, iv, f.now())
}

func (f *Fernet) encryptWithIV(plaintext, iv []byte, at time.Time) (string, error) {
	block, err := aes.NewCipher(f.encryption)
	if err != nil {
		return "", fmt.Errorf("fernet cipher: %w", err)
	}
	pad := aes.BlockSize - len(plaintext)%aes.BlockSize
	padded := make([]byte, len(plaintext)+pad)
	copy(padded, plaintext)
	for i := len(plaintext); i < len(padded); i++ {
		padded[i] = byte(pad)
	}
	token := make([]byte, fernetHeader, fernetHeader+len(padded)+fernetMAC)
	token[0] = fernetVersion
	binary.BigEndian.PutUint64(token[1:9], uint64(at.Unix()))
	copy(token[9:], iv)
	ct := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ct, padded)
	token = append(token, ct...)
	h := hmac.New(sha256.New, f.signing)
	h.Write(token)
	token = h.Sum(token)
	return base64.URLEncoding.EncodeToString(token), nil
}

// Decrypt checks the token's HMAC and returns its plaintext. Token age is not
// checked: stored secrets do not expire (Python decrypts with no ttl). The
// errors name no key or plaintext material.
func (f *Fernet) Decrypt(token string) ([]byte, error) {
	data, err := base64.URLEncoding.DecodeString(token)
	if err != nil {
		return nil, errors.New("fernet token is not urlsafe base64")
	}
	if len(data) < fernetMinLen || (len(data)-fernetHeader-fernetMAC)%aes.BlockSize != 0 {
		return nil, errors.New("fernet token has a bad length")
	}
	if data[0] != fernetVersion {
		return nil, fmt.Errorf("fernet token version %#x is not supported", data[0])
	}
	signed, mac := data[:len(data)-fernetMAC], data[len(data)-fernetMAC:]
	h := hmac.New(sha256.New, f.signing)
	h.Write(signed)
	if !hmac.Equal(mac, h.Sum(nil)) {
		return nil, errors.New("fernet token signature does not match the key")
	}
	block, err := aes.NewCipher(f.encryption)
	if err != nil {
		return nil, fmt.Errorf("fernet cipher: %w", err)
	}
	iv, ct := signed[9:fernetHeader], signed[fernetHeader:]
	plaintext := make([]byte, len(ct))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plaintext, ct)
	return unpad(plaintext)
}

func unpad(data []byte) ([]byte, error) {
	n := int(data[len(data)-1])
	if n == 0 || n > aes.BlockSize || n > len(data) {
		return nil, errors.New("fernet plaintext has bad padding")
	}
	diff := 0
	for _, b := range data[len(data)-n:] {
		diff |= int(b) ^ n
	}
	if diff != 0 {
		return nil, errors.New("fernet plaintext has bad padding")
	}
	return data[:len(data)-n], nil
}

// pyURLSafeB64Decode is base64.urlsafe_b64decode on CPython 3.14, which
// Fernet(key) reads the key with: '-' and '_' read as '+' and '/', the
// standard '+' and '/' are kept, any other byte outside the alphabet
// (whitespace included) is skipped, and padding only has to complete the
// last quad.
func pyURLSafeB64Decode(s string) ([]byte, error) {
	out := make([]byte, 0, len(s)*3/4)
	quad, pads := 0, 0
	var left byte
	for i := range len(s) {
		c := s[i]
		if c == '=' {
			if quad >= 2 {
				pads++
			}
			continue
		}
		v, ok := b64Value(c)
		if !ok {
			continue
		}
		pads = 0
		switch quad {
		case 0:
			left = v
		case 1:
			out = append(out, left<<2|v>>4)
			left = v & 0x0f
		case 2:
			out = append(out, left<<4|v>>2)
			left = v & 0x03
		case 3:
			out = append(out, left<<6|v)
		}
		quad = (quad + 1) % 4
	}
	if quad != 0 && quad+pads < 4 {
		return nil, errors.New("incorrect padding")
	}
	return out, nil
}

func b64Value(c byte) (byte, bool) {
	switch {
	case c >= 'A' && c <= 'Z':
		return c - 'A', true
	case c >= 'a' && c <= 'z':
		return c - 'a' + 26, true
	case c >= '0' && c <= '9':
		return c - '0' + 52, true
	case c == '+' || c == '-':
		return 62, true
	case c == '/' || c == '_':
		return 63, true
	}
	return 0, false
}
