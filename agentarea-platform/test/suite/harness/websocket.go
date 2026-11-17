//go:build suite

package harness

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"crypto/sha1" //nolint:gosec // RFC 6455 fixes SHA-1 for Sec-WebSocket-Accept.
	"crypto/tls"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"testing"
	"time"
)

// WebSocket opcodes.
const (
	OpText   = 0x1
	OpBinary = 0x2
	OpClose  = 0x8
	OpPing   = 0x9
	OpPong   = 0xA
)

// WSConn is a client WebSocket (RFC 6455) kept to what the suite needs:
// the handshake, masked writes, reassembled reads, ping replies, close.
type WSConn struct {
	t    testing.TB
	conn net.Conn
	r    *bufio.Reader
	// CloseCode and CloseReason are set once the server sends a close frame.
	CloseCode   int
	CloseReason string
}

// WSHandshakeError is a refused upgrade: the reply the server sent instead of 101.
type WSHandshakeError struct {
	Status int
	Header http.Header
	Body   []byte
}

func (e *WSHandshakeError) Error() string {
	return fmt.Sprintf("websocket upgrade refused: status %d: %s", e.Status, truncate(e.Body, 1000))
}

// DialWS opens a WebSocket on path with the client's credential (plus
// header). The connection is closed at t.Cleanup.
func (c *Client) DialWS(t testing.TB, path string, header http.Header) *WSConn {
	t.Helper()
	ws, err := c.TryDialWS(t, path, header)
	if err != nil {
		t.Fatalf("%s WS %s: %v", c.Name, path, err)
	}
	return ws
}

// TryDialWS is DialWS returning the failure; a refused upgrade is a *WSHandshakeError.
func (c *Client) TryDialWS(t testing.TB, path string, header http.Header) (*WSConn, error) {
	t.Helper()
	u, err := url.Parse(c.url(path))
	if err != nil {
		return nil, err
	}
	host := u.Host
	if u.Port() == "" {
		if u.Scheme == "https" {
			host += ":443"
		} else {
			host += ":80"
		}
	}
	dialer := &net.Dialer{Timeout: 10 * time.Second}
	var conn net.Conn
	if u.Scheme == "https" {
		conn, err = tls.DialWithDialer(dialer, "tcp", host, &tls.Config{ServerName: u.Hostname(), MinVersion: tls.VersionTLS12})
	} else {
		conn, err = dialer.Dial("tcp", host)
	}
	if err != nil {
		return nil, err
	}

	keyRaw := make([]byte, 16)
	if _, err := rand.Read(keyRaw); err != nil {
		_ = conn.Close()
		return nil, err
	}
	key := base64.StdEncoding.EncodeToString(keyRaw)
	req, err := http.NewRequest(http.MethodGet, u.String(), nil)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	req.Header.Set("Connection", "Upgrade")
	req.Header.Set("Upgrade", "websocket")
	req.Header.Set("Sec-WebSocket-Version", "13")
	req.Header.Set("Sec-WebSocket-Key", key)
	if c.bearer != nil {
		req.Header.Set("Authorization", "Bearer "+c.bearer(t))
	}
	for k, vs := range header {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	_ = conn.SetDeadline(time.Now().Add(15 * time.Second))
	if err := req.Write(conn); err != nil {
		_ = conn.Close()
		return nil, err
	}
	br := bufio.NewReader(conn)
	resp, err := http.ReadResponse(br, req)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	if resp.StatusCode != http.StatusSwitchingProtocols {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4000))
		_ = resp.Body.Close()
		_ = conn.Close()
		return nil, &WSHandshakeError{Status: resp.StatusCode, Header: resp.Header, Body: body}
	}
	sum := sha1.Sum([]byte(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")) //nolint:gosec // RFC 6455.
	if resp.Header.Get("Sec-WebSocket-Accept") != base64.StdEncoding.EncodeToString(sum[:]) {
		_ = conn.Close()
		return nil, errors.New("websocket upgrade: bad Sec-WebSocket-Accept")
	}
	_ = conn.SetDeadline(time.Time{})
	ws := &WSConn{t: t, conn: conn, r: br}
	t.Cleanup(func() { _ = ws.conn.Close() })
	return ws, nil
}

// WriteText sends one text message.
func (ws *WSConn) WriteText(s string) {
	ws.t.Helper()
	if err := ws.writeFrame(OpText, []byte(s)); err != nil {
		ws.t.Fatalf("websocket write: %v", err)
	}
}

// WriteJSON sends v as one text message.
func (ws *WSConn) WriteJSON(v any) {
	ws.t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		ws.t.Fatal(err)
	}
	ws.WriteText(string(raw))
}

