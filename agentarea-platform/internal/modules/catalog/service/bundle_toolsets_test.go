package service

import (
	"errors"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

const mediaBundle = `
name: media
setup:
  - {key: picture, label: Picture model, type: string, default: us-image}
agents:
  - key: artist
    name: Artist
    model: us-model
    toolsets:
      - agentarea/files
      - name: agentarea/media
        image_model: "${setup.picture}"
        video_model: veo-3
`

func mediaToolsets() []BundleToolset {
	return []BundleToolset{{Name: "agentarea/files"}, {Name: "agentarea/media", ImageModel: strp("${setup.picture}"), VideoModel: strp("veo-3")}}
}

func TestBundleToolsetIsANameOrANameWithSettings(t *testing.T) {
	b := mustParse(t, mediaBundle)
	if got := b.Agents[0].Toolsets; !reflect.DeepEqual(got, mediaToolsets()) {
		t.Fatalf("toolsets = %+v", got)
	}
	dumped, _ := b.Agents[0].dump().Get("toolsets")
	want := []any{"agentarea/files", wirejson.Object{{Key: "name", Value: "agentarea/media"},
		{Key: "image_model", Value: "${setup.picture}"}, {Key: "video_model", Value: "veo-3"}}}
	if !reflect.DeepEqual(dumped, want) {
		t.Fatalf("dump = %#v", dumped)
	}
	var c checker
	again, ok := bundleAgentFrom(&c, b.Agents[0].dump(), nil)
	if !ok || !reflect.DeepEqual(again.Toolsets, mediaToolsets()) {
		t.Fatalf("reparsed = %+v, %v", again.Toolsets, c.errs)
	}
}

func TestBundleToolsetRefusesAMappingWithoutNameOrWithUnknownKeys(t *testing.T) {
	for _, tc := range []struct {
		entry any
		typ   string
		loc   []any
	}{
		{wirejson.Object{{Key: "image_model", Value: "flux"}}, "missing", []any{"toolsets", 0, "name"}},
		{wirejson.Object{{Key: "name", Value: "agentarea/media"}, {Key: "image", Value: "flux"}}, "extra_forbidden", []any{"toolsets", 0, "image"}},
		{wirejson.Object{{Key: "name", Value: "agentarea/media"}, {Key: "image_model", Value: []any{}}}, "string_type", []any{"toolsets", 0, "image_model"}},
		{5, "value_error", []any{"toolsets", 0}},
	} {
		var c checker
		_, ok := bundleAgentFrom(&c, wirejson.Object{{Key: "key", Value: "a"}, {Key: "name", Value: "A"}, {Key: "toolsets", Value: []any{tc.entry}}}, nil)
		if ok || len(c.errs) != 1 || c.errs[0].Type != tc.typ || !reflect.DeepEqual(c.errs[0].Loc, tc.loc) {
			t.Errorf("%v: ok=%v errors = %+v", tc.entry, ok, c.errs)
		}
	}
}

func TestBundleFolderAgentTakesToolsetSettings(t *testing.T) {
	b, _, err := LoadBundleFolder(with(teamFiles(), "agents/lead.md",
		"---\nname: lead\ndelegates: [writer]\ntoolsets:\n  - agentarea/files\n  - {name: agentarea/media, image_model: flux-pro}\n---\nYou lead.\n"))
	if err != nil {
		t.Fatal(err)
	}
	i := slices.IndexFunc(b.Agents, func(a BundleAgent) bool { return a.Key == "lead" })
	want := []BundleToolset{{Name: "agentarea/files"}, {Name: "agentarea/media", ImageModel: strp("flux-pro")}}
	if i < 0 || !reflect.DeepEqual(b.Agents[i].Toolsets, want) {
		t.Fatalf("agents = %+v", b.Agents)
	}

	legacy := StrPairs{{"agent.yaml", "name: r\nmodel: m\ntoolsets:\n  - {name: agentarea/media, video_model: veo-3}\n"}, {"instructions.md", "Go.\n"}}
	b, _, err = LoadBundleFolder(legacy)
	if err != nil || !reflect.DeepEqual(b.Agents[0].Toolsets, []BundleToolset{{Name: "agentarea/media", VideoModel: strp("veo-3")}}) {
		t.Fatalf("legacy = %+v, %v", b.Agents, err)
	}
	_, _, err = LoadBundleFolder(StrPairs{{"agent.yaml", "name: r\ntoolsets: [{name: agentarea/media, image: x}]\n"}, {"instructions.md", "Go.\n"}})
	var pe *BundleParseError
	if !errors.As(err, &pe) || !strings.HasPrefix(pe.Msg, "agent.yaml: ") || !strings.Contains(pe.Msg, "toolsets.0.image") {
		t.Fatalf("err = %v", err)
	}
}

func TestBundleInstallResolvesToolsetModels(t *testing.T) {
	f := newDeployFixture(t)
	b := mustParse(t, mediaBundle)
	if _, _, err := f.install(t, &b, nil); err != nil {
		t.Fatal(err)
	}
	want := []catalogapi.BundleTool{{Type: "code", Name: "agentarea/files"},
		{Type: "code", Name: "agentarea/media", ImageModelID: strp("model-flux"), VideoModelID: strp("model-veo")}}
	if len(f.agents.created) != 1 || !reflect.DeepEqual(f.agents.created[0].Tools, want) {
		t.Fatalf("created = %+v", f.agents.created)
	}

	f = newDeployFixture(t)
	b = mustParse(t, strings.Replace(mediaBundle, "video_model: veo-3", "video_model: us-image", 1))
	_, _, err := f.install(t, &b, nil)
	var be *BundleError
	if !errors.As(err, &be) || be.Msg != "agent 'artist': toolset 'agentarea/media': video_model 'us-image' names no active video model instance "+
		"in this workspace; the workspace has 'veo' (veo-3)" {
		t.Fatalf("err = %v", err)
	}
}

func TestBundleAnalyzeChecksToolsetModels(t *testing.T) {
	f := newDeployFixture(t)
	p := analyzeWith(t, f, mediaBundle, nil)
	if len(p.Blocks()) != 0 || len(f.agents.checked) != 1 {
		t.Fatalf("blocks = %v, checked %+v", blockMessages(p), f.agents.checked)
	}
	want := []catalogapi.BundleTool{{Type: "code", Name: "agentarea/files"},
		{Type: "code", Name: "agentarea/media", ImageModelID: strp("model-flux"), VideoModelID: strp("model-veo")}}
	if got := f.agents.checked[0].Toolsets; !reflect.DeepEqual(got, want) {
		t.Fatalf("checked toolsets = %+v", got)
	}

	f = newDeployFixture(t)
	p = analyzeWith(t, f, strings.Replace(mediaBundle, "default: us-image", "default: nope", 1), nil)
	want2 := []string{"agent 'artist': toolset 'agentarea/media': image_model 'nope' names no active image model instance in this workspace; " +
		"the workspace has 'us-image' (flux-pro), 'sd' (stable-diffusion)"}
	if got := blockMessages(p); !reflect.DeepEqual(got, want2) || len(f.agents.checked) != 0 {
		t.Fatalf("blocks = %q", got)
	}
}

func TestBundleRedeployFollowsToolsetSettings(t *testing.T) {
	f := newDeployFixture(t)
	first := mustParse(t, mediaBundle)
	_, res, err := f.install(t, &first, nil)
	if err != nil {
		t.Fatal(err)
	}
	prior := &priorInstall{bundle: first, result: res}
	if _, _, err := f.install(t, &first, prior); err != nil || len(f.agents.updates) != 0 {
		t.Fatalf("unchanged redeploy: updates %+v, %v", f.agents.updates, err)
	}

	changed := mustParse(t, strings.Replace(mediaBundle, "default: us-image", "default: sd", 1))
	if _, _, err := f.install(t, &changed, prior); err == nil {
		t.Fatal("a settings change was applied without the plan's approval")
	}
	_, _, err = f.install(t, &changed, prior, entityRef{KindAgent, "artist"})
	if err != nil || len(f.agents.updates) != 1 {
		t.Fatalf("updates %+v, %v", f.agents.updates, err)
	}
	u := f.agents.updates[0]
	if u.Tools[1].ImageModelID == nil || *u.Tools[1].ImageModelID != "model-sd" ||
		!reflect.DeepEqual(u.ManagedTools, []catalogapi.BundleTool{{Type: "code", Name: "agentarea/files"}, {Type: "code", Name: "agentarea/media"}}) {
		t.Fatalf("update = %+v", u)
	}
}
