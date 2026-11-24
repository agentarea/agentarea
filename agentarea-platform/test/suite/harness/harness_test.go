//go:build suite

package harness

import (
	"bufio"
	"crypto/sha1" //nolint:gosec // RFC 6455.
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCompare(t *testing.T) {
	var got any
	if err := json.Unmarshal([]byte(`{"id":"0f395217-57e7-4301-9ebd-b86dac79630a","n":3,"tags":["b","a"],"at":"2026-11-11T21:16:03.123456"}`), &got); err != nil {
		t.Fatal(err)
	}
	got = renumber(t, got)
	ok := map[string]any{"id": AnyUUID, "n": 3, "tags": Unordered("a", "b"), "at": AnyTimestamp}
	if err := Compare(got, ok); err != nil {
		t.Fatalf("want a match: %v", err)
	}
	for name, want := range map[string]map[string]any{
		"extra key":   {"id": AnyUUID, "n": 3, "tags": Any},
		"missing key": {"id": AnyUUID, "n": 3, "tags": Any, "at": Any, "more": nil},
		"order":       {"id": AnyUUID, "n": 3, "tags": []any{"a", "b"}, "at": Any},
		"number":      {"id": AnyUUID, "n": 4, "tags": Any, "at": Any},
	} {
		if err := Compare(got, want); err == nil {
			t.Errorf("%s: want a difference", name)
		}
	}
}

func renumber(t *testing.T, v any) any {
	raw, _ := json.Marshal(v)
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.UseNumber()
	var out any
	if err := dec.Decode(&out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestStream(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			http.Error(w, "no", http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
		f := w.(http.Flusher)
		_, _ = fmt.Fprint(w, ": keepalive\n\nid: 1\nevent: a\ndata: one\ndata: two\n\n")
		f.Flush()
		_, _ = fmt.Fprint(w, "data: {\"k\":1}\r\n\r\n")
		f.Flush()
	}))
	defer srv.Close()
	c := newClient("test", srv.URL, func(testing.TB) string { return "tok" })
	s := c.Stream(t, "/events", 5*time.Second)
	evs := s.Take(2, 2*time.Second)
	if evs[0] != (Event{ID: "1", Event: "a", Data: "one\ntwo"}) || evs[1].Data != `{"k":1}` {
		t.Fatalf("events %+v", evs)
	}
	if _, err := s.TryNext(2 * time.Second); !errors.Is(err, io.EOF) {
		t.Fatalf("want EOF after the server closes, got %v", err)
	}
}

func TestWebSocket(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer tok" {
			http.Error(w, "no", http.StatusForbidden)
			return
		}
		sum := sha1.Sum([]byte(r.Header.Get("Sec-WebSocket-Key") + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")) //nolint:gosec // RFC 6455.
		conn, rw, err := w.(http.Hijacker).Hijack()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()
		_, _ = fmt.Fprintf(rw, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n",
			base64.StdEncoding.EncodeToString(sum[:]))
		serverFrame(rw.Writer, OpPing, []byte("p"))
		serverFrame(rw.Writer, OpText, []byte(`{"hello":"runner"}`))
		_ = rw.Flush()
		msg := readMasked(rw.Reader)
		if msg == "pong" {
			msg = readMasked(rw.Reader)
		}
		serverFrame(rw.Writer, OpText, []byte(msg))
		serverFrame(rw.Writer, OpClose, []byte{0x03, 0xF0, 'b', 'y', 'e'})
		_ = rw.Flush()
	}))
	defer srv.Close()

	refused := newClient("anon", srv.URL, nil)
	_, err := refused.TryDialWS(t, "/ws", nil)
	var he *WSHandshakeError
	if !errors.As(err, &he) || he.Status != http.StatusForbidden {
		t.Fatalf("want a 403 handshake error, got %v", err)
	}

	ws := newClient("test", srv.URL, func(testing.TB) string { return "tok" }).DialWS(t, "/ws", nil)
	var hello map[string]string
	ws.ReadJSON(2*time.Second, &hello)
	if hello["hello"] != "runner" {
		t.Fatalf("hello %v", hello)
	}
	ws.WriteJSON(map[string]int{"n": 7})
	var echo map[string]int
	ws.ReadJSON(2*time.Second, &echo)
	if echo["n"] != 7 {
		t.Fatalf("echo %v", echo)
	}
	if _, _, err := ws.Read(2 * time.Second); !errors.Is(err, io.EOF) || ws.CloseCode != 1008 || ws.CloseReason != "bye" {
		t.Fatalf("want close 1008 bye, got %v %d %q", err, ws.CloseCode, ws.CloseReason)
	}
}

func serverFrame(w *bufio.Writer, op int, payload []byte) {
	_ = w.WriteByte(0x80 | byte(op))
	_ = w.WriteByte(byte(len(payload)))
	_, _ = w.Write(payload)
}

func readMasked(r *bufio.Reader) string {
	var h [2]byte
	if _, err := io.ReadFull(r, h[:]); err != nil {
		return ""
	}
	n := int(h[1] & 0x7F)
	if n == 126 {
		var ext [2]byte
		_, _ = io.ReadFull(r, ext[:])
		n = int(binary.BigEndian.Uint16(ext[:]))
	}
	var mask [4]byte
	_, _ = io.ReadFull(r, mask[:])
	p := make([]byte, n)
	_, _ = io.ReadFull(r, p)
	for i := range p {
		p[i] ^= mask[i%4]
	}
	if h[0]&0x0F == OpPong {
		return "pong"
	}
	return string(p)
}
