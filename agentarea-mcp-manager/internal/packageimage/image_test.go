package packageimage

import (
	"archive/tar"
	"os"
	"testing"

	"github.com/google/go-containerregistry/pkg/v1/mutate"
	"github.com/google/go-containerregistry/pkg/v1/random"
)

func TestAssembleImageRetainsBaseProcessConfigAndAddsLabels(t *testing.T) {
	base, err := random.Image(1, 1024)
	if err != nil {
		t.Fatal(err)
	}
	config, err := base.ConfigFile()
	if err != nil {
		t.Fatal(err)
	}
	config.Config.Entrypoint = []string{"/bin/base"}
	config.Config.Cmd = []string{"--serve"}
	config.Config.Env = []string{"BASE=1"}
	base, err = mutate.Config(base, config.Config)
	if err != nil {
		t.Fatal(err)
	}

	layerPath := t.TempDir() + "/layer.tar"
	file, err := os.Create(layerPath)
	if err != nil {
		t.Fatal(err)
	}
	tarWriter := tar.NewWriter(file)
	if err := tarWriter.WriteHeader(&tar.Header{Name: "opt/", Mode: 0o755, Typeflag: tar.TypeDir}); err != nil {
		t.Fatal(err)
	}
	if err := tarWriter.WriteHeader(&tar.Header{Name: "opt/mcp-pkg/", Mode: 0o755, Typeflag: tar.TypeDir}); err != nil {
		t.Fatal(err)
	}
	body := []byte("payload")
	if err := tarWriter.WriteHeader(&tar.Header{Name: "opt/mcp-pkg/bin", Mode: 0o755, Size: int64(len(body))}); err != nil {
		t.Fatal(err)
	}
	if _, err := tarWriter.Write(body); err != nil {
		t.Fatal(err)
	}
	if err := tarWriter.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}

	assembled, err := AssembleImage(base, layerPath, Package{Ecosystem: EcosystemNPM, Name: "pkg", Version: "1.2.3"}, []string{"/opt/mcp-pkg/bin", "--x"})
	if err != nil {
		t.Fatal(err)
	}
	assembledConfig, err := assembled.ConfigFile()
	if err != nil {
		t.Fatal(err)
	}
	if got := assembledConfig.Config.Entrypoint; len(got) != 1 || got[0] != "/bin/base" {
		t.Fatalf("entrypoint = %v", got)
	}
	if got := assembledConfig.Config.Cmd; len(got) != 1 || got[0] != "--serve" {
		t.Fatalf("cmd = %v", got)
	}
	if got := assembledConfig.Config.Env; len(got) != 1 || got[0] != "BASE=1" {
		t.Fatalf("env = %v", got)
	}
	if assembledConfig.Config.Labels["io.agentarea.mcp.package"] != "npm:pkg@1.2.3" {
		t.Fatalf("package label = %q", assembledConfig.Config.Labels["io.agentarea.mcp.package"])
	}
	if assembledConfig.Config.Labels["io.agentarea.mcp.entrypoint"] == "" {
		t.Fatal("entrypoint label is empty")
	}
	manifest, err := assembled.Manifest()
	if err != nil {
		t.Fatal(err)
	}
	if len(manifest.Layers) < 2 {
		t.Fatalf("layers = %d, want base plus package", len(manifest.Layers))
	}
}
