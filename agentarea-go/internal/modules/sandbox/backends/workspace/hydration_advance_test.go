package workspace

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
)

func inputEntry(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, relativePath, body string) Entry {
	t.Helper()
	digest := sha256.Sum256([]byte(body))
	hash := hex.EncodeToString(digest[:])
	entry := Entry{
		RelativePath:        relativePath,
		ObjectURI:           repository.objectURI(repository.taskPrefix(ref.WorkspaceID, ref.TaskID) + "/objects/" + hash),
		ObjectVersionOrETag: "object-" + hash[:8],
		SHA256:              hash,
		Size:                int64(len(body)),
		ContentType:         "application/octet-stream",
		Mode:                0o600,
	}
	storage.put(repository.keyFromURI(entry.ObjectURI), []byte(body), entry.ObjectVersionOrETag, map[string]string{"sha256": hash})
	return entry
}

// commitInputs publishes the next workspace generation whose entries are the
// fixture's non-input files plus inputs.
func commitInputs(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, manifest Manifest, inputs ...Entry) (ManifestRef, Manifest) {
	t.Helper()
	next := manifest
	next.Entries = nil
	for _, entry := range manifest.Entries {
		if strings.HasPrefix(entry.RelativePath, "inputs/") {
			continue
		}
		next.Entries = append(next.Entries, entry)
	}
	next.Entries = append(next.Entries, inputs...)
	next.BaseGeneration = manifest.Generation
	next.Generation = manifest.Generation + 1
	nextRef := ref
	nextRef.BaseGeneration = ref.Generation
	nextRef.Generation = next.Generation
	nextRef = storage.replaceManifest(t, repository, nextRef, next)
	storage.putJSON(repository.pointerKey(nextRef), nextRef, fmt.Sprintf("current-%d", nextRef.Generation))
	return nextRef, next
}

func inputRevision(t *testing.T, inputs ...Entry) string {
	t.Helper()
	revision, err := hydrationRevisionSHA256("inputs", selectHydrationEntries(inputs, "inputs"))
	if err != nil {
		t.Fatal(err)
	}
	return revision
}

func todaysInputConflict(from, to string) string {
	return fmt.Sprintf("%v: immutable task input revision changed from %s to %s", ErrWorkspaceConflict, from, to)
}

func pinnedRevision(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef) string {
	t.Helper()
	storage.mu.Lock()
	object, ok := storage.objects[repository.hydrationPinKey(ref.WorkspaceID, ref.TaskID, "inputs")]
	storage.mu.Unlock()
	if !ok {
		t.Fatal("hydration revision pin is missing")
	}
	var record hydrationRevisionRecord
	if err := json.Unmarshal(object.body, &record); err != nil {
		t.Fatal(err)
	}
	return record.RevisionSHA256
}

func TestAdditiveAttachmentDiff(t *testing.T) {
	brief := Entry{RelativePath: "inputs/brief.txt", SHA256: "1", Size: 1}
	first := Entry{RelativePath: "inputs/attachments/a.pdf", SHA256: "2", Size: 2}
	second := Entry{RelativePath: "inputs/attachments/b.pdf", SHA256: "3", Size: 3}
	changedFirst := first
	changedFirst.SHA256 = "4"
	cases := []struct {
		name     string
		previous []Entry
		current  []Entry
		want     []string
	}{
		{"one attachment added", []Entry{brief, first}, []Entry{brief, first, second}, []string{"inputs/attachments/b.pdf"}},
		{"first attachment into an empty view", nil, []Entry{first, second}, []string{"inputs/attachments/a.pdf", "inputs/attachments/b.pdf"}},
		{"nothing changed", []Entry{brief, first}, []Entry{brief, first}, nil},
		{"attachment content changed", []Entry{brief, first}, []Entry{brief, changedFirst, second}, nil},
		{"attachment removed", []Entry{brief, first}, []Entry{brief, second}, nil},
		{"non-attachment input added", []Entry{first}, []Entry{first, brief}, nil},
		{"nested attachment added", []Entry{first}, []Entry{first, {RelativePath: "inputs/attachments/dir/c.pdf", SHA256: "5"}}, nil},
		{"traversal added", []Entry{first}, []Entry{first, {RelativePath: "inputs/attachments/../escape", SHA256: "5"}}, nil},
		{"absolute path added", []Entry{first}, []Entry{first, {RelativePath: "/inputs/attachments/c.pdf", SHA256: "5"}}, nil},
		{"prefix lookalike added", []Entry{first}, []Entry{first, {RelativePath: "inputs/attachments-x/c.pdf", SHA256: "5"}}, nil},
		{"tombstone added", []Entry{first}, []Entry{first, {RelativePath: "inputs/attachments/c.pdf", Deleted: true}}, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := additiveAttachmentDiff(tc.previous, tc.current)
			if tc.want == nil {
				if ok {
					t.Fatalf("additiveAttachmentDiff() = %v, true; want refusal", got)
				}
				return
			}
			if !ok || fmt.Sprint(got) != fmt.Sprint(tc.want) {
				t.Fatalf("additiveAttachmentDiff() = %v, %v; want %v, true", got, ok, tc.want)
			}
		})
	}
}

