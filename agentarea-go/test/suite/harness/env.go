//go:build suite

package harness

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
)

// Env is what a suite run is pointed at.
type Env struct {
	BaseURL      string
	KratosPublic string
	KratosAdmin  string
}

//nolint:gochecknoglobals // one environment per test process
var (
	envOnce sync.Once
	envVal  Env
	envErr  error
)

func loadEnv() (Env, error) {
	envOnce.Do(func() {
		need := func(name string) string {
			v := strings.TrimRight(os.Getenv(name), "/")
			if v == "" && envErr == nil {
				envErr = fmt.Errorf("%s is required (see test/suite/README.md; `deploy/suite/stack.sh env` prints it)", name)
			}
			return v
		}
		envVal = Env{
			BaseURL:      need("BASE_URL"),
			KratosPublic: need("SUITE_KRATOS_PUBLIC_URL"),
			KratosAdmin:  need("SUITE_KRATOS_ADMIN_URL"),
		}
	})
	return envVal, envErr
}

// Current returns the run's environment, failing the test when it is incomplete.
func Current(t testing.TB) Env {
	t.Helper()
	env, err := loadEnv()
	if err != nil {
		t.Fatal(err)
	}
	return env
}

// Main is a suite package's TestMain: it refuses to run without the
// environment and deletes the identities the run minted once it is done.
func Main(m *testing.M) {
	if _, err := loadEnv(); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, "suite:", err)
		os.Exit(2)
	}
	code := m.Run()
	deleteIdentities()
	os.Exit(code)
}
