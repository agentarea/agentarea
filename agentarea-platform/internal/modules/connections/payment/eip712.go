package payment

import (
	"encoding/hex"
	"fmt"
	"math/big"
	"sort"
	"strconv"
	"strings"
)

// EIP-712 typed-data hashing as eth_account's encode_typed_data does it, for
// atomic types and nested structs (no arrays: nothing here signs one).

type typedField struct {
	Name string
	Type string
}

type typedData struct {
	Types       map[string][]typedField
	PrimaryType string
	Domain      map[string]any
	Message     map[string]any
}

func domainFields(domain map[string]any) []typedField {
	var out []typedField
	for _, f := range []typedField{
		{"name", "string"}, {"version", "string"}, {"chainId", "uint256"},
		{"verifyingContract", "address"}, {"salt", "bytes32"},
	} {
		if _, ok := domain[f.Name]; ok {
			out = append(out, f)
		}
	}
	return out
}

func (td typedData) digest() ([]byte, error) {
	types := make(map[string][]typedField, len(td.Types)+1)
	for k, v := range td.Types {
		types[k] = v
	}
	types["EIP712Domain"] = domainFields(td.Domain)
	domainHash, err := hashStruct("EIP712Domain", types, td.Domain)
	if err != nil {
		return nil, err
	}
	messageHash, err := hashStruct(td.PrimaryType, types, td.Message)
	if err != nil {
		return nil, err
	}
	return keccak256([]byte{0x19, 0x01}, domainHash, messageHash), nil
}

func structDeps(name string, types map[string][]typedField, seen map[string]bool) {
	if seen[name] {
		return
	}
	if _, ok := types[name]; !ok {
		return
	}
	seen[name] = true
	for _, f := range types[name] {
		structDeps(f.Type, types, seen)
	}
}

func encodeType(name string, types map[string][]typedField) string {
	seen := map[string]bool{}
	structDeps(name, types, seen)
	delete(seen, name)
	deps := make([]string, 0, len(seen))
	for d := range seen {
		deps = append(deps, d)
	}
	sort.Strings(deps)
	var b strings.Builder
	for _, t := range append([]string{name}, deps...) {
		b.WriteString(t)
		b.WriteByte('(')
		for i, f := range types[t] {
			if i > 0 {
				b.WriteByte(',')
			}
			b.WriteString(f.Type + " " + f.Name)
		}
		b.WriteByte(')')
	}
	return b.String()
}

func hashStruct(name string, types map[string][]typedField, data map[string]any) ([]byte, error) {
	fields, ok := types[name]
	if !ok {
		return nil, fmt.Errorf("eip712: unknown type %s", name)
	}
	enc := keccak256([]byte(encodeType(name, types)))
	for _, f := range fields {
		v, ok := data[f.Name]
		if !ok || v == nil {
			return nil, fmt.Errorf("eip712: %s.%s is missing", name, f.Name)
		}
		word, err := encodeValue(f.Type, v, types)
		if err != nil {
			return nil, fmt.Errorf("eip712: %s.%s: %w", name, f.Name, err)
		}
		enc = append(enc, word...)
	}
	return keccak256(enc), nil
}

func encodeValue(typ string, v any, types map[string][]typedField) ([]byte, error) {
	if _, isStruct := types[typ]; isStruct {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("%s is not an object", typ)
		}
		return hashStruct(typ, types, m)
	}
	switch {
	case typ == "string":
		s, ok := v.(string)
		if !ok {
			return nil, fmt.Errorf("not a string")
		}
		return keccak256([]byte(s)), nil
	case typ == "bytes":
		b, err := bytesValue(v)
		if err != nil {
			return nil, err
		}
		return keccak256(b), nil
	case typ == "address":
		s, ok := v.(string)
		if !ok {
			return nil, fmt.Errorf("not an address")
		}
		a, err := parseAddress(s)
		if err != nil {
			return nil, err
		}
		return leftPad32(a), nil
	case typ == "bool":
		b, ok := v.(bool)
		if !ok {
			return nil, fmt.Errorf("not a bool")
		}
		if b {
			return leftPad32([]byte{1}), nil
		}
		return make([]byte, 32), nil
	case strings.HasPrefix(typ, "bytes"):
		n, err := strconv.Atoi(typ[len("bytes"):])
		if err != nil || n < 1 || n > 32 {
			return nil, fmt.Errorf("unsupported type %s", typ)
		}
		b, err := bytesValue(v)
		if err != nil {
			return nil, err
		}
		if len(b) != n {
			return nil, fmt.Errorf("%s holds %d bytes", typ, len(b))
		}
		out := make([]byte, 32)
		copy(out, b)
		return out, nil
	case strings.HasPrefix(typ, "uint"), strings.HasPrefix(typ, "int"):
		return encodeInteger(typ, v)
	}
	return nil, fmt.Errorf("unsupported type %s", typ)
}

func bytesValue(v any) ([]byte, error) {
	switch b := v.(type) {
	case []byte:
		return b, nil
	case string:
		raw, err := hex.DecodeString(strip0x(b))
		if err != nil {
			return nil, fmt.Errorf("not hex bytes")
		}
		return raw, nil
	}
	return nil, fmt.Errorf("not bytes")
}

func encodeInteger(typ string, v any) ([]byte, error) {
	signed := strings.HasPrefix(typ, "int")
	bitsText := strings.TrimPrefix(strings.TrimPrefix(typ, "u"), "int")
	bits := 256
	if bitsText != "" {
		n, err := strconv.Atoi(bitsText)
		if err != nil || n < 8 || n > 256 || n%8 != 0 {
			return nil, fmt.Errorf("unsupported type %s", typ)
		}
		bits = n
	}
	var n *big.Int
	switch x := v.(type) {
	case *big.Int:
		n = x
	case int64:
		n = big.NewInt(x)
	case int:
		n = big.NewInt(int64(x))
	default:
		return nil, fmt.Errorf("not an integer")
	}
	limit := new(big.Int).Lsh(big.NewInt(1), uint(bits))
	if signed {
		half := new(big.Int).Rsh(limit, 1)
		if n.Cmp(half) >= 0 || n.Cmp(new(big.Int).Neg(half)) < 0 {
			return nil, fmt.Errorf("%s out of range", typ)
		}
		if n.Sign() < 0 {
			return leftPad32(new(big.Int).Add(n, new(big.Int).Lsh(big.NewInt(1), 256)).Bytes()), nil
		}
		return leftPad32(n.Bytes()), nil
	}
	if n.Sign() < 0 || n.Cmp(limit) >= 0 {
		return nil, fmt.Errorf("%s out of range", typ)
	}
	return leftPad32(n.Bytes()), nil
}

func leftPad32(b []byte) []byte {
	out := make([]byte, 32)
	copy(out[32-len(b):], b)
	return out
}
