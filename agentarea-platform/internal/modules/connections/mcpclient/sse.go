package mcpclient

import (
	"bufio"
	"io"
	"strings"
)

// event is one server-sent event.
type event struct {
	Name string
	Data string
	ID   string
}

// sseReader reads text/event-stream events (WHATWG parsing, comments and
// retry ignored).
type sseReader struct {
	r *bufio.Reader
}

func newSSEReader(r io.Reader) *sseReader {
	return &sseReader{r: bufio.NewReaderSize(r, 64*1024)}
}

// next returns the next dispatched event; io.EOF when the stream ends.
func (s *sseReader) next() (event, error) {
	var ev event
	var data []string
	seen := false
	for {
		line, err := s.r.ReadString('\n')
		if err != nil && (line == "" || err != io.EOF) {
			if seen && err == io.EOF {
				return dispatch(ev, data), nil
			}
			return event{}, err
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			if !seen {
				if err == io.EOF {
					return event{}, io.EOF
				}
				continue
			}
			return dispatch(ev, data), nil
		}
		if strings.HasPrefix(line, ":") {
			continue
		}
		field, value, _ := strings.Cut(line, ":")
		value = strings.TrimPrefix(value, " ")
		switch field {
		case "event":
			ev.Name, seen = value, true
		case "data":
			data, seen = append(data, value), true
		case "id":
			ev.ID = value
		}
		if err == io.EOF {
			return dispatch(ev, data), nil
		}
	}
}

func dispatch(ev event, data []string) event {
	ev.Data = strings.Join(data, "\n")
	if ev.Name == "" {
		ev.Name = "message"
	}
	return ev
}
