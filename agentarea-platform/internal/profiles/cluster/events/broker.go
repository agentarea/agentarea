// Package events is the Redis Streams adapter of kernel/events: the broker
// (broker/redis_streams.py RedisStreamsBroker), its pub/sub live channels
// and the SETNX dedup cache (broker/dedup.py), on the keys and wire format
// already stored before cutover and read by the event service and SSE feeds.
package events

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
)

// lostGroupStart is where a group the broker lost is recreated: it went with
// its stream, so everything the stream holds now was never delivered to it.
const lostGroupStart = "0"

// stoppedConsumerIdle: a consumer idle this long with nothing pending belongs
// to a stopped process.
const stoppedConsumerIdle = 10 * time.Minute

const lagPage = 1000

// moveScript deletes first, so a second mover of the same id appends nothing.
const moveScript = `
if redis.call('XDEL', KEYS[1], ARGV[1]) == 0 then
    return false
end
return redis.call('XADD', KEYS[2], '*', unpack(ARGV, 2))
`

// pruneScript checks and deletes in one step, so a consumer that reads
// between the two does not lose its new pending entries.
const pruneScript = `
local consumers = redis.pcall('XINFO', 'CONSUMERS', KEYS[1], ARGV[1])
if type(consumers) == 'table' and consumers.err then
    if string.find(consumers.err, 'NOGROUP') or string.find(consumers.err, 'no such key') then
        return 0
    end
    return consumers
end
local removed = 0
for _, consumer in ipairs(consumers) do
    local f = {}
    for i = 1, #consumer, 2 do
        f[consumer[i]] = consumer[i + 1]
    end
    if f['pending'] == 0 and f['idle'] > tonumber(ARGV[2]) then
        redis.call('XGROUP', 'DELCONSUMER', KEYS[1], ARGV[1], f['name'])
        removed = removed + 1
    end
end
return removed
`

// Broker is kernel/events.Broker over Redis Streams. Callers name streams
// logically; every key is "<namespace>.<stream>" and messages come back with
// the logical name. A read or reclaim that finds its group gone (NOGROUP:
// the broker restarted without its data) recreates it from "0".
type Broker struct {
	client  *redis.Client
	prefix  string
	log     *slog.Logger
	stopped time.Duration
	move    *redis.Script
	prune   *redis.Script
}

var _ kernel.Broker = (*Broker)(nil)

// NewClient connects to url with RESP2, the protocol redis-py speaks.
func NewClient(url string) (*redis.Client, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, fmt.Errorf("AGENTAREA_REDIS_URL: %w", err)
	}
	opts.Protocol = 2
	return redis.NewClient(opts), nil
}

// NewBroker is a broker on client under namespace.
func NewBroker(client *redis.Client, namespace string, log *slog.Logger) (*Broker, error) {
	if namespace == "" {
		return nil, errors.New("events broker needs a namespace (AGENTAREA_EVENT_NAMESPACE)")
	}
	return &Broker{
		client: client, prefix: namespace + ".", log: log, stopped: stoppedConsumerIdle,
		move: redis.NewScript(moveScript), prune: redis.NewScript(pruneScript),
	}, nil
}

func (b *Broker) key(stream string) string { return b.prefix + stream }

func (b *Broker) logical(key string) string { return strings.TrimPrefix(key, b.prefix) }

func flatten(fields map[string]string) []string {
	out := make([]string, 0, 2*len(fields))
	for k, v := range fields {
		out = append(out, k, v)
	}
	return out
}

func minID(retention time.Duration) string {
	return strconv.FormatInt(time.Now().Add(-retention).UnixMilli(), 10) + "-0"
}

func (b *Broker) Submit(ctx context.Context, stream string, fields map[string]string, retention time.Duration) (string, error) {
	return b.client.XAdd(ctx, &redis.XAddArgs{
		Stream: b.key(stream), MinID: minID(retention), Approx: true, Values: flatten(fields),
	}).Result()
}

func (b *Broker) EnsureGroup(ctx context.Context, stream, group, start string) error {
	if start == "" {
		start = "$"
	}
	if err := b.client.XGroupCreateMkStream(ctx, b.key(stream), group, start).Err(); err != nil &&
		!strings.Contains(err.Error(), "BUSYGROUP") {
		return err
	}
	return b.pruneStopped(ctx, stream, group)
}

