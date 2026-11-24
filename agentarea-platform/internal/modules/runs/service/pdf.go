package service

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"
)

// read_file's PDF rules, as Claude Code's Read keeps them: a PDF over
// pdfPagesWithoutRange pages needs pages, and one read takes at most
// maxPDFPagesPerRead.
const (
	pdfPagesWithoutRange = 10
	maxPDFPagesPerRead   = 20
)

// pdfConfig never reads or writes a pdfcpu config directory.
func pdfConfig() *model.Configuration {
	conf := model.NewStatelessConfiguration()
	conf.ValidationMode = model.ValidationRelaxed
	return conf
}

// pdfCall runs fn, turning a panic in the PDF parser into an error.
func pdfCall(fn func() error) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("the PDF parser failed: %v", r)
		}
	}()
	return fn()
}

// pdfPageCount is how many pages data has.
func pdfPageCount(ctx context.Context, data []byte) (int, error) {
	var n int
	err := pdfCall(func() error {
		var err error
		n, err = api.PageCount(ctx, bytes.NewReader(data), pdfConfig())
		return err
	})
	if err != nil {
		return 0, fmt.Errorf("not a readable PDF: %w", err)
	}
	return n, nil
}

// pdfSelectPages is data cut down to pages from through to, 1-based.
func pdfSelectPages(ctx context.Context, data []byte, from, to int) ([]byte, error) {
	var out bytes.Buffer
	err := pdfCall(func() error {
		return api.Trim(ctx, bytes.NewReader(data), &out, []string{fmt.Sprintf("%d-%d", from, to)}, pdfConfig())
	})
	if err != nil {
		return nil, fmt.Errorf("could not cut pages %d-%d: %w", from, to, err)
	}
	return out.Bytes(), nil
}

// parsePages is read_file's pages, "3" or "2-5", as a 1-based range.
func parsePages(s string) (int, int, error) {
	bad := errors.New(`pages is one page or a range, e.g. "3" or "1-5"`)
	a, b, isRange := strings.Cut(s, "-")
	from, err := strconv.Atoi(strings.TrimSpace(a))
	if err != nil || from < 1 {
		return 0, 0, bad
	}
	to := from
	if isRange {
		if to, err = strconv.Atoi(strings.TrimSpace(b)); err != nil || to < from {
			return 0, 0, bad
		}
	}
	return from, to, nil
}

// readPDF is read_file of a PDF: the pages asked for, attached as a PDF file.
func readPDF(ctx context.Context, name string, data []byte, pages string) (ToolOutput, string) {
	total, err := pdfPageCount(ctx, data)
	if err != nil {
		return ToolOutput{}, err.Error()
	}
	from, to := 1, total
	if pages == "" {
		if total > pdfPagesWithoutRange {
			return ToolOutput{Success: true, Source: "builtin", Result: fmt.Sprintf(
				"%s has %d pages; read up to %d at a time with pages, e.g. pages: \"1-5\".", name, total, maxPDFPagesPerRead)}, ""
		}
	} else if from, to, err = parsePages(pages); err != nil {
		return ToolOutput{}, err.Error()
	}
	switch {
	case to > total:
		return ToolOutput{}, fmt.Sprintf("pages %s is past the last page, %d", pages, total)
	case to-from+1 > maxPDFPagesPerRead:
		return ToolOutput{}, fmt.Sprintf("pages %s is %d pages; read up to %d at a time", pages, to-from+1, maxPDFPagesPerRead)
	}
	file := data
	if from != 1 || to != total {
		if file, err = pdfSelectPages(ctx, data, from, to); err != nil {
			return ToolOutput{}, err.Error()
		}
	}
	return ToolOutput{Success: true, Source: "builtin",
		Result: fmt.Sprintf("%s: pages %d-%d of %d (PDF); it is attached.", name, from, to, total),
		Images: []ToolImage{{Data: file, MimeType: pdfMimeType, Pages: to - from + 1}}}, ""
}

// readLines is offset and limit of a text file's lines, 1-based.
func readLines(text string, offset, limit int) (string, string) {
	lines := strings.Split(text, "\n")
	if offset < 1 {
		offset = 1
	}
	if offset > len(lines) {
		return "", fmt.Sprintf("offset %d is past the last line, %d", offset, len(lines))
	}
	end := len(lines)
	if limit > 0 && offset-1+limit < end {
		end = offset - 1 + limit
	}
	out := strings.Join(lines[offset-1:end], "\n")
	if end < len(lines) {
		out += fmt.Sprintf("\n[lines %d-%d of %d; read on with offset: %d]", offset, end, len(lines), end+1)
	}
	return out, ""
}
