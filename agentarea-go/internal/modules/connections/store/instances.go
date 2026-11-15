package store

import (
	"bytes"
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// Instances is the mcp_server_instances repository. Reads see the
// workspace's rows and the platform-managed ones; writes only the workspace's.
type Instances struct{}

// InstanceNew is the row create inserts.
type InstanceNew struct {
	ID           uuid.UUID
	CreatedBy    string
	Name         string
	Description  *string
	ServerSpecID string
	Transport    string
	JSONSpec     map[string]any
	AuthConfigID *uuid.UUID
	Cost         map[string]any
	Now          time.Time
}

// InstancePatch is the fields update writes, all replaced.
type InstancePatch struct {
	Name        string
	Description *string
	JSONSpec    map[string]any
	Cost        map[string]any
	Now         time.Time
}

func decodeAny(b []byte) (any, error) {
	if len(b) == 0 {
		return nil, nil
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	return v, nil
}

func instanceFrom(r GetInstanceRow) (domain.Instance, error) {
	spec, err := jsonMap(r.JsonSpec)
	if err != nil {
		return domain.Instance{}, err
	}
	if spec == nil {
		spec = map[string]any{}
	}
	ver, err := jsonMap(r.Verification)
	if err != nil {
		return domain.Instance{}, err
	}
	last, err := jsonMap(r.LastDispatch)
	if err != nil {
		return domain.Instance{}, err
	}
	events, err := jsonMap(r.Events)
	if err != nil {
		return domain.Instance{}, err
	}
	cost, err := jsonMap(r.Cost)
	if err != nil {
		return domain.Instance{}, err
	}
	tools, err := decodeAny(r.Tools)
	if err != nil {
		return domain.Instance{}, err
	}
	i := domain.Instance{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, CreatedBy: r.CreatedBy, Name: r.Name,
		Description: fromText(r.Description), ServerSpecID: r.ServerSpecID, Transport: r.Transport,
		JSONSpec: spec, VerificationRaw: ver, LastDispatch: last, Events: events,
		AuthConfigID: fromNullUUID(r.AuthConfigID), ManagedBy: fromText(r.ManagedBy), Cost: cost,
		CreatedAt: fromTimestamp(r.CreatedAt), UpdatedAt: fromTimestamp(r.UpdatedAt),
	}
	if l, ok := tools.([]any); ok {
		i.Tools, i.ToolsSet = l, true
	}
	i.Verification = VerificationFrom(ver)
	return i, nil
}

// VerificationFrom reads a stored verification object; a row with none is never_attempted.
func VerificationFrom(m map[string]any) domain.Verification {
	v := domain.DefaultVerification()
	if m == nil {
		return v
	}
	if s, ok := m["status"].(string); ok {
		v.Status = s
	}
	if s, ok := m["at"].(string); ok {
		v.At = &s
	}
	if e, ok := m["error"].(map[string]any); ok {
		code, _ := e["code"].(string)
		msg, _ := e["message"].(string)
		v.Error = &domain.VerificationError{Code: code, Message: msg, Detail: e["detail"]}
	}
	return v
}

func verificationJSON(v domain.Verification) []byte {
	raw, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return raw
}

func jsonOrNull(v any) []byte {
	if v == nil {
		return nil
	}
	raw, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return raw
}

func nullUUID(p *uuid.UUID) uuid.NullUUID {
	if p == nil {
		return uuid.NullUUID{}
	}
	return uuid.NullUUID{UUID: *p, Valid: true}
}

func (Instances) List(ctx context.Context, s db.Session) ([]domain.Instance, error) {
	rows, err := New(s.Q()).ListInstances(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]domain.Instance, 0, len(rows))
	for _, r := range rows {
		i, err := instanceFrom(GetInstanceRow(r))
		if err != nil {
			return nil, err
		}
		out = append(out, i)
	}
	return out, nil
}

func (Instances) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	r, err := New(s.Q()).GetInstance(ctx, GetInstanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.Instance{}, false, nil
	}
	if err != nil {
		return domain.Instance{}, false, err
	}
	i, err := instanceFrom(r)
	return i, err == nil, err
}