func (b *Broker) pruneStopped(ctx context.Context, stream, group string) error {
	removed, err := b.prune.Run(ctx, b.client, []string{b.key(stream)}, group, b.stopped.Milliseconds()).Int()
	if err != nil {
		return fmt.Errorf("prune stopped consumers of %s on %s: %w", group, stream, err)
	}
	if removed > 0 {
		b.log.InfoContext(ctx, "Removed stopped consumers", "count", removed, "group", group, "stream", stream)
	}
	return nil
}

func isLostGroup(err error) bool { return err != nil && strings.HasPrefix(err.Error(), "NOGROUP") }

func (b *Broker) recreateLostGroup(ctx context.Context, streams []string, group string, lost error) error {
	b.log.WarnContext(ctx, "Consumer group is gone; the broker lost its data. Recreating it",
		"group", group, "streams", strings.Join(streams, ", "), "start", lostGroupStart, "error", lost)
	for _, s := range streams {
		if err := b.EnsureGroup(ctx, s, group, lostGroupStart); err != nil {
			return err
		}
	}
	return nil
}

func (b *Broker) readGroup(ctx context.Context, streams []string, group, consumer string, count int, block time.Duration) ([]redis.XStream, error) {
	args := &redis.XReadGroupArgs{Group: group, Consumer: consumer, Count: int64(count), Block: block}
	for _, s := range streams {
		args.Streams = append(args.Streams, b.key(s))
	}
	for range streams {
		args.Streams = append(args.Streams, ">")
	}
	res, err := b.client.XReadGroup(ctx, args).Result()
	if isLostGroup(err) {
		if err := b.recreateLostGroup(ctx, streams, group, err); err != nil {
			return nil, err
		}
		res, err = b.client.XReadGroup(ctx, args).Result()
	}
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	return res, err
}

func (b *Broker) messages(res []redis.XStream) []kernel.Message {
	var out []kernel.Message
	for _, s := range res {
		for _, m := range s.Messages {
			out = append(out, kernel.Message{ID: m.ID, Fields: stringFields(m.Values), DeliveryCount: 1, Stream: b.logical(s.Stream)})
		}
	}
	return out
}

func stringFields(values map[string]any) map[string]string {
	out := make(map[string]string, len(values))
	for k, v := range values {
		switch x := v.(type) {
		case string:
			out[k] = x
		default:
			out[k] = fmt.Sprint(x)
		}
	}
	return out
}

func (b *Broker) Consume(ctx context.Context, stream, group, consumer string, count int, block time.Duration) ([]kernel.Message, error) {
	res, err := b.readGroup(ctx, []string{stream}, group, consumer, count, block)
	if err != nil {
		return nil, err
	}
	return b.withDeliveryCount(ctx, stream, group, b.messages(res))
}

func (b *Broker) ConsumeMany(ctx context.Context, streams []string, group, consumer string, count int, block time.Duration) ([]kernel.Message, error) {
	if len(streams) == 0 {
		return nil, nil
	}
	res, err := b.readGroup(ctx, streams, group, consumer, count, block)
	if err != nil {
		return nil, err
	}
	var order []string
	by := map[string][]kernel.Message{}
	for _, m := range b.messages(res) {
		if _, ok := by[m.Stream]; !ok {
			order = append(order, m.Stream)
		}
		by[m.Stream] = append(by[m.Stream], m)
	}
	var out []kernel.Message
	for _, s := range order {
		counted, err := b.withDeliveryCount(ctx, s, group, by[s])
		if err != nil {
			return nil, err
		}
		out = append(out, counted...)
	}
	return out, nil
}

// withDeliveryCount sets each message's count from its own pending entry, one
// XPENDING per id, pipelined: a range over the batch would count other
// pending entries between them.
func (b *Broker) withDeliveryCount(ctx context.Context, stream, group string, msgs []kernel.Message) ([]kernel.Message, error) {
	if len(msgs) == 0 {
		return msgs, nil
	}
	pipe := b.client.Pipeline()
	cmds := make([]*redis.XPendingExtCmd, len(msgs))
	for i, m := range msgs {
		cmds[i] = pipe.XPendingExt(ctx, &redis.XPendingExtArgs{Stream: b.key(stream), Group: group, Start: m.ID, End: m.ID, Count: 1})
	}
	if _, err := pipe.Exec(ctx); err != nil && !errors.Is(err, redis.Nil) {
		return nil, err
	}
	for i, cmd := range cmds {
		entries, err := cmd.Result()
		if err != nil && !errors.Is(err, redis.Nil) {
			return nil, err
		}
		if len(entries) == 0 {
			return nil, fmt.Errorf("message %s on %s was just claimed by %s but is not pending", msgs[i].ID, stream, group)
		}
		msgs[i].DeliveryCount = int(entries[0].RetryCount)
	}
	return msgs, nil
}

