package service

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

// SkillPlatformPrincipal is PLATFORM_PRINCIPAL_ID: the author of a migrate version.
const SkillPlatformPrincipal = "platform"

// SkillPlatformWorkspace is PLATFORM_WORKSPACE_ID.
const SkillPlatformWorkspace = "platform"

const skillURLTTL = 3600 * time.Second

func skills() store.Skills { return store.Skills{} }

// skillFileInfo is a stored package file.
type skillFileInfo struct {
	Path string
	Size int64
}

func (k *Skills) store() (blob.Store, error) {
	if k.blob == nil {
		return nil, &UnwiredError{Feature: "skill package storage"}
	}
	return k.blob, nil
}

func skillPrefix(s3Path string) string { return strings.TrimRight(s3Path, "/") + "/" }

// listFiles is SkillStorageService.list_files.
func (k *Skills) listFiles(ctx context.Context, s3Path string) ([]skillFileInfo, error) {
	st, err := k.store()
	if err != nil {
		return nil, err
	}
	prefix := skillPrefix(s3Path)
	var out []skillFileInfo
	for info, err := range st.List(ctx, prefix) {
		if err != nil {
			return nil, err
		}
		if rel := strings.TrimPrefix(info.Key, prefix); rel != "" {
			out = append(out, skillFileInfo{Path: rel, Size: info.Size})
		}
	}
	return out, nil
}

// fileContent is get_file_content.
func (k *Skills) fileContent(ctx context.Context, s3Path, rel string) ([]byte, error) {
	st, err := k.store()
	if err != nil {
		return nil, err
	}
	p, err := domain.SkillSafePath(rel)
	if err != nil {
		return nil, err
	}
	rc, _, err := st.Get(ctx, skillPrefix(s3Path)+p)
	if errors.Is(err, blob.ErrNotFound) {
		return nil, &SkillFileNotFoundError{Path: rel}
	}
	if err != nil {
		return nil, err
	}
	defer func() { _ = rc.Close() }()
	return io.ReadAll(rc)
}

// fileURL is get_file_url: a presigned GET, the object's existence unchecked.
func (k *Skills) fileURL(ctx context.Context, s3Path, rel string, ttl time.Duration) (string, error) {
	st, err := k.store()
	if err != nil {
		return "", err
	}
	p, err := domain.SkillSafePath(rel)
	if err != nil {
		return "", err
	}
	pre, err := st.PresignGet(ctx, skillPrefix(s3Path)+p, ttl)
	if err != nil {
		return "", err
	}
	return pre.URL, nil
}

// readPackage is read_package: every file, in listing order.
func (k *Skills) readPackage(ctx context.Context, s3Path string) (domain.SkillFiles, error) {
	infos, err := k.listFiles(ctx, s3Path)
	if err != nil {
		return nil, err
	}
	var files domain.SkillFiles
	for _, info := range infos {
		data, err := k.fileContent(ctx, s3Path, info.Path)
		if err != nil {
			return nil, err
		}
		files.Set(info.Path, data)
	}
	return files, nil
}

// deletePackage is delete_package: every object under the prefix.
func (k *Skills) deletePackage(ctx context.Context, s3Path string) (int, error) {
	infos, err := k.listFiles(ctx, s3Path)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, info := range infos {
		if err := k.blob.Delete(ctx, skillPrefix(s3Path)+info.Path); err != nil && !errors.Is(err, blob.ErrNotFound) {
			return n, err
		}
		n++
	}
	return n, nil
}

// storeWorkspacePackage is store_workspace_package: the files at their digest, missing ones only.
func (k *Skills) storeWorkspacePackage(ctx context.Context, files domain.SkillFiles, workspaceID string) (string, error) {
	return k.storeByDigest(ctx, domain.SkillWorkspacePackageArea(workspaceID), files)
}

// storeByDigest is _store_by_digest: files at <area>/<digest>/, missing ones only.
func (k *Skills) storeByDigest(ctx context.Context, area string, files domain.SkillFiles) (string, error) {
	checked, err := domain.SkillCheckedFiles(files)
	if err != nil {
		return "", err
	}
	st, err := k.store()
	if err != nil {
		return "", err
	}
	prefix := area + "/" + domain.SkillDigest(checked) + "/"
	stored, err := k.listFiles(ctx, prefix)
	if err != nil {
		return "", err
	}
	have := map[string]bool{}
	for _, f := range stored {
		have[f.Path] = true
	}
	for _, f := range checked {
		if have[f.Path] {
			continue
		}
		if err := st.Put(ctx, prefix+f.Path, bytes.NewReader(f.Data), int64(len(f.Data)),
			blob.PutOptions{ContentType: domain.SkillContentType(f.Path)}); err != nil {
			return "", err
		}
	}
	return prefix, nil
}

