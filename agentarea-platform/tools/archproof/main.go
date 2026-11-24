// Command archproof shows that the arch lint catches what it must and nothing
// else. It runs golangci-lint with the archviolation build tag and compares
// the issues with the markers in the tagged fixture files: every line marked
// "// want <linter>" must be reported by that linter, a line marked
// "// allowed" must not be reported, and nothing else may be reported.
//
//	go run ./tools/archproof -lint golangci-lint
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

const tag = "archviolation"

type key struct {
	file   string
	line   int
	linter string
}

type issue struct {
	FromLinter string
	Text       string
	Pos        struct {
		Filename string
		Line     int
	}
}

func main() {
	lint := flag.String("lint", "golangci-lint", "golangci-lint binary")
	flag.Parse()
	if err := run(*lint); err != nil {
		fmt.Fprintln(os.Stderr, "archproof:", err)
		os.Exit(1)
	}
}

func run(lint string) error {
	want, allowed, err := markers(".")
	if err != nil {
		return err
	}
	if len(want) == 0 {
		return errors.New("no fixture marks a violation")
	}
	got, err := issues(lint)
	if err != nil {
		return err
	}
	var problems []string
	reported := map[key]bool{}
	for _, is := range got {
		k := key{filepath.ToSlash(is.Pos.Filename), is.Pos.Line, is.FromLinter}
		reported[k] = true
		switch {
		case want[k]:
		case allowed[key{k.file, k.line, ""}]:
			problems = append(problems, fmt.Sprintf("%s:%d: allowed import reported by %s: %s", k.file, k.line, k.linter, is.Text))
		default:
			problems = append(problems, fmt.Sprintf("%s:%d: unexpected %s issue: %s", k.file, k.line, k.linter, is.Text))
		}
	}
	for k := range want {
		if !reported[k] {
			problems = append(problems, fmt.Sprintf("%s:%d: %s did not report the deliberate violation", k.file, k.line, k.linter))
		}
	}
	if len(problems) > 0 {
		sort.Strings(problems)
		return errors.New(strings.Join(problems, "\n"))
	}
	fmt.Printf("archproof: %d deliberate violations caught, %d allowed imports passed\n", len(want), len(allowed))
	return nil
}

// markers reads the want and allowed lines of every tagged fixture.
func markers(root string) (want, allowed map[key]bool, err error) {
	want, allowed = map[key]bool{}, map[key]bool{}
	err = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !strings.HasSuffix(path, "_"+tag+".go") {
			return nil
		}
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer func() { _ = f.Close() }()
		sc := bufio.NewScanner(f)
		for n := 1; sc.Scan(); n++ {
			_, comment, ok := strings.Cut(sc.Text(), "// ")
			if !ok {
				continue
			}
			fields := strings.Fields(comment)
			switch {
			case len(fields) == 2 && fields[0] == "want":
				want[key{filepath.ToSlash(path), n, fields[1]}] = true
			case len(fields) == 1 && fields[0] == "allowed":
				allowed[key{filepath.ToSlash(path), n, ""}] = true
			}
		}
		return sc.Err()
	})
	return want, allowed, err
}

func issues(lint string) ([]issue, error) {
	cmd := exec.Command(lint, "run", "--build-tags", tag,
		"--enable-only", "depguard,gochecknoglobals,gochecknoinits",
		"--output.json.path", "stdout", "--show-stats=false", "./...")
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	runErr := cmd.Run()
	var exit *exec.ExitError
	if runErr != nil && !errors.As(runErr, &exit) {
		return nil, runErr
	}
	var report struct{ Issues []issue }
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		return nil, fmt.Errorf("golangci-lint did not report issues (%w): %s%s", err, stdout.String(), stderr.String())
	}
	if runErr != nil && len(report.Issues) == 0 {
		return nil, fmt.Errorf("golangci-lint failed without issues: %s", stderr.String())
	}
	return report.Issues, nil
}