func (b *Broker) Ack(ctx context.Context, stream, group, messageID string) error {
	return b.client.XAck(ctx, b.key(stream), group, messageID).Err()
}

func (b *Broker) Autoclaim(ctx context.Context, stream, group, consumer string, minIdle time.Duration, start string, count int) ([]kernel.Message, error) {
	if start == "" {
		start = "0-0"
	}
	claimed, _, err := b.client.XAutoClaim(ctx, &redis.XAutoClaimArgs{
		Stream: b.key(stream), Group: group, Consumer: consumer, MinIdle: minIdle, Start: start, Count: int64(count),
	}).Result()
	if isLostGroup(err) {
		return nil, b.recreateLostGroup(ctx, []string{stream}, group, err)
	}
	if err != nil && !errors.Is(err, redis.Nil) {
		return nil, err
	}
	if err := b.pruneStopped(ctx, stream, group); err != nil {
		return nil, err
	}
	msgs := make([]kernel.Message, 0, len(claimed))
	for _, m := range claimed {
		msgs = append(msgs, kernel.Message{ID: m.ID, Fields: stringFields(m.Values), DeliveryCount: 1, Stream: stream})
	}
	return b.withDeliveryCount(ctx, stream, group, msgs)
}

func (b *Broker) Tail(ctx context.Context, stream, lastID string, block time.Duration, count int) (string, []kernel.Message, error) {
	if lastID == "" {
		lastID = "$"
	}
	res, err := b.client.XRead(ctx, &redis.XReadArgs{Streams: []string{b.key(stream), lastID}, Count: int64(count), Block: block}).Result()
	if errors.Is(err, redis.Nil) {
		return lastID, nil, nil
	}
	if err != nil {
		return lastID, nil, err
	}
	msgs := b.messages(res)
	if len(msgs) == 0 {
		return lastID, nil, nil
	}
	return msgs[len(msgs)-1].ID, msgs, nil
}

// GroupInfo reads XINFO GROUPS raw: go-redis reports a nil lag as 0, and
// Redis 7+ gives no lag once entries were deleted past the group's position.
func (b *Broker) GroupInfo(ctx context.Context, stream, group string) (*kernel.GroupInfo, error) {
	raw, err := b.client.Do(ctx, "XINFO", "GROUPS", b.key(stream)).Slice()
	if err != nil {
		if strings.Contains(err.Error(), "no such key") {
			return nil, nil
		}
		return nil, err
	}
	for _, g := range raw {
		pairs, ok := g.([]any)
		if !ok {
			continue
		}
		f := map[string]any{}
		for i := 0; i+1 < len(pairs); i += 2 {
			if k, ok := pairs[i].(string); ok {
				f[k] = pairs[i+1]
			}
		}
		if f["name"] != group {
			continue
		}
		last, _ := f["last-delivered-id"].(string)
		info := &kernel.GroupInfo{LastDeliveredID: last}
		if n, ok := f["consumers"].(int64); ok {
			info.Consumers = int(n)
		}
		if lag, ok := f["lag"].(int64); ok {
			info.Lag = lag
		} else if info.Lag, err = b.countAfter(ctx, stream, last); err != nil {
			return nil, err
		}
		return info, nil
	}
	return nil, nil
}

func (b *Broker) countAfter(ctx context.Context, stream, lastID string) (int64, error) {
	var total int64
	start := "(" + lastID
	for {
		entries, err := b.client.XRangeN(ctx, b.key(stream), start, "+", lagPage).Result()
		if err != nil {
			return 0, err
		}
		total += int64(len(entries))
		if len(entries) < lagPage {
			return total, nil
		}
		start = "(" + entries[len(entries)-1].ID
	}
}