func TestPrepareCurrentHydrationAdvancesPinForAddedAttachment(t *testing.T) {
	repository, storage, ref, manifest := repositoryFixture(t)
	brief := inputEntry(t, repository, storage, ref, "inputs/brief.txt", "brief")
	first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
	ref, manifest = commitInputs(t, repository, storage, ref, manifest, brief, first)
	before, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatal(err)
	}

	second := inputEntry(t, repository, storage, ref, "inputs/attachments/b.pdf", "follow-up attachment")
	ref, _ = commitInputs(t, repository, storage, ref, manifest, brief, first, second)
	after, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatalf("PrepareCurrentHydration() after an added attachment error = %v", err)
	}
	if after.RevisionSHA256 == before.RevisionSHA256 || len(after.Downloads) != 3 {
		t.Fatalf("hydration after addition = %#v", after)
	}
	if got := pinnedRevision(t, repository, storage, ref); got != after.RevisionSHA256 {
		t.Fatalf("pinned revision = %s, want %s", got, after.RevisionSHA256)
	}

	additions, err := repository.HydrationAdditions(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs", before.RevisionSHA256, after.RevisionSHA256)
	if err != nil {
		t.Fatal(err)
	}
	if len(additions) != 1 || additions[0] != second {
		t.Fatalf("HydrationAdditions() = %#v, want only %s", additions, second.RelativePath)
	}
	if _, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs"); err != nil {
		t.Fatalf("steady-state PrepareCurrentHydration() error = %v", err)
	}
}

func TestPrepareCurrentHydrationAdvancesFromAnEmptyInputView(t *testing.T) {
	repository, storage, ref, manifest := repositoryFixture(t)
	before, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatal(err)
	}
	first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
	ref, _ = commitInputs(t, repository, storage, ref, manifest, first)
	after, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatalf("PrepareCurrentHydration() error = %v", err)
	}
	additions, err := repository.HydrationAdditions(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs", before.RevisionSHA256, after.RevisionSHA256)
	if err != nil || len(additions) != 1 || additions[0] != first {
		t.Fatalf("HydrationAdditions() = %#v, %v", additions, err)
	}
}

func TestPrepareCurrentHydrationRefusesEveryNonAdditiveInputChange(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, brief, first Entry) []Entry
	}{
		{"attachment changed", func(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, brief, _ Entry) []Entry {
			return []Entry{brief, inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "rewritten")}
		}},
		{"attachment removed", func(_ *testing.T, _ *Repository, _ *fakeS3, _ ManifestRef, brief, _ Entry) []Entry {
			return []Entry{brief}
		}},
		{"input outside attachments added", func(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, brief, first Entry) []Entry {
			return []Entry{brief, first, inputEntry(t, repository, storage, ref, "inputs/extra.txt", "extra")}
		}},
		{"nested attachment added", func(t *testing.T, repository *Repository, storage *fakeS3, ref ManifestRef, brief, first Entry) []Entry {
			return []Entry{brief, first, inputEntry(t, repository, storage, ref, "inputs/attachments/dir/c.pdf", "nested")}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repository, storage, ref, manifest := repositoryFixture(t)
			brief := inputEntry(t, repository, storage, ref, "inputs/brief.txt", "brief")
			first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
			ref, manifest = commitInputs(t, repository, storage, ref, manifest, brief, first)
			before, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
			if err != nil {
				t.Fatal(err)
			}
			inputs := tc.mutate(t, repository, storage, ref, brief, first)
			ref, _ = commitInputs(t, repository, storage, ref, manifest, inputs...)
			_, err = repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
			if err == nil || !errors.Is(err, ErrWorkspaceConflict) || err.Error() != todaysInputConflict(before.RevisionSHA256, inputRevision(t, inputs...)) {
				t.Fatalf("PrepareCurrentHydration() error = %v, want today's input conflict", err)
			}
			if got := pinnedRevision(t, repository, storage, ref); got != before.RevisionSHA256 {
				t.Fatalf("refused change moved the pin to %s", got)
			}
		})
	}
}

func TestPrepareCurrentHydrationKeepsRefusingPinsWrittenWithoutAView(t *testing.T) {
	repository, storage, ref, manifest := repositoryFixture(t)
	first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
	ref, manifest = commitInputs(t, repository, storage, ref, manifest, first)
	legacyRevision := inputRevision(t, first)
	storage.putJSON(repository.hydrationPinKey(ref.WorkspaceID, ref.TaskID, "inputs"), hydrationRevisionRecord{
		SchemaVersion: SchemaVersion, WorkspaceID: ref.WorkspaceID, TaskID: ref.TaskID,
		Prefix: "inputs", RevisionSHA256: legacyRevision,
	}, "legacy-pin")

	second := inputEntry(t, repository, storage, ref, "inputs/attachments/b.pdf", "follow-up attachment")
	ref, _ = commitInputs(t, repository, storage, ref, manifest, first, second)
	_, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err == nil || !errors.Is(err, ErrWorkspaceConflict) || err.Error() != todaysInputConflict(legacyRevision, inputRevision(t, first, second)) {
		t.Fatalf("PrepareCurrentHydration() error = %v, want today's input conflict", err)
	}
	if got := pinnedRevision(t, repository, storage, ref); got != legacyRevision {
		t.Fatalf("legacy pin moved to %s", got)
	}
}

