package domain

import (
	"crypto/sha1" //nolint:gosec // uuid5 is defined over SHA-1
	"encoding/hex"
	"errors"
	"strings"
)

// MaxInlineBodyBytes is the encoded body size past which a body moves to the workspace's files.
const MaxInlineBodyBytes = 64 * 1024

// MaxRequestBytes is the largest request a source may deliver.
const MaxRequestBytes = 25 * 1024 * 1024

// Namespaces of the derived ids (domain/keys.py, batches.py); persisted, kept byte for byte.
const (
	StreamEventNamespace = "6f1c7b8e-3d2a-4f5e-9b0c-1a2b3c4d5e6f"
	TaskNamespace        = "0b6a6f2e-9a51-4c43-8f3e-2d7c1e5a9b40"
	BatchNamespace       = "3c9e2b71-5d84-4f0a-b6e3-8a1f2c7d9e45"
)

func parseUUID(s string) ([16]byte, error) {
	var out [16]byte
	h := strings.ReplaceAll(strings.TrimSuffix(strings.TrimPrefix(strings.ToLower(s), "urn:uuid:"), "}"), "-", "")
	h = strings.TrimPrefix(h, "{")
	if len(h) != 32 {
		return out, errors.New("invalid uuid: " + s)
	}
	b, err := hex.DecodeString(h)
	if err != nil {
		return out, errors.New("invalid uuid: " + s)
	}
	copy(out[:], b)
	return out, nil
}

func formatUUID(b [16]byte) string {
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32]
}

// UUID5 is uuid.uuid5(namespace, name); namespace must be a UUID.
func UUID5(namespace, name string) (string, error) {
	ns, err := parseUUID(namespace)
	if err != nil {
		return "", err
	}
	h := sha1.New() //nolint:gosec // uuid5 is defined over SHA-1
	h.Write(ns[:])
	h.Write([]byte(name))
	sum := h.Sum(nil)
	var out [16]byte
	copy(out[:], sum[:16])
	out[6] = (out[6] & 0x0f) | 0x50
	out[8] = (out[8] & 0x3f) | 0x80
	return formatUUID(out), nil
}

func mustUUID5(namespace, name string) string {
	id, err := UUID5(namespace, name)
	if err != nil {
		panic(err)
	}
	return id
}

// CanonicalUUID is s in Python's str(UUID(s)) form.
func CanonicalUUID(s string) (string, error) {
	b, err := parseUUID(s)
	if err != nil {
		return "", err
	}
	return formatUUID(b), nil
}

// EventIDFor is event_id_for: uuid5(STREAM_EVENT_NAMESPACE, "<stream>:<key>").
func EventIDFor(streamID, eventKey string) string {
	return mustUUID5(StreamEventNamespace, streamID+":"+eventKey)
}

// DerivedEventID is derived_event_id: uuid5(processor or forward, source event id).
func DerivedEventID(ownerID, sourceEventID string) (string, error) {
	return UUID5(ownerID, sourceEventID)
}

// ProcessorOutputID is processor_output_id: uuid5(processor, "<source event>:<index>").
func ProcessorOutputID(processorID, sourceEventID string, index int) (string, error) {
	return UUID5(processorID, sourceEventID+":"+itoa(index))
}

// TaskIDFor is task_id_for: uuid5(_TASK_NAMESPACE, "<subscription>:<event>").
func TaskIDFor(subscriptionID, eventID string) string {
	return mustUUID5(TaskNamespace, subscriptionID+":"+eventID)
}

// BatchWorkflowID is the batch workflow of a trigger, one per caller when given.
func BatchWorkflowID(triggerID, caller string) string {
	if caller == "" {
		return "trigger-batch-" + triggerID
	}
	return "trigger-batch-" + triggerID + "-" + mustUUID5(BatchNamespace, caller)
}

// BatchTaskID is the task a batch fires: uuid5(_BATCH_NAMESPACE, "<subscription>:batch:<first event>").
func BatchTaskID(subscriptionID, firstEventID string) string {
	return mustUUID5(BatchNamespace, subscriptionID+":batch:"+firstEventID)
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}
