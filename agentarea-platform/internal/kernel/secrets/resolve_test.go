package secrets

import (
	"context"
	"errors"
	"strings"
	"testing"
)

// catalogRows is a workspace catalog: user rows and rows a connection owns.
type catalogRows struct {
	user    map[string]string
	managed map[string]string
}

func (c catalogRows) GetUserOwned(_ context.Context, n string) (string, error) {
	if v, ok := c.user[n]; ok {
		return v, nil
	}
	return "", ErrNotFound
}

func (c catalogRows) Get(ctx context.Context, n string) (string, error) {
	if v, ok := c.managed[n]; ok {
		return v, nil
	}
	return c.GetUserOwned(ctx, n)
}

func userRows(m map[string]string) catalogRows { return catalogRows{user: m} }

func TestResolveValues(t *testing.T) {
	r := NewUserResolver(userRows(map[string]string{"api-key": "s3cret", "empty": ""}))
	got, err := ResolveValues(context.Background(), r, map[string]any{
		"LITERAL": "x", "NUM": 3, "KEY": map[string]any{"secret_name": "api-key"}, "KEY2": map[string]string{"secret_name": "api-key"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if got["LITERAL"] != "x" || got["NUM"] != "3" || got["KEY"] != "s3cret" || got["KEY2"] != "s3cret" {
		t.Errorf("got %v", got)
	}
}

func TestResolveValuesRefuses(t *testing.T) {
	r := NewUserResolver(userRows(map[string]string{"empty": ""}))
	cases := map[string]struct {
		r    Resolver
		in   any
		want string
	}{
		"no name":     {r, map[string]any{}, "secret_name"},
		"reserved":    {r, map[string]any{"secret_name": "mcp_instance_" + u + "_K"}, "reserved prefix"},
		"missing":     {r, map[string]any{"secret_name": "nope"}, "secret not found"},
		"empty":       {r, map[string]any{"secret_name": "empty"}, "is empty"},
		"no resolver": {nil, map[string]any{"secret_name": "a"}, "no secret resolver"},
	}
	for name, c := range cases {
		_, err := ResolveValues(context.Background(), c.r, map[string]any{"K": c.in})
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v", name, err)
		}
	}
	_, err := ResolveValues(context.Background(), r, map[string]any{"K": map[string]any{"secret_name": "nope"}})
	if !errors.Is(err, ErrNotFound) {
		t.Errorf("not found not wrapped: %v", err)
	}
}

// A row a connection owns is no workspace's catalog entry, whatever its name.
func TestResolveReadsOnlyUserOwnedRows(t *testing.T) {
	r := NewUserResolver(catalogRows{user: map[string]string{"mine": "v"}, managed: map[string]string{"reclassified": "connection credential"}})
	if v, err := r.Resolve(context.Background(), "mine"); err != nil || v != "v" {
		t.Fatalf("%q %v", v, err)
	}
	if v, err := r.Resolve(context.Background(), "reclassified"); !errors.Is(err, ErrNotFound) {
		t.Errorf("resolved a managed row: %q %v", v, err)
	}
}
