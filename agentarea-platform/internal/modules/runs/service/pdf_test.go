package service

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"testing"
)

// pdfOf is a valid PDF of n blank pages.
func pdfOf(n int) []byte {
	var b bytes.Buffer
	var offsets []int
	obj := func(body string) {
		offsets = append(offsets, b.Len())
		fmt.Fprintf(&b, "%d 0 obj\n%s\nendobj\n", len(offsets), body)
	}
	b.WriteString("%PDF-1.7\n")
	obj("<< /Type /Catalog /Pages 2 0 R >>")
	kids := make([]string, n)
	for i := range kids {
		kids[i] = fmt.Sprintf("%d 0 R", i+3)
	}
	obj(fmt.Sprintf("<< /Type /Pages /Kids [%s] /Count %d >>", strings.Join(kids, " "), n))
	for range n {
		obj("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>")
	}
	xref := b.Len()
	fmt.Fprintf(&b, "xref\n0 %d\n0000000000 65535 f \n", len(offsets)+1)
	for _, o := range offsets {
		fmt.Fprintf(&b, "%010d 00000 n \n", o)
	}
	fmt.Fprintf(&b, "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(offsets)+1, xref)
	return b.Bytes()
}

func TestPDFPagesCountsAndCuts(t *testing.T) {
	ctx := context.Background()
	if n, err := pdfPageCount(ctx, pdfOf(7)); err != nil || n != 7 {
		t.Fatalf("count %d %v", n, err)
	}
	cut, err := pdfSelectPages(ctx, pdfOf(30), 3, 5)
	if err != nil {
		t.Fatal(err)
	}
	if n, err := pdfPageCount(ctx, cut); err != nil || n != 3 {
		t.Fatalf("cut has %d pages, %v", n, err)
	}
	if _, err := pdfPageCount(ctx, []byte("%PDF-1.7\nnot really")); err == nil {
		t.Fatal("a broken PDF was counted")
	}
}

func TestParsePagesTakesARangeOfOneBasedPages(t *testing.T) {
	for in, want := range map[string][2]int{"3": {3, 3}, "2-5": {2, 5}, " 1 - 20 ": {1, 20}} {
		if from, to, err := parsePages(in); err != nil || from != want[0] || to != want[1] {
			t.Fatalf("%q = %d-%d %v", in, from, to, err)
		}
	}
	for _, bad := range []string{"", "0", "5-2", "a", "1-", "1,3"} {
		if _, _, err := parsePages(bad); err == nil {
			t.Fatalf("%q accepted", bad)
		}
	}
}