func TestPrepareCurrentHydrationLostPinRaceRereadsAndRechecks(t *testing.T) {
	t.Run("racer pinned the same revision", func(t *testing.T) {
		repository, storage, ref, manifest := repositoryFixture(t)
		first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
		ref, manifest = commitInputs(t, repository, storage, ref, manifest, first)
		if _, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs"); err != nil {
			t.Fatal(err)
		}
		second := inputEntry(t, repository, storage, ref, "inputs/attachments/b.pdf", "follow-up attachment")
		ref, _ = commitInputs(t, repository, storage, ref, manifest, first, second)
		target := inputRevision(t, first, second)
		pinKey := repository.hydrationPinKey(ref.WorkspaceID, ref.TaskID, "inputs")
		racer, _ := json.Marshal(hydrationRevisionRecord{
			SchemaVersion: SchemaVersion, WorkspaceID: ref.WorkspaceID, TaskID: ref.TaskID, Prefix: "inputs", RevisionSHA256: target,
		})
		storage.ifMatchRaceKey = pinKey
		storage.ifMatchRaceObject = fakeObject{body: racer, etag: "racer-pin"}

		if _, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs"); err != nil {
			t.Fatalf("PrepareCurrentHydration() error = %v", err)
		}
		storage.mu.Lock()
		defer storage.mu.Unlock()
		if storage.objects[pinKey].etag != "racer-pin" {
			t.Fatal("lost CAS overwrote the racing pin")
		}
	})

	t.Run("racer pinned a divergent revision", func(t *testing.T) {
		repository, storage, ref, manifest := repositoryFixture(t)
		first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
		ref, manifest = commitInputs(t, repository, storage, ref, manifest, first)
		if _, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs"); err != nil {
			t.Fatal(err)
		}
		racing := inputEntry(t, repository, storage, ref, "inputs/attachments/racer.pdf", "racing attachment")
		racingView, racingRevision, err := hydrationView("inputs", selectHydrationEntries([]Entry{first, racing}, "inputs"))
		if err != nil {
			t.Fatal(err)
		}
		storage.put(repository.hydrationViewKey(ref.WorkspaceID, ref.TaskID, racingRevision), racingView, "racer-view", nil)
		second := inputEntry(t, repository, storage, ref, "inputs/attachments/b.pdf", "follow-up attachment")
		ref, _ = commitInputs(t, repository, storage, ref, manifest, first, second)
		pinKey := repository.hydrationPinKey(ref.WorkspaceID, ref.TaskID, "inputs")
		racer, _ := json.Marshal(hydrationRevisionRecord{
			SchemaVersion: SchemaVersion, WorkspaceID: ref.WorkspaceID, TaskID: ref.TaskID, Prefix: "inputs", RevisionSHA256: racingRevision,
		})
		storage.ifMatchRaceKey = pinKey
		storage.ifMatchRaceObject = fakeObject{body: racer, etag: "racer-pin"}

		_, err = repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
		if err == nil || err.Error() != todaysInputConflict(racingRevision, inputRevision(t, first, second)) {
			t.Fatalf("PrepareCurrentHydration() error = %v, want conflict against the racing pin", err)
		}
		storage.mu.Lock()
		defer storage.mu.Unlock()
		if storage.objects[pinKey].etag != "racer-pin" {
			t.Fatal("lost CAS overwrote the racing pin")
		}
	})
}

func TestHydrationAdditionsRejectsATamperedView(t *testing.T) {
	repository, storage, ref, manifest := repositoryFixture(t)
	before, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatal(err)
	}
	first := inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "first attachment")
	ref, _ = commitInputs(t, repository, storage, ref, manifest, first)
	after, err := repository.PrepareCurrentHydration(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs")
	if err != nil {
		t.Fatal(err)
	}
	forged, _, err := hydrationView("inputs", []Entry{inputEntry(t, repository, storage, ref, "inputs/attachments/a.pdf", "forged")})
	if err != nil {
		t.Fatal(err)
	}
	storage.put(repository.hydrationViewKey(ref.WorkspaceID, ref.TaskID, after.RevisionSHA256), forged, "forged-view", nil)
	if _, err := repository.HydrationAdditions(context.Background(), ref.WorkspaceID, ref.TaskID, "inputs", before.RevisionSHA256, after.RevisionSHA256); err == nil {
		t.Fatal("HydrationAdditions() accepted a view whose digest is not its revision")
	}
}
