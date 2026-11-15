package events

import (
	"hash/crc32"
	"strconv"
	"time"

	"github.com/google/uuid"
)

// Logical topic and channel names (broker/topics.py); the broker adapter puts
// the namespace in front. They are a contract with the Python backend and
// the event service.
const (
	StreamEvents   = "streams.events"
	StreamsIngest  = "streams.ingest"
	TaskEvents     = "tasks.events"
	TaskLive       = "tasks.live"
	StreamsLive    = "streams.live"
	DomainEvents   = "domain.events"
	ExternalEvents = "streams.external"

	RouterGroup         = "router"
	EventsViewGroup     = "events-view"
	DeliveryGroup       = "delivery"
	PlatformGroup       = "platform"
	TriggerOutcomeGroup = "trigger-outcomes"
	IngestGroup         = "ingest"
)

// BusRetention is how long a topic keeps its entries; DeadLetterRetention
// how long dead letters wait for an operator.
const (
	BusRetention        = 72 * time.Hour
	DeadLetterRetention = 14 * 24 * time.Hour
)

// Dead-letter fields: why a message failed, and the topic it came from.
const (
	DeadLetterReasonField = "fatal_reason"
	DeadLetterSourceField = "source_topic"
	// DeadLetterGroupField names the group a message dead-lettered from; a replay targets that group only
	// through TargetGroupField, which every other group acknowledges without processing.
	DeadLetterGroupField = "source_group"
	TargetGroupField     = "target_group"
)

// StreamEventsPartition carries every event of one stream, so its order holds.
func StreamEventsPartition(streamID uuid.UUID, partitions int) string {
	return StreamEvents + "." + strconv.FormatUint(uint64(crc32.ChecksumIEEE(streamID[:]))%uint64(partitions), 10)
}

// StreamEventsPartitions is every partition of the stream-events topic.
func StreamEventsPartitions(partitions int) []string {
	out := make([]string, partitions)
	for n := range partitions {
		out[n] = StreamEvents + "." + strconv.Itoa(n)
	}
	return out
}

// DeadLetterTopic is where group's failures on topic go.
func DeadLetterTopic(topic, group string) string { return topic + "." + group + ".dlq" }

// TaskLiveChannel is the pub/sub channel of a task's live-only signals.
func TaskLiveChannel(taskID string) string { return TaskLive + "." + taskID }

// StreamsLiveChannel is the pub/sub channel of a workspace's events-page notices.
func StreamsLiveChannel(workspaceID string) string { return StreamsLive + "." + workspaceID }

// DomainEventsTopic is where the outbox relay publishes an event type.
func DomainEventsTopic(eventType string) string { return DomainEvents + "." + eventType }

// ExternalRetryTopic is where a webhook delivery waits for its attempt-th retry.
func ExternalRetryTopic(attempt int) string { return ExternalEvents + ".retry." + strconv.Itoa(attempt) }
