package mcpgateway

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/models"
)

func policyFrom(t *testing.T, repositories, packages string) (ImagePolicy, error) {
	t.Helper()
	t.Setenv("MCP_ALLOWED_IMAGE_REPOSITORIES", repositories)
	t.Setenv("MCP_ALLOWED_COMMAND_PACKAGES", packages)
	return LoadImagePolicyFromEnv()
}

// An operator who has not declared the lists has not decided what may run.
// Reading that as "everything" is the exact failure this gate replaces, because
// on a cluster without a sandboxing runtime nothing else stops the image.
func TestAbsentListsAreRefusedRatherThanReadAsAllowAll(t *testing.T) {
	for _, absent := range []string{"MCP_ALLOWED_IMAGE_REPOSITORIES", "MCP_ALLOWED_COMMAND_PACKAGES"} {
		t.Run(absent, func(t *testing.T) {
			t.Setenv("MCP_ALLOWED_IMAGE_REPOSITORIES", "ghcr.io/agentarea/mcp")
			t.Setenv("MCP_ALLOWED_COMMAND_PACKAGES", "")
			// t.Setenv registers the restore; Unsetenv then makes it genuinely absent.
			if err := os.Unsetenv(absent); err != nil {
				t.Fatal(err)
			}
			if _, err := LoadImagePolicyFromEnv(); err == nil {
				t.Fatalf("%s missing was accepted", absent)
			}
		})
	}
}

func TestTwoEmptyListsAreRefusedBecauseNothingCouldStart(t *testing.T) {
	if _, err := policyFrom(t, "", ""); err == nil {
		t.Fatal("a policy admitting nothing at all was accepted as configuration")
	}
}

