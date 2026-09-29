package packageimage

import (
	"reflect"
	"testing"
)

func TestParseInvocation(t *testing.T) {
	tests := []struct {
		name    string
		command []string
		want    Invocation
		wantErr bool
	}{
		{name: "npx default", command: []string{"npx", "@scope/server"}, want: Invocation{Ecosystem: EcosystemNPM, Package: "@scope/server"}},
		{name: "npx exact", command: []string{"npx", "pkg@1.2.3"}, want: Invocation{Ecosystem: EcosystemNPM, Package: "pkg", Version: "1.2.3"}},
		{name: "npx latest executable args", command: []string{"npx", "--yes", "--package=@scope/server@latest", "serve", "--port", "4"}, want: Invocation{Ecosystem: EcosystemNPM, Package: "@scope/server", Version: "latest", Executable: "serve", Args: []string{"--port", "4"}}},
		{name: "uvx from executable", command: []string{"uvx", "--from", "my_pkg==2.0.0", "my-command", "--debug"}, want: Invocation{Ecosystem: EcosystemPyPI, Package: "my_pkg", Version: "2.0.0", Executable: "my-command", Args: []string{"--debug"}}},
		{name: "uvx package at latest", command: []string{"uvx", "my.pkg@latest"}, want: Invocation{Ecosystem: EcosystemPyPI, Package: "my.pkg", Version: "latest"}},
		{name: "npx unsupported flag", command: []string{"npx", "--ignore-scripts", "pkg"}, wantErr: true},
		{name: "uvx extras", command: []string{"uvx", "--from", "pkg[extra]", "cmd"}, wantErr: true},
		{name: "npm range", command: []string{"npx", "pkg@^1.2.0"}, wantErr: true},
		{name: "pypi marker", command: []string{"uvx", "pkg; python_version<'3.12'"}, wantErr: true},
		{name: "missing package", command: []string{"npx", "--package"}, wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := ParseInvocation(tt.command)
			if tt.wantErr {
				if err == nil {
					t.Fatal("ParseInvocation() error = nil, want error")
				}
				return
			}
			if err != nil {
				t.Fatalf("ParseInvocation() error = %v", err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("ParseInvocation() = %#v, want %#v", got, tt.want)
			}
		})
	}
}

func TestPackageRepositoryPathAndTag(t *testing.T) {
	if got := RepositoryPath(EcosystemNPM, "@Scope/Name"); got != "npm/scope/name" {
		t.Fatalf("RepositoryPath() = %q", got)
	}
	if got := RepositoryPath(EcosystemPyPI, "My_Package.Name"); got != "pypi/my-package-name" {
		t.Fatalf("RepositoryPath() = %q", got)
	}
	if got := ImageTag("1.2.3+cpu/arm"); got != "1.2.3_cpu-arm" {
		t.Fatalf("ImageTag() = %q", got)
	}
}
