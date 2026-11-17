package domain

import (
	"errors"
	"fmt"
	"strings"
	"unicode"
)

// MaxWritePathBytes bounds a written path so the file stays archivable
// (service.py MAX_WRITE_PATH_BYTES).
const MaxWritePathBytes = 900

// TrashPrefix is where archived files live (service.py TRASH_PREFIX).
const TrashPrefix = ".trash/"

// MaxUploadsPerPlan is MAX_UPLOADS_PER_PLAN.
const MaxUploadsPerPlan = 100

// ValidationError is WorkspaceValidationError: a path a write may not take.
type ValidationError struct{ Msg string }

func (e *ValidationError) Error() string { return e.Msg }

// ReadOnlyError is WorkspaceReadOnlyError, a ValidationError under apps/.
type ReadOnlyError struct{ Msg string }

func (e *ReadOnlyError) Error() string { return e.Msg }

// ConflictError is WorkspaceConflictError.
type ConflictError struct{ Msg string }

func (e *ConflictError) Error() string { return e.Msg }

// QuotaError is WorkspaceQuotaError.
type QuotaError struct{ Msg string }

func (e *QuotaError) Error() string { return e.Msg }

// IsValidation reports a ValidationError or a ReadOnlyError (its subclass).
func IsValidation(err error) bool {
	var v *ValidationError
	var r *ReadOnlyError
	return errors.As(err, &v) || errors.As(err, &r)
}

// IsWorkspaceError is any WorkspaceError subclass.
func IsWorkspaceError(err error) bool {
	var c *ConflictError
	var q *QuotaError
	return IsValidation(err) || errors.As(err, &c) || errors.As(err, &q)
}

func invalid(format string, a ...any) error { return &ValidationError{Msg: fmt.Sprintf(format, a...)} }

// PyRepr is Python's repr of a str.
func PyRepr(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, "\"") {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == rune(quote):
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case !unicode.IsPrint(r) && r <= 0xff:
			fmt.Fprintf(&b, `\x%02x`, r)
		case !unicode.IsPrint(r) && r <= 0xffff:
			fmt.Fprintf(&b, `\u%04x`, r)
		case !unicode.IsPrint(r):
			fmt.Fprintf(&b, `\U%08x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// posixParts is PurePosixPath(p).parts: empty and "." segments dropped, a
// leading "/" kept as its own part (POSIX keeps "//" too).
func posixParts(p string) []string {
	var parts []string
	switch {
	case strings.HasPrefix(p, "//") && !strings.HasPrefix(p, "///"):
		parts = append(parts, "//")
	case strings.HasPrefix(p, "/"):
		parts = append(parts, "/")
	}
	for _, seg := range strings.Split(p, "/") {
		if seg == "" || seg == "." {
			continue
		}
		parts = append(parts, seg)
	}
	return parts
}

// PosixName is PurePosixPath(p).name.
func PosixName(p string) string {
	parts := posixParts(p)
	if len(parts) == 0 {
		return ""
	}
	last := parts[len(parts)-1]
	if strings.HasPrefix(last, "/") {
		return ""
	}
	return last
}

// PosixParts is PurePosixPath(p).parts.
func PosixParts(p string) []string { return posixParts(p) }

// NormalizeWorkspacePath is normalize_workspace_path: a canonical POSIX
// relative path or a ValidationError.
func NormalizeWorkspacePath(p string) (string, error) {
	if p == "" {
		return "", invalid("workspace path must be a non-empty string")
	}
	for _, r := range p {
		if r < 0x20 || r == 0x7f || r == '\\' {
			return "", invalid("workspace path is not canonical POSIX: %s", PyRepr(p))
		}
	}
	if strings.HasPrefix(p, "/") {
		return "", invalid("workspace path escapes task root: %s", PyRepr(p))
	}
	parts := posixParts(p)
	for _, part := range parts {
		if part == ".." {
			return "", invalid("workspace path escapes task root: %s", PyRepr(p))
		}
	}
	if strings.Join(parts, "/") != p {
		return "", invalid("workspace path is not canonical: %s", PyRepr(p))
	}
	return p, nil
}

func firstPart(p string) string {
	parts := posixParts(strings.TrimLeft(p, "/"))
	if len(parts) == 0 {
		return ""
	}
	return parts[0]
}

// IsReservedPath is is_reserved_path: tasks/, staging/, events/, .trash/.
func IsReservedPath(p string) bool {
	switch firstPart(p) {
	case "tasks", "staging", "events", ".trash":
		return true
	}
	return false
}

// IsReadOnlyPath is is_read_only_path: apps/ belongs to MCP apps.
func IsReadOnlyPath(p string) bool { return firstPart(p) == "apps" }

// EnsureNotReadOnly is ensure_not_read_only.
func EnsureNotReadOnly(p string) error {
	if IsReadOnlyPath(p) {
		return &ReadOnlyError{Msg: PyRepr(strings.TrimLeft(p, "/")) + " belongs to an MCP app and is read-only; only the app itself can change it"}
	}
	return nil
}

// ResolveWritePath is resolve_write_path.
func ResolveWritePath(p, filename string) (string, error) {
	if p == "" {
		if filename == "" {
			filename = "unnamed"
		}
		p = PosixName(filename)
		if p == "" {
			p = "unnamed"
		}
	}
	resolved, err := NormalizeWorkspacePath(p)
	if err != nil {
		return "", err
	}
	if len(resolved) > MaxWritePathBytes {
		return "", invalid("workspace path exceeds %d bytes of UTF-8", MaxWritePathBytes)
	}
	if IsReservedPath(resolved) {
		return "", invalid("%s is a reserved prefix and cannot be written directly", PyRepr(resolved))
	}
	if err := EnsureNotReadOnly(resolved); err != nil {
		return "", err
	}
	return resolved, nil
}

// TaskWorkspacePath is _task_workspace_path: tasks/{id}/workspace/{path},
// ok false for any other path.
func TaskWorkspacePath(filePath string) (taskID, rel string, ok bool, err error) {
	clean := strings.TrimLeft(filePath, "/")
	parts := posixParts(clean)
	if len(parts) < 4 || parts[0] != "tasks" || parts[2] != "workspace" {
		return "", "", false, nil
	}
	if clean != strings.Join(parts, "/") || strings.Contains(clean, "\\") {
		return "", "", true, invalid("workspace path is not canonical")
	}
	rel, err = NormalizeWorkspacePath(strings.Join(parts[3:], "/"))
	if err != nil {
		return "", "", true, err
	}
	return parts[1], rel, true, nil
}

// Parents is PurePosixPath(p).parents without ".": nearest first.
func Parents(p string) []string {
	parts := posixParts(p)
	var out []string
	for i := len(parts) - 1; i > 0; i-- {
		out = append(out, strings.Join(parts[:i], "/"))
	}
	return out
}