func (b *Broker) Pending(ctx context.Context, stream, group string) (kernel.PendingSummary, error) {
	p, err := b.client.XPending(ctx, b.key(stream), group).Result()
	if err != nil {
		return kernel.PendingSummary{}, err
	}
	if p.Count == 0 {
		return kernel.PendingSummary{}, nil
	}
	ms, err := strconv.ParseInt(strings.SplitN(p.Lower, "-", 2)[0], 10, 64)
	if err != nil {
		return kernel.PendingSummary{}, fmt.Errorf("pending min id %q: %w", p.Lower, err)
	}
	age := max(0, time.Duration(time.Now().UnixMilli()-ms)*time.Millisecond)
	return kernel.PendingSummary{Count: p.Count, OldestAge: &age}, nil
}

func (b *Broker) Length(ctx context.Context, stream string) (int64, error) {
	return b.client.XLen(ctx, b.key(stream)).Result()
}

func (b *Broker) ReadRange(ctx context.Context, stream, start, end string, count int) ([]kernel.Message, error) {
	entries, err := b.client.XRangeN(ctx, b.key(stream), start, end, int64(count)).Result()
	if err != nil {
		return nil, err
	}
	out := make([]kernel.Message, 0, len(entries))
	for _, m := range entries {
		out = append(out, kernel.Message{ID: m.ID, Fields: stringFields(m.Values), DeliveryCount: 1, Stream: stream})
	}
	return out, nil
}

func (b *Broker) LastID(ctx context.Context, stream string) (string, error) {
	newest, err := b.client.XRevRangeN(ctx, b.key(stream), "+", "-", 1).Result()
	if err != nil {
		return "", err
	}
	if len(newest) == 0 {
		return "0-0", nil
	}
	return newest[0].ID, nil
}

// Notify publishes fields as json.dumps(fields) to the namespaced channel.
func (b *Broker) Notify(ctx context.Context, channel string, fields map[string]string) error {
	if fields == nil {
		fields = map[string]string{}
	}
	payload, err := kernel.PyJSON(fields)
	if err != nil {
		return err
	}
	return b.client.Publish(ctx, b.key(channel), payload).Err()
}

func (b *Broker) Move(ctx context.Context, source, messageID, target string, fields map[string]string) (string, error) {
	args := append([]any{messageID}, toAny(flatten(fields))...)
	id, err := b.move.Run(ctx, b.client, []string{b.key(source), b.key(target)}, args...).Text()
	if errors.Is(err, redis.Nil) {
		return "", nil
	}
	return id, err
}

func toAny(s []string) []any {
	out := make([]any, len(s))
	for i, v := range s {
		out[i] = v
	}
	return out
}

// OpenLive is one pub/sub connection; channels carry the namespace.
func (b *Broker) OpenLive(ctx context.Context) (kernel.LiveChannels, error) {
	return &liveChannels{ps: b.client.Subscribe(ctx), b: b}, nil
}

type liveChannels struct {
	ps         *redis.PubSub
	b          *Broker
	subscribed atomic.Int64
}

func (l *liveChannels) Subscribe(ctx context.Context, channel string) error {
	if err := l.ps.Subscribe(ctx, l.b.key(channel)); err != nil {
		return err
	}
	l.subscribed.Add(1)
	return nil
}

func (l *liveChannels) Unsubscribe(ctx context.Context, channel string) error {
	if err := l.ps.Unsubscribe(ctx, l.b.key(channel)); err != nil {
		return err
	}
	if l.subscribed.Add(-1) < 0 {
		l.subscribed.Store(0)
	}
	return nil
}

func (l *liveChannels) Next(ctx context.Context, timeout time.Duration) (string, map[string]string, bool, error) {
	if l.subscribed.Load() == 0 {
		select {
		case <-ctx.Done():
			return "", nil, false, ctx.Err()
		case <-time.After(timeout):
			return "", nil, false, nil
		}
	}
	deadline := time.Now().Add(timeout)
	for {
		left := time.Until(deadline)
		if left <= 0 {
			return "", nil, false, nil
		}
		msg, err := l.ps.ReceiveTimeout(ctx, left)
		if err != nil {
			var ne interface{ Timeout() bool }
			if errors.As(err, &ne) && ne.Timeout() {
				return "", nil, false, nil
			}
			return "", nil, false, err
		}
		m, ok := msg.(*redis.Message)
		if !ok {
			continue
		}
		var fields map[string]string
		if err := json.Unmarshal([]byte(m.Payload), &fields); err != nil {
			return "", nil, false, fmt.Errorf("live message on %s: %w", m.Channel, err)
		}
		return l.b.logical(m.Channel), fields, true, nil
	}
}

func (l *liveChannels) Close() error { return l.ps.Close() }
