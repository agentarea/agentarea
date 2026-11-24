package service

import (
	"bytes"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"net/http"

	_ "golang.org/x/image/webp"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

// maxImagePixels bounds the image a run decodes to check it.
const maxImagePixels = 100_000_000

// imageInfo is an image a run keeps, as it is.
type imageInfo struct {
	MimeType      string
	Width, Height int
}

// inspectImage is data as an image a model reads: a PNG, JPEG, GIF or WebP
// that decodes whole. ok is false when data is none of those formats; a
// broken one is an error, since a provider refuses it on every later call.
func inspectImage(data []byte) (imageInfo, bool, error) {
	mime := http.DetectContentType(data)
	switch mime {
	case "image/png", "image/jpeg", "image/gif", "image/webp":
	default:
		return imageInfo{}, false, nil
	}
	cfg, _, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		return imageInfo{}, true, fmt.Errorf("not a readable %s: %w", mime, err)
	}
	if cfg.Width <= 0 || cfg.Height <= 0 || cfg.Width*cfg.Height > maxImagePixels {
		return imageInfo{}, true, fmt.Errorf("%dx%d is over %d pixels", cfg.Width, cfg.Height, maxImagePixels)
	}
	if _, _, err := image.Decode(bytes.NewReader(data)); err != nil {
		return imageInfo{}, true, fmt.Errorf("not a readable %s: %w", mime, err)
	}
	return imageInfo{MimeType: mime, Width: cfg.Width, Height: cfg.Height}, true, nil
}

// imageReadNote is read_file's text for an image it attaches.
func imageReadNote(name string, info imageInfo, size int) string {
	return fmt.Sprintf("%s is an image (%s, %dx%d px, %s); it is attached.", name, info.MimeType, info.Width, info.Height, fileSize(size))
}

func fileSize(n int) string {
	if n < 1<<20 {
		return fmt.Sprintf("%d KB", (n+1023)/1024)
	}
	return fmt.Sprintf("%.1f MB", float64(n)/(1<<20))
}

const pdfMimeType = domain.PDFMimeType