// Read returns the next data message within d, answering pings on the way.
// A close frame from the server yields io.EOF with CloseCode set.
func (ws *WSConn) Read(d time.Duration) (opcode int, payload []byte, err error) {
	_ = ws.conn.SetReadDeadline(time.Now().Add(d))
	var msg []byte
	msgOp := 0
	for {
		fin, op, data, err := ws.readFrame()
		if err != nil {
			return 0, nil, err
		}
		switch op {
		case OpPing:
			if err := ws.writeFrame(OpPong, data); err != nil {
				return 0, nil, err
			}
			continue
		case OpPong:
			continue
		case OpClose:
			if len(data) >= 2 {
				ws.CloseCode = int(binary.BigEndian.Uint16(data[:2]))
				ws.CloseReason = string(data[2:])
			} else {
				ws.CloseCode = 1005
			}
			_ = ws.writeFrame(OpClose, data[:min(len(data), 2)])
			return 0, nil, io.EOF
		case 0:
			msg = append(msg, data...)
		default:
			msgOp, msg = op, data
		}
		if fin {
			return msgOp, msg, nil
		}
	}
}

// ReadJSON reads the next message within d into v (numbers as json.Number), failing the test otherwise.
func (ws *WSConn) ReadJSON(d time.Duration, v any) {
	ws.t.Helper()
	_, payload, err := ws.Read(d)
	if err != nil {
		ws.t.Fatalf("websocket read: %v (close %d %q)", err, ws.CloseCode, ws.CloseReason)
	}
	dec := json.NewDecoder(bytes.NewReader(payload))
	dec.UseNumber()
	if err := dec.Decode(v); err != nil {
		ws.t.Fatalf("websocket message is not %T: %v: %s", v, err, truncate(payload, 1000))
	}
}

// Close sends a normal close frame and closes the connection.
func (ws *WSConn) Close() {
	_ = ws.writeFrame(OpClose, []byte{0x03, 0xE8})
	_ = ws.conn.Close()
}

func (ws *WSConn) writeFrame(op int, payload []byte) error {
	header := []byte{0x80 | byte(op)}
	n := len(payload)
	switch {
	case n < 126:
		header = append(header, 0x80|byte(n))
	case n <= 0xFFFF:
		header = append(header, 0x80|126, byte(n>>8), byte(n))
	default:
		header = append(header, 0x80|127)
		header = binary.BigEndian.AppendUint64(header, uint64(n))
	}
	mask := make([]byte, 4)
	if _, err := rand.Read(mask); err != nil {
		return err
	}
	header = append(header, mask...)
	masked := make([]byte, n)
	for i := range payload {
		masked[i] = payload[i] ^ mask[i%4]
	}
	_ = ws.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	_, err := ws.conn.Write(append(header, masked...))
	return err
}

func (ws *WSConn) readFrame() (fin bool, op int, payload []byte, err error) {
	var h [2]byte
	if _, err := io.ReadFull(ws.r, h[:]); err != nil {
		return false, 0, nil, err
	}
	fin = h[0]&0x80 != 0
	op = int(h[0] & 0x0F)
	masked := h[1]&0x80 != 0
	n := uint64(h[1] & 0x7F)
	switch n {
	case 126:
		var ext [2]byte
		if _, err := io.ReadFull(ws.r, ext[:]); err != nil {
			return false, 0, nil, err
		}
		n = uint64(binary.BigEndian.Uint16(ext[:]))
	case 127:
		var ext [8]byte
		if _, err := io.ReadFull(ws.r, ext[:]); err != nil {
			return false, 0, nil, err
		}
		n = binary.BigEndian.Uint64(ext[:])
	}
	if n > 64<<20 {
		return false, 0, nil, fmt.Errorf("websocket frame of %d bytes", n)
	}
	var mask [4]byte
	if masked {
		if _, err := io.ReadFull(ws.r, mask[:]); err != nil {
			return false, 0, nil, err
		}
	}
	payload = make([]byte, n)
	if _, err := io.ReadFull(ws.r, payload); err != nil {
		return false, 0, nil, err
	}
	if masked {
		for i := range payload {
			payload[i] ^= mask[i%4]
		}
	}
	return fin, op, payload, nil
}
