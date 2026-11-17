package domain

import (
	"strconv"
	"strings"
)

// binaryExtension: writing a file with it as UTF-8 text corrupts the payload
// (file_toolset _BINARY_EXTENSIONS).
func binaryExtension(ext string) bool {
	switch ext {
	case "xlsx", "xls", "pptx", "ppt", "docx", "doc", "pdf", "zip", "gz", "tar", "png", "jpg", "jpeg", "gif",
		"webp", "bmp", "ico", "tiff", "mp3", "mp4", "wav", "ogg", "webm", "mov", "parquet", "sqlite", "db":
		return true
	}
	return false
}

// BinaryFileRefusal is save_file's answer for a binary extension; empty when the name is text.
func BinaryFileRefusal(fileName string) string {
	i := strings.LastIndexByte(fileName, '.')
	if i < 0 {
		return ""
	}
	ext := strings.ToLower(fileName[i+1:])
	if !binaryExtension(ext) {
		return ""
	}
	return "Error: save_file writes UTF-8 text only and would corrupt a ." + ext + " file. " +
		"Produce binary deliverables by running a program in the shell that writes the file into your workspace."
}

// FilePathRefusal is FileToolset._resolve's refusal of a path that escapes the working directory.
func FilePathRefusal(fileName string) string {
	if strings.HasPrefix(fileName, "/") || fileName == "" || strings.Contains(fileName, `\`) || containsDotDot(strings.Split(fileName, "/")) {
		return "path escapes workspace sandbox: " + PyStrRepr(fileName)
	}
	return ""
}

// FileListing is list_files' or search_files' JSON (json.dumps(..., indent=2)).
// countKey is files_found or matches_found; patternFirst puts pattern before scope.
func FileListing(pattern, countKey string, patternFirst bool, files []string) string {
	var b strings.Builder
	b.WriteString("{\n")
	field := func(k string) {
		b.WriteString("  ")
		pyString(&b, k, true)
		b.WriteString(": ")
	}
	if patternFirst {
		field("pattern")
		pyString(&b, pattern, true)
		b.WriteString(",\n")
		field("scope")
		pyString(&b, "/", true)
	} else {
		field("scope")
		pyString(&b, "/", true)
		b.WriteString(",\n")
		field("pattern")
		pyString(&b, pattern, true)
	}
	b.WriteString(",\n")
	field(countKey)
	b.WriteString(strconv.Itoa(len(files)))
	b.WriteString(",\n")
	field("files")
	if len(files) == 0 {
		b.WriteString("[]")
	} else {
		b.WriteString("[\n")
		for i, f := range files {
			b.WriteString("    ")
			pyString(&b, f, true)
			if i < len(files)-1 {
				b.WriteByte(',')
			}
			b.WriteByte('\n')
		}
		b.WriteString("  ]")
	}
	b.WriteString("\n}")
	return b.String()
}