// Padding and stray separators are formatting, not intent: a list that means
// one repository must not depend on how the operator spaced it.
func TestListFormattingDoesNotChangeWhatIsAdmitted(t *testing.T) {
	policy, err := policyFrom(t, "  ghcr.io/agentarea/mcp , , ", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := policy.AuthorizeImage("ghcr.io/agentarea/mcp:1.0", nil); err != nil {
		t.Fatalf("a padded entry was not admitted: %v", err)
	}
	if err := policy.AuthorizeImage("docker.io/attacker/mcp", nil); err == nil {
		t.Fatal("stray separators widened the list")
	}
}

func TestAllowedRepositoryAdmitsAnyTagOrDigest(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/mcp", "")
	if err != nil {
		t.Fatal(err)
	}
	for _, image := range []string{
		"ghcr.io/agentarea/mcp",
		"ghcr.io/agentarea/mcp:1.4.2",
		"ghcr.io/agentarea/mcp@sha256:" + strings.Repeat("a", 64),
	} {
		if err := policy.AuthorizeImage(image, nil); err != nil {
			t.Fatalf("AuthorizeImage(%q, nil) = %v", image, err)
		}
	}
}

func TestRegistryPortIsNotMistakenForATag(t *testing.T) {
	policy, err := policyFrom(t, "registry.internal:5000/agentarea/mcp", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := policy.AuthorizeImage("registry.internal:5000/agentarea/mcp:2.0", nil); err != nil {
		t.Fatalf("a registry port was stripped as if it were a tag: %v", err)
	}
}

func TestUndeclaredRepositoryIsRefused(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/mcp", "")
	if err != nil {
		t.Fatal(err)
	}
	for _, image := range []string{
		"docker.io/attacker/mcp:1.0",
		"ghcr.io/agentarea/mcp-evil:1.0",
		"",
		"   ",
	} {
		if err := policy.AuthorizeImage(image, nil); err == nil {
			t.Fatalf("AuthorizeImage(%q, nil) admitted an undeclared image", image)
		}
	}
}

// A command-type instance runs our own bridge image, so an image-only gate
// would wave it through while it fetches and executes an arbitrary package.
func TestCommandInstancesAreGatedSeparatelyFromImages(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/mcp", "mcp-server-notion")
	if err != nil {
		t.Fatal(err)
	}
	if err := policy.AuthorizeCommand("mcp-server-notion", nil); err != nil {
		t.Fatalf("AuthorizeCommand admitted nothing: %v", err)
	}
	for _, command := range []string{"curl", "mcp-server-evil", "", "  "} {
		if err := policy.AuthorizeCommand(command, nil); err == nil {
			t.Fatalf("AuthorizeCommand(%q) admitted an undeclared package", command)
		}
	}
}

// Admitting the interpreter would admit everything it can fetch, so the
// arguments are part of the decision: `npx` is not a package, `npx -y <pkg>` is.
func TestAllowingOneNpxPackageDoesNotAllowEveryNpxPackage(t *testing.T) {
	const admitted = "npx -y @modelcontextprotocol/server-everything"
	policy, err := policyFrom(t, "ghcr.io/agentarea/mcp", admitted)
	if err != nil {
		t.Fatal(err)
	}
	if err := policy.AuthorizeCommand("npx", []string{"-y", "@modelcontextprotocol/server-everything"}); err != nil {
		t.Fatalf("the declared invocation was refused: %v", err)
	}
	refused := [][]string{
		nil,
		{"-y", "@attacker/exfiltrate"},
		{"-y", "--package=@attacker/exfiltrate", "@modelcontextprotocol/server-everything"},
		{"-y", "@modelcontextprotocol/server-everything", "--extra"},
	}
	for _, args := range refused {
		if err := policy.AuthorizeCommand("npx", args); err == nil {
			t.Fatalf("npx %v was admitted by a policy that only declared %q", args, admitted)
		}
	}
}

// An allowlist entry names a package, and a package only means something
// together with the registry it is fetched from. Environment that moves the
// launcher off that registry leaves the invocation matching while changing the
// code, so it has to be refused rather than carried into the pod.
func TestLauncherEnvironmentCannotRedirectPackageResolution(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/mcp", "npx -y @modelcontextprotocol/server-everything")
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{
		// Name another index outright.
		"npm_config_registry", "NPM_CONFIG_REGISTRY", "NPM_CONFIG_USERCONFIG",
		"UV_INDEX_URL", "UV_DEFAULT_INDEX", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
		// Route the fetch through a host the caller controls.
		"HTTP_PROXY", "https_proxy", "ALL_PROXY",
		// Keep the address but break the proof of who answered.
		"NODE_TLS_REJECT_UNAUTHORIZED", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
		"REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_NO_VERIFY",
		// Change which binary or config is found at all.
		"PATH", "HOME", "PYTHONPATH", "NODE_OPTIONS", "NODE_PATH",
	} {
		if err := policy.AuthorizeLauncherEnvironment(map[string]string{name: "https://attacker.tld/"}); err == nil {
			t.Fatalf("%s was accepted; the declared package could be fetched from anywhere", name)
		}
	}
	if err := policy.AuthorizeLauncherEnvironment(map[string]string{"NOTION_TOKEN": "secret"}); err != nil {
		t.Fatalf("ordinary server configuration was refused: %v", err)
	}
}

// An image is vouched for as published. Choosing its argv makes it a different
// program, so a repository-only entry must not admit a command override.
func TestImageEntryDoesNotAdmitACallerChosenCommand(t *testing.T) {
	policy, err := policyFrom(t, "mcp/fetch", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := policy.AuthorizeImage("mcp/fetch:latest", nil); err != nil {
		t.Fatalf("the declared image was refused: %v", err)
	}
	if err := policy.AuthorizeImage("mcp/fetch:latest", []string{"--proxy-url", "http://attacker.tld"}); err == nil {
		t.Fatal("a repository entry admitted a caller-chosen command override")
	}

	withCommand, err := policyFrom(t, "mcp/fetch --ignore-robots-txt", "")
	if err != nil {
		t.Fatal(err)
	}
	if err := withCommand.AuthorizeImage("mcp/fetch:latest", []string{"--ignore-robots-txt"}); err != nil {
		t.Fatalf("the declared invocation was refused: %v", err)
	}
	if err := withCommand.AuthorizeImage("mcp/fetch:latest", nil); err == nil {
		t.Fatal("an invocation entry admitted the bare image it does not describe")
	}
}

func TestContainerCommandOverrideMirrorsTheProviderStrip(t *testing.T) {
	got := containerCommandOverride(map[string]any{
		"command": []any{"server", "--transport=stdio", "--root", "/data"},
	})
	if strings.Join(got, " ") != "server --root /data" {
		t.Fatalf("override = %v", got)
	}
}

func TestInstanceEnvironmentReadsBothSpecKeys(t *testing.T) {
	got := instanceEnvironment(map[string]any{
		"environment": map[string]any{"A": "1"},
		"env_vars":    map[string]any{"B": 2},
	})
	if got["A"] != "1" || got["B"] != "2" {
		t.Fatalf("environment = %v", got)
	}
}

// The environment check has to sit on the path EnsureReady takes, not only in
// the policy type: a declared invocation carrying a redirected registry must be
// refused before any workload is inspected or created.
func TestRedirectedRegistryIsRefusedOnTheAdmissionPath(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/allowed-mcp", "npx -y @modelcontextprotocol/server-everything")
	if err != nil {
		t.Fatal(err)
	}
	backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	runtime.imagePolicy = policy

	instance := &models.MCPServerInstance{
		InstanceID: "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		Name:       "8ca9f331-9cc9-4a51-9933-27d7bb73860b",
		JSONSpec: map[string]any{
			"type":        "command",
			"command":     "npx",
			"args":        []any{"-y", "@modelcontextprotocol/server-everything"},
			"environment": map[string]any{"npm_config_registry": "https://attacker.tld/"},
		},
	}

	if _, err := runtime.EnsureReady(context.Background(), instance); err == nil {
		t.Fatal("a declared invocation was admitted while pointed at another registry")
	}

	delete(instance.JSONSpec, "environment")
	if _, err := runtime.EnsureReady(context.Background(), instance); err != nil {
		t.Fatalf("the same invocation without the redirect was refused: %v", err)
	}
}

// The gate reads the arguments the provider will actually run, not a
// differently-shaped copy of them.
func TestCommandArgsAreReadTheSameWayTheProviderBuildsThem(t *testing.T) {
	args := commandArgs(map[string]any{"args": []any{"-y", "@scope/pkg"}})
	if strings.Join(args, " ") != "-y @scope/pkg" {
		t.Fatalf("unexpected args: %v", args)
	}
	if got := commandArgs(map[string]any{}); got != nil {
		t.Fatalf("a spec without args yielded %v", got)
	}
}

// The security property, stated at the level that matters: a refused instance
// must not reach the data plane at all.
func TestRefusedInstanceNeverReachesTheDataPlane(t *testing.T) {
	t.Setenv("MCP_ALLOWED_IMAGE_REPOSITORIES", "ghcr.io/agentarea/allowed-mcp")
	t.Setenv("MCP_ALLOWED_COMMAND_PACKAGES", "")
	policy, err := LoadImagePolicyFromEnv()
	if err != nil {
		t.Fatal(err)
	}

	backend := &runtimeBackendStub{statuses: []statusReply{{err: nil}}}
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	runtime.imagePolicy = policy

	instance := dockerInstance()
	instance.JSONSpec["image"] = "docker.io/attacker/mcp:latest"

	if _, err := runtime.EnsureReady(context.Background(), instance); err == nil {
		t.Fatal("an undeclared image was activated")
	}
	if creates, deletes := provider.counts(); creates != 0 || deletes != 0 {
		t.Fatalf("creates=%d deletes=%d; a refused instance still touched the data plane", creates, deletes)
	}
	if backend.statusCall != 0 {
		t.Fatalf("statusCall=%d; admission ran after the workload was inspected", backend.statusCall)
	}
}

// An instance edited to something inadmissible must stop being served, not keep
// answering from the workload it was granted under the previous spec.
func TestEditedInstanceIsRefusedEvenWithALiveWorkload(t *testing.T) {
	policy, err := policyFrom(t, "ghcr.io/agentarea/allowed-mcp", "")
	if err != nil {
		t.Fatal(err)
	}
	backend := &runtimeBackendStub{statuses: []statusReply{{status: "running"}}}
	provider := &runtimeProviderStub{}
	runtime := testProviderRuntime(t, backend, provider, time.Second)
	runtime.imagePolicy = policy

	instance := dockerInstance()
	instance.JSONSpec["image"] = "docker.io/attacker/mcp:latest"

	if _, err := runtime.EnsureReady(context.Background(), instance); err == nil {
		t.Fatal("a running workload kept serving an image that is no longer admissible")
	}
}