// skillPackageMovedError is SkillPackageMovedError: a compare-and-set move lost.
type skillPackageMovedError struct{ current *string }

func (e *skillPackageMovedError) Error() string { return "skill package moved meanwhile" }

// setPackage is SkillRepository.set_package; expect makes it a compare-and-set.
// False when the workspace has no such skill.
func (k *Skills) setPackage(ctx context.Context, sess db.Session, userID string, id uuid.UUID, s3Path, reason string,
	catalogVersion *string, expect *string, compare bool) (bool, error) {
	now := k.s.d.Now()
	if compare {
		moved, err := skills().SwapPackage(ctx, sess, id, s3Path, expect, now)
		if err != nil {
			return false, err
		}
		if !moved {
			cur, ok, err := skills().Get(ctx, sess, id)
			if err != nil || !ok {
				return false, err
			}
			return false, &skillPackageMovedError{current: cur.S3Path}
		}
	} else {
		if _, ok, err := skills().Lock(ctx, sess, id); err != nil || !ok {
			return false, err
		}
		if err := skills().SetPackage(ctx, sess, id, s3Path, now); err != nil {
			return false, err
		}
	}
	latest, has, err := skills().LatestVersion(ctx, sess, id)
	if err != nil {
		return false, err
	}
	if has && latest.S3Path == s3Path {
		return true, nil
	}
	by := userID
	if reason == "migrate" {
		by = SkillPlatformPrincipal
	}
	return true, skills().AddVersion(ctx, sess, domain.SkillVersion{
		ID: uuid.NewString(), SkillID: id.String(), S3Path: s3Path, Digest: domain.SkillPackageDigestOf(&s3Path),
		Reason: reason, CatalogVersion: catalogVersion, CreatedBy: by,
	}, now)
}

// skillRefused is _move_body_or_refuse's refusal in a read.
func skillRefused(id string) error {
	return &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s still holds its body in its row, and a read does not move it; "+
		"run `agentarea-api skills move-bodies-to-packages`", id)}
}

// resolve is resolve_s3_path: the skill's package, moving a pre-package row
// into one when writes is set (a write session), refusing it otherwise.
func (k *Skills) resolve(ctx context.Context, sess db.Session, userID string, sk *domain.Skill, writes bool) (string, error) {
	if sk.S3Path != nil && *sk.S3Path != "" {
		if sk.Content != nil {
			if !writes {
				return "", skillRefused(sk.ID)
			}
			return k.moveBody(ctx, sess, userID, sk)
		}
		if writes && domain.SkillIsOwnCopy(*sk) {
			return k.moveOwnCopy(ctx, sess, userID, sk)
		}
		return *sk.S3Path, nil
	}
	if sk.Content != nil {
		if !writes {
			return "", skillRefused(sk.ID)
		}
		return k.moveBody(ctx, sess, userID, sk)
	}
	return "", &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s has neither a package nor a body", sk.ID)}
}

func (k *Skills) movedMeanwhile(sk *domain.Skill, err error) (string, error) {
	var moved *skillPackageMovedError
	if !errors.As(err, &moved) {
		return "", err
	}
	if moved.current == nil {
		return "", fmt.Errorf("skill %s lost its package while it was moved", sk.ID)
	}
	sk.S3Path, sk.Content = moved.current, nil
	return *moved.current, nil
}

// moveBody is move_body_to_package.
func (k *Skills) moveBody(ctx context.Context, sess db.Session, userID string, sk *domain.Skill) (string, error) {
	body := []byte("")
	if sk.Content != nil {
		body = []byte(*sk.Content)
	}
	files := domain.SkillFiles{{Path: domain.SkillManifest, Data: body}}
	id := uuid.MustParse(sk.ID)
	if sk.S3Path != nil && *sk.S3Path != "" {
		var err error
		files, err = k.readPackage(ctx, *sk.S3Path)
		if err != nil {
			return "", err
		}
		main, ok := domain.SkillMainFile(files.Paths())
		if !ok {
			main = domain.SkillManifest
		}
		if cur, has := files.Get(main); has && bytes.Equal(cur, body) {
			if err := skills().ClearContent(ctx, sess, id, k.s.d.Now()); err != nil {
				return "", err
			}
			sk.Content = nil
			return *sk.S3Path, nil
		}
		files.Set(main, body)
	}
	s3, err := k.storeWorkspacePackage(ctx, files, sk.WorkspaceID)
	if err != nil {
		return "", err
	}
	ok, err := k.setPackage(ctx, sess, userID, id, s3, "migrate", nil, sk.S3Path, true)
	if err != nil {
		return k.movedMeanwhile(sk, err)
	}
	if !ok {
		return "", fmt.Errorf("skill %s vanished while its body was moved", sk.ID)
	}
	sk.S3Path, sk.Content = &s3, nil
	return s3, nil
}

