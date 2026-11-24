package service

import (
	"net/http"
	"regexp"
	"strings"

	"golang.org/x/text/unicode/norm"
)

// AttachmentDisposition is attachment_content_disposition.
func AttachmentDisposition(filename, fallback string) string {
	var ascii strings.Builder
	for _, r := range norm.NFKD.String(filename) {
		if r < 0x80 {
			ascii.WriteRune(r)
		}
	}
	unsafe := regexp.MustCompile(`[^A-Za-z0-9._-]+`)
	fb := strings.Trim(unsafe.ReplaceAllString(ascii.String(), "_"), "._-")
	if fb == "" {
		fb = fallback
	}
	return `attachment; filename="` + fb + `"; filename*=UTF-8''` + QuoteAll(filename)
}

// DownloadHeaders is secure_download_headers with no upstream disposition:
// always an attachment, whatever the content type.
func DownloadHeaders(contentType, filename, fallback string) http.Header {
	return SecureDownloadHeaders(contentType, filename, "", fallback)
}

// SecureDownloadHeaders is secure_download_headers: an upstream disposition is
// kept unless the content type is one a browser executes inline.
func SecureDownloadHeaders(contentType, filename, disposition, fallback string) http.Header {
	mediaType, _, _ := strings.Cut(contentType, ";")
	switch strings.ToLower(strings.TrimSpace(mediaType)) {
	case "text/html", "application/xhtml+xml", "image/svg+xml", "text/xml", "application/xml":
		disposition = ""
	}
	if disposition == "" {
		disposition = AttachmentDisposition(filename, fallback)
	}
	h := http.Header{}
	h.Set("Content-Disposition", disposition)
	h.Set("X-Content-Type-Options", "nosniff")
	return h
}

// quote is urllib.parse.quote over UTF-8 with safe extra characters.
func quote(s, safe string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := range len(s) {
		c := s[i]
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.IndexByte("_.-~", c) >= 0 || strings.IndexByte(safe, c) >= 0 {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hex[c>>4])
		b.WriteByte(hex[c&15])
	}
	return b.String()
}

// QuoteAll is quote(s, safe="").
func QuoteAll(s string) string { return quote(s, "") }

// QuotePath is quote(s, safe="/").
func QuotePath(s string) string { return quote(s, "/") }