// GetMany reads the ids the session sees, keyed by id.
func (Instances) GetMany(ctx context.Context, s db.Session, ids []uuid.UUID) (map[string]domain.Instance, error) {
	rows, err := New(s.Q()).GetInstancesByIDs(ctx, GetInstancesByIDsParams{Ids: ids, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make(map[string]domain.Instance, len(rows))
	for _, r := range rows {
		i, err := instanceFrom(GetInstanceRow(r))
		if err != nil {
			return nil, err
		}
		out[i.ID] = i
	}
	return out, nil
}

// Lock reads the row FOR UPDATE; s must be a transaction.
func (Instances) Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Instance, bool, error) {
	r, err := New(s.Q()).LockInstance(ctx, LockInstanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if IsNoRows(err) {
		return domain.Instance{}, false, nil
	}
	if err != nil {
		return domain.Instance{}, false, err
	}
	i, err := instanceFrom(GetInstanceRow(r))
	return i, err == nil, err
}

func (Instances) Insert(ctx context.Context, s db.Session, n InstanceNew) (domain.Instance, error) {
	var cost []byte
	if n.Cost != nil {
		cost = jsonObject(n.Cost)
	}
	r, err := New(s.Q()).InsertInstance(ctx, InsertInstanceParams{
		ID: n.ID, WorkspaceID: s.Workspace().ID(), CreatedBy: n.CreatedBy, Name: n.Name,
		Description: text(n.Description), ServerSpecID: n.ServerSpecID, Transport: n.Transport,
		JsonSpec: jsonObject(n.JSONSpec), Verification: verificationJSON(domain.DefaultVerification()),
		AuthConfigID: nullUUID(n.AuthConfigID), Cost: cost, Now: naive(n.Now),
	})
	if err != nil {
		return domain.Instance{}, err
	}
	return instanceFrom(GetInstanceRow(r))
}

func (Instances) Update(ctx context.Context, s db.Session, id uuid.UUID, p InstancePatch) (bool, error) {
	var cost []byte
	if p.Cost != nil {
		cost = jsonObject(p.Cost)
	}
	n, err := New(s.Q()).UpdateInstance(ctx, UpdateInstanceParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Name: p.Name, Description: text(p.Description),
		JsonSpec: jsonObject(p.JSONSpec), Cost: cost, Now: naive(p.Now),
	})
	return n > 0, err
}

func (Instances) SetJSONSpec(ctx context.Context, s db.Session, id uuid.UUID, spec map[string]any, now time.Time) (bool, error) {
	n, err := New(s.Q()).SetInstanceJSONSpec(ctx, SetInstanceJSONSpecParams{
		ID: id, WorkspaceID: s.Workspace().ID(), JsonSpec: jsonObject(spec), Now: naive(now)})
	return n > 0, err
}

func (Instances) SetAuthConfig(ctx context.Context, s db.Session, id uuid.UUID, authConfig *uuid.UUID, now time.Time) (bool, error) {
	n, err := New(s.Q()).SetInstanceAuthConfig(ctx, SetInstanceAuthConfigParams{
		ID: id, WorkspaceID: s.Workspace().ID(), AuthConfigID: nullUUID(authConfig), Now: naive(now)})
	return n > 0, err
}

func (Instances) SetVerification(ctx context.Context, s db.Session, id uuid.UUID, v domain.Verification) (bool, error) {
	n, err := New(s.Q()).SetInstanceVerification(ctx, SetInstanceVerificationParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Verification: verificationJSON(v)})
	return n > 0, err
}

// SetDiscovery writes a verification with the tools and events it found;
// nil tools or events store NULL.
func (Instances) SetDiscovery(ctx context.Context, s db.Session, id uuid.UUID, v domain.Verification, tools []any, events map[string]any) (bool, error) {
	var ev any
	if events != nil {
		ev = events
	}
	var tl any
	if tools != nil {
		tl = tools
	}
	n, err := New(s.Q()).SetInstanceDiscovery(ctx, SetInstanceDiscoveryParams{
		ID: id, WorkspaceID: s.Workspace().ID(), Verification: verificationJSON(v),
		Tools: jsonOrNull(tl), Events: jsonOrNull(ev)})
	return n > 0, err
}

func (Instances) SetLastDispatch(ctx context.Context, s db.Session, id uuid.UUID, dispatch map[string]any) (bool, error) {
	n, err := New(s.Q()).SetInstanceLastDispatch(ctx, SetInstanceLastDispatchParams{
		ID: id, WorkspaceID: s.Workspace().ID(), LastDispatch: jsonObject(dispatch)})
	return n > 0, err
}

func (Instances) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteInstance(ctx, DeleteInstanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// InterruptStale marks in_progress verifications older than before as failed.
func (Instances) InterruptStale(ctx context.Context, q db.Querier, v domain.Verification, before time.Time) (int64, error) {
	return New(q).InterruptStaleVerifications(ctx, InterruptStaleVerificationsParams{
		Verification: verificationJSON(v), Before: tstz(before)})
}

// Pending is one instance the monitor still has to verify.
type Pending struct {
	ID          uuid.UUID
	WorkspaceID string
	ManagedBy   *string
}

// NeverAttempted lists container and platform-managed instances never verified, across workspaces.
func (Instances) NeverAttempted(ctx context.Context, q db.Querier, limit int32) ([]Pending, error) {
	rows, err := New(q).ListNeverAttempted(ctx, limit)
	if err != nil {
		return nil, err
	}
	out := make([]Pending, 0, len(rows))
	for _, r := range rows {
		out = append(out, Pending{ID: r.ID, WorkspaceID: r.WorkspaceID, ManagedBy: fromText(r.ManagedBy)})
	}
	return out, nil
}

// Owner is the workspace and kind (mcp or openapi) of a connection id, across workspaces.
type Owner struct {
	WorkspaceID string
	Kind        string
}

// ConnectionOwners is every row the id names: an MCP instance first.
func (Instances) ConnectionOwners(ctx context.Context, q db.Querier, id uuid.UUID) ([]Owner, error) {
	rows, err := New(q).ConnectionWorkspace(ctx, id)
	if err != nil {
		return nil, err
	}
	out := make([]Owner, 0, len(rows))
	for _, r := range rows {
		out = append(out, Owner{WorkspaceID: r.WorkspaceID, Kind: r.Kind})
	}
	return out, nil
}
