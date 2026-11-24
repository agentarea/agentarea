package service

import (
	"bytes"
	"encoding/binary"
	"hash/crc32"
	"image"
	"image/png"
	"testing"
)

func pngBytes(t *testing.T, w, h int) []byte {
	t.Helper()
	var b bytes.Buffer
	if err := png.Encode(&b, image.NewRGBA(image.Rect(0, 0, w, h))); err != nil {
		t.Fatal(err)
	}
	return b.Bytes()
}

func TestInspectImageReadsAWholeImage(t *testing.T) {
	info, ok, err := inspectImage(pngBytes(t, 40, 30))
	if err != nil || !ok || info != (imageInfo{MimeType: "image/png", Width: 40, Height: 30}) {
		t.Fatalf("%+v %v %v", info, ok, err)
	}
}

func TestInspectImageLeavesOtherFilesAlone(t *testing.T) {
	for _, data := range [][]byte{[]byte("hello"), []byte("%PDF-1.7\n"), {}} {
		if _, ok, err := inspectImage(data); ok || err != nil {
			t.Fatalf("%q: ok %v err %v", data, ok, err)
		}
	}
}

func TestInspectImageRefusesABrokenOrHugeImage(t *testing.T) {
	data := pngBytes(t, 4, 4)
	if _, ok, err := inspectImage(data[:40]); !ok || err == nil {
		t.Fatalf("truncated: ok %v err %v", ok, err)
	}
	huge := append([]byte(nil), data...)
	binary.BigEndian.PutUint32(huge[16:20], 60000)
	binary.BigEndian.PutUint32(huge[20:24], 60000)
	binary.BigEndian.PutUint32(huge[29:33], crc32.ChecksumIEEE(huge[12:29]))
	if _, ok, err := inspectImage(huge); !ok || err == nil {
		t.Fatalf("60000x60000: ok %v err %v", ok, err)
	}
}
