// Package tracing installs the OpenTelemetry tracer provider. The exporter is
// configured by the SDK's own OTEL_* variables; AGENTAREA_OTEL_ENABLED gates it.
package tracing

import (
	"context"
	"fmt"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

const (
	serviceName = "agentarea-event-service"
	protocolEnv = "OTEL_EXPORTER_OTLP_PROTOCOL"

	AttrSourceID        = attribute.Key("agentarea.source.id")
	AttrSourceTransport = attribute.Key("agentarea.source.transport")
	AttrItemsFetched    = attribute.Key("agentarea.poll.items_fetched")

	// TraceparentField is the inbound stream field carrying the W3C traceparent.
	TraceparentField = "traceparent"
)

// Shutdown flushes and stops the tracer provider.
type Shutdown func(context.Context) error

// Setup installs a batching OTLP tracer provider when enabled. Disabled, the
// global provider stays the no-op one and spans are never recorded.
func Setup(ctx context.Context, enabled bool) (Shutdown, error) {
	if !enabled {
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := newExporter(ctx, os.Getenv(protocolEnv))
	if err != nil {
		return nil, err
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(attribute.String("service.name", serviceName)),
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
	)
	if err != nil {
		return nil, fmt.Errorf("build otel resource: %w", err)
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(provider)
	return provider.Shutdown, nil
}

func newExporter(ctx context.Context, protocol string) (sdktrace.SpanExporter, error) {
	switch protocol {
	case "", "grpc":
		exporter, err := otlptracegrpc.New(ctx)
		if err != nil {
			return nil, fmt.Errorf("create otlp grpc exporter: %w", err)
		}
		return exporter, nil
	case "http/protobuf":
		exporter, err := otlptracehttp.New(ctx)
		if err != nil {
			return nil, fmt.Errorf("create otlp http exporter: %w", err)
		}
		return exporter, nil
	default:
		return nil, fmt.Errorf("%s=%q is not supported: use grpc or http/protobuf", protocolEnv, protocol)
	}
}

// Tracer returns the service tracer from the global provider.
func Tracer() trace.Tracer {
	return otel.Tracer("github.com/agentarea/event-service")
}

// RecordError marks the span failed with err.
func RecordError(span trace.Span, err error) {
	span.RecordError(err)
	span.SetStatus(codes.Error, err.Error())
}

// Traceparent renders the W3C traceparent of the span in ctx, or "" when ctx
// carries no valid span context.
func Traceparent(ctx context.Context) string {
	carrier := propagation.MapCarrier{}
	propagation.TraceContext{}.Inject(ctx, carrier)
	return carrier.Get(TraceparentField)
}
