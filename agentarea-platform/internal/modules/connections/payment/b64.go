package payment

import "errors"

// pyB64Decode is CPython's binascii.a2b_base64 in its default (non-strict)
// mode, which base64.b64decode and urlsafe_b64decode use: characters outside
// the alphabet are skipped and decoding stops once a quad's padding is
// complete. urlsafe maps '-' and '_' to '+' and '/' first.
func pyB64Decode(s string, urlsafe bool) ([]byte, error) {
	out := make([]byte, 0, len(s)*3/4)
	quad, pads := 0, 0
	var left byte
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 0x80 {
			return nil, errors.New("base64: non-ASCII input")
		}
		if urlsafe {
			switch c {
			case '-':
				c = '+'
			case '_':
				c = '/'
			}
		}
		if c == '=' {
			if quad >= 2 {
				pads++
				if quad+pads >= 4 {
					return out, nil
				}
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
			quad, left = 1, v
		case 1:
			out = append(out, left<<2|v>>4)
			quad, left = 2, v&0x0f
		case 2:
			out = append(out, left<<4|v>>2)
			quad, left = 3, v&0x03
		case 3:
			out = append(out, left<<6|v)
			quad, left = 0, 0
		}
	}
	switch quad {
	case 0:
		return out, nil
	case 1:
		return nil, errors.New("base64: data length is 1 more than a multiple of 4")
	}
	return nil, errors.New("base64: incorrect padding")
}

func b64Value(c byte) (byte, bool) {
	switch {
	case c >= 'A' && c <= 'Z':
		return c - 'A', true
	case c >= 'a' && c <= 'z':
		return c - 'a' + 26, true
	case c >= '0' && c <= '9':
		return c - '0' + 52, true
	case c == '+':
		return 62, true
	case c == '/':
		return 63, true
	}
	return 0, false
}