// moveOwnCopy is move_own_copy_to_package; the copy itself stays.
func (k *Skills) moveOwnCopy(ctx context.Context, sess db.Session, userID string, sk *domain.Skill) (string, error) {
	own := *sk.S3Path
	files, err := k.readPackage(ctx, own)
	if err != nil {
		return "", err
	}
	if len(files) == 0 {
		return "", &domain.SkillValueError{Msg: fmt.Sprintf("Skill %s points at %s, which holds no files", sk.ID, own)}
	}
	s3, err := k.storeWorkspacePackage(ctx, files, sk.WorkspaceID)
	if err != nil {
		return "", err
	}
	ok, err := k.setPackage(ctx, sess, userID, uuid.MustParse(sk.ID), s3, "migrate", nil, &own, true)
	if err != nil {
		return k.movedMeanwhile(sk, err)
	}
	if !ok {
		return "", fmt.Errorf("skill %s vanished while its copy was moved", sk.ID)
	}
	sk.S3Path = &s3
	return s3, nil
}

// readFiles is SkillPackages.read_files at the skill's own package.
func (k *Skills) readFiles(ctx context.Context, sess db.Session, userID string, sk *domain.Skill, writes bool) (domain.SkillFiles, error) {
	if sk.Content != nil && !writes {
		return k.unmovedFiles(ctx, sk)
	}
	s3, err := k.resolve(ctx, sess, userID, sk, writes)
	if err != nil {
		return nil, err
	}
	return k.readPackage(ctx, s3)
}

// unmovedFiles is _unmoved_files: a row whose body is still in the database, read as it is.
func (k *Skills) unmovedFiles(ctx context.Context, sk *domain.Skill) (domain.SkillFiles, error) {
	var files domain.SkillFiles
	if sk.S3Path != nil && *sk.S3Path != "" {
		var err error
		if files, err = k.readPackage(ctx, *sk.S3Path); err != nil {
			return nil, err
		}
	}
	main, ok := domain.SkillMainFile(files.Paths())
	if !ok {
		main = domain.SkillManifest
	}
	files.Set(main, []byte(*sk.Content))
	return files, nil
}

// readSkillMD is read_skill_md at the skill's own package.
func (k *Skills) readSkillMD(ctx context.Context, sess db.Session, userID string, sk *domain.Skill, writes bool) (string, error) {
	if sk.Content != nil && !writes {
		return *sk.Content, nil
	}
	s3, err := k.resolve(ctx, sess, userID, sk, writes)
	if err != nil {
		return "", err
	}
	infos, err := k.listFiles(ctx, s3)
	if err != nil {
		return "", err
	}
	paths := make([]string, len(infos))
	for i, f := range infos {
		paths[i] = f.Path
	}
	main, ok := domain.SkillMainFile(paths)
	if !ok {
		if domain.SkillIsImmutablePackage(s3) {
			return "", &skillInternalError{msg: fmt.Sprintf("Skill %s package has no SKILL.md at its root", sk.ID)}
		}
		return "", &skillInternalError{msg: fmt.Sprintf("Skill %s package %s has no SKILL.md at its root", sk.ID, s3)}
	}
	raw, err := k.fileContent(ctx, s3, main)
	if err != nil {
		return "", err
	}
	text, err := domain.SkillDecodeUTF8(raw)
	if err != nil {
		return "", &skillInternalError{msg: err.Error()}
	}
	return text, nil
}

// SkillFileNotFoundError is get_file_content's FileNotFoundError.
type SkillFileNotFoundError struct{ Path string }

func (e *SkillFileNotFoundError) Error() string { return "File not found: " + e.Path }

// skillInternalError is a ValueError a route does not catch: it answers 500.
type skillInternalError struct{ msg string }

func (e *skillInternalError) Error() string { return e.msg }

// skillUncaught turns a ValueError into one the route does not catch.
func skillUncaught(err error) error {
	var ve *domain.SkillValueError
	if errors.As(err, &ve) {
		return &skillInternalError{msg: ve.Msg}
	}
	return err
}
