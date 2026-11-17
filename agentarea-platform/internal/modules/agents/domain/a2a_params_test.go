package domain

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"
)

func msg(extra ...A2AMember) A2AJSON {
	m := A2AJSON{{Key: "messageId", Value: "m1"}, {Key: "role", Value: "ROLE_USER"},
		{Key: "parts", Value: []any{A2AJSON{{Key: "text", Value: "hello"}}}}}
	return append(m, extra...)
}

func TestA2ASendParams(t *testing.T) {
	got, err := A2ASendParams(A2AJSON{{Key: "message", Value: msg(A2AMember{Key: "context_id", Value: "c1"})},
		{Key: "metadata", Value: A2AJSON{{Key: "n", Value: json.Number("1")}}},
		{Key: "configuration", Value: A2AJSON{{Key: "taskPushNotificationConfig", Value: A2AJSON{{Key: "url", Value: "https://x"}}}}}})
	if err != nil {
		t.Fatal(err)
	}
	if A2AMessageText(got.Parts) != "hello" || got.ContextID != "c1" || got.Push == nil || got.Push.URL != "https://x" {
		t.Errorf("%+v", got)
	}
	if v, _ := got.Metadata.Get("n"); v != float64(1) {
		t.Errorf("a Struct number is a float: %v", v)
	}
}

func TestA2ASendParamsRequiredFields(t *testing.T) {
	cases := map[string]struct {
		params any
		fields []string
	}{
		"no params":  {nil, []string{"message"}},
		"no message": {A2AJSON{}, []string{"message"}},
		"empty message": {A2AJSON{{Key: "message", Value: A2AJSON{}}},
			[]string{"message.message_id", "message.role", "message.parts"}},
		"no parts": {A2AJSON{{Key: "message", Value: A2AJSON{{Key: "messageId", Value: "m"}, {Key: "role", Value: "ROLE_USER"}}}},
			[]string{"message.parts"}},
	}
	for name, c := range cases {
		_, err := A2ASendParams(c.params)
		if err == nil || err.Message != "Validation failed" {
			t.Errorf("%s: %v", name, err)
			continue
		}
		info := err.Data.([]any)[0].(A2AJSON)
		md, _ := info.Get("metadata")
		list, _ := md.(A2AJSON).Get("errors")
		var got []string
		for _, e := range list.([]any) {
			f, _ := e.(A2AJSON).Get("field")
			got = append(got, f.(string))
		}
		if !reflect.DeepEqual(got, c.fields) {
			t.Errorf("%s: %v", name, got)
		}
	}
}

func TestA2AIDAndConfigParams(t *testing.T) {
	if _, err := A2AIDParams(A2AJSON{}); err == nil {
		t.Error("id is required")
	}
	if ref, err := A2AIDParams(A2AJSON{{Key: "id", Value: "t"}}); err != nil || ref.TaskID != "t" {
		t.Errorf("%v %v", ref, err)
	}
	if _, err := A2AConfigParams(A2AJSON{{Key: "task_id", Value: "t"}}, true); err == nil {
		t.Error("config id is required")
	}
	if ref, err := A2AConfigParams(A2AJSON{{Key: "taskId", Value: "t"}}, false); err != nil || ref.TaskID != "t" {
		t.Errorf("%v %v", ref, err)
	}
}

func TestA2AListParams(t *testing.T) {
	token := A2AEncodePageToken(150)
	got, err := A2AListParams(A2AJSON{{Key: "pageSize", Value: json.Number("20")}, {Key: "pageToken", Value: token}})
	if err != nil || got.PageSize != 20 || got.Offset != 150 {
		t.Errorf("%+v %v", got, err)
	}
	for name, p := range map[string]A2AJSON{
		"filter":     {{Key: "contextId", Value: "c"}},
		"too small":  {{Key: "pageSize", Value: json.Number("0")}},
		"too big":    {{Key: "pageSize", Value: json.Number("101")}},
		"bad token":  {{Key: "pageToken", Value: "bm90IGEgbnVtYmVy"}},
		"past int32": {{Key: "pageToken", Value: A2AEncodePageToken(math.MaxInt32 + 1)}},
	} {
		if _, err := A2AListParams(p); err == nil {
			t.Errorf("%s accepted", name)
		}
	}
	if o, ok := A2ADecodePageToken("MTUw"); !ok || o != 150 {
		t.Errorf("%d %v", o, ok)
	}
	if _, ok := A2ADecodePageToken("MTUw" + "$"); ok {
		t.Error("a token that is not base64")
	}
}

func TestA2APushConfigs(t *testing.T) {
	params := A2AJSON{{Key: "other", Value: "x"}}
	next, stored := A2AUpsertPushConfig(params, "https://a", "c1")
	next, _ = A2AUpsertPushConfig(next, "https://b", "c1")
	next, _ = A2AUpsertPushConfig(next, "https://c", "c2")
	if len(A2AStoredPushConfigs(next)) != 2 || len(params) != 1 {
		t.Fatalf("%v %v", next, params)
	}
	if id, _ := stored.Get("id"); id != "c1" {
		t.Error(stored)
	}
	c, ok := A2AFindPushConfig(next, "c1")
	if url, _ := c.Get("url"); !ok || url != "https://b" {
		t.Errorf("an upsert replaces by id: %v", c)
	}
	res := A2APushResult("t1", c)
	if res[0].Key != "id" || res[1].Key != "taskId" || res[2].Key != "url" {
		t.Errorf("token-free result in field order: %v", res)
	}
	after, removed := A2ADeletePushConfig(next, "c1")
	if !removed || len(A2AStoredPushConfigs(after)) != 1 {
		t.Errorf("%v", after)
	}
	if _, removed := A2ADeletePushConfig(after, "gone"); removed {
		t.Error("nothing to remove")
	}
	if A2APushTokenSecret("t", "c") != "a2a_push_token:t:c" {
		t.Error("secret name")
	}
}
