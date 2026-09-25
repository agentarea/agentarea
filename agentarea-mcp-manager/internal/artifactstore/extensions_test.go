package artifactstore

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
)

type publicationObserverStub struct {
	publications []Publication
	err          error
}

func (o *publicationObserverStub) Published(_ context.Context, publication Publication) error {
	o.publications = append(o.publications, publication)
	return o.err
}

func publishForObserver(t *testing.T, client *fakeS3Client, observer PublicationObserver) (Artifact, error) {
	t.Helper()
	repository, err := New(Config{Bucket: "artifacts", Prefix: "root", MaxBytes: 1024, MaxCount: 10, MaxTotalBytes: 4096}, client)
	if err != nil {
		t.Fatal(err)
	}
	if observer != nil {
		repository.SetPublicationObserver(observer)
	}
	content := []byte("report")
	return repository.PublishStream(context.Background(), "workspace-1", "task-1", "reports/report.txt", "text/plain", bytes.NewReader(content), int64(len(content)))
}

func TestPublicationObserverSeesTheStoredObject(t *testing.T) {
	client := &fakeS3Client{}
	observer := &publicationObserverStub{}
	artifact, err := publishForObserver(t, client, observer)
	if err != nil {
		t.Fatal(err)
	}
	if len(observer.publications) != 1 {
		t.Fatalf("publications = %+v", observer.publications)
	}
	publication := observer.publications[0]
	if publication.WorkspaceID != "workspace-1" || publication.TaskID != "task-1" || publication.SizeBytes != artifact.Size ||
		!strings.HasPrefix(publication.ObjectKey, "root/workspaces/workspace-1/tasks/task-1/artifacts/"+artifact.ID+"/") {
		t.Fatalf("publication = %+v", publication)
	}
}

func TestPublicationObserverFailureFailsThePublish(t *testing.T) {
	observerErr := errors.New("ledger unavailable")
	if _, err := publishForObserver(t, &fakeS3Client{}, &publicationObserverStub{err: observerErr}); !errors.Is(err, observerErr) {
		t.Fatalf("publish error = %v", err)
	}
}

func TestPublishWithoutObserverReadsNothingBack(t *testing.T) {
	client := &fakeS3Client{}
	if _, err := publishForObserver(t, client, nil); err != nil {
		t.Fatal(err)
	}
	if client.headCalls != 0 {
		t.Fatalf("publish without an observer issued %d HEAD requests", client.headCalls)
	}
}
