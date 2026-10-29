// Package telemetry installs the OpenTelemetry tracer and meter providers
// (ADR-0048). AGENTAREA_OTEL_ENABLED gates both; the exporters read the SDK's
// own OTEL_* variables. Instruments stay no-ops until Setup installs a provider.
package telemetry

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"

	"go.opentelemetry.io/contrib/exporters/autoexport"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

const (
	serviceName = "agentarea-event-service"
	scope       = "github.com/agentarea/event-service"

	endpointEnv        = "OTEL_EXPORTER_OTLP_ENDPOINT"
	tracesEndpointEnv  = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
	metricsEndpointEnv = "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"
	tracesExporterEnv  = "OTEL_TRACES_EXPORTER"
	metricsExporterEnv = "OTEL_METRICS_EXPORTER"
	protocolEnv        = "OTEL_EXPORTER_OTLP_PROTOCOL"
	metricsProtocolEnv = "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL"
	intervalEnv        = "OTEL_METRIC_EXPORT_INTERVAL"

	defaultInterval = 15 * time.Second

	AttrSourceID        = attribute.Key("agentarea.source.id")
	AttrSourceTransport = attribute.Key("agentarea.source.transport")
	AttrItemsFetched    = attribute.Key("agentarea.poll.items_fetched")

	// TraceparentField is the inbound stream field carrying the W3C traceparent.
	TraceparentField = "traceparent"
)

// Shutdown flushes and stops the providers.
type Shutdown func(context.Context) error

// Setup installs the tracer and meter providers when enabled. Disabled, the
// global providers stay the no-op ones and nothing is recorded or required.
func Setup(ctx context.Context, enabled bool, version string) (Shutdown, error) {
	if !enabled {
		return func(context.Context) error { return nil }, nil
	}
	if err := checkEndpoints(os.Getenv); err != nil {
		return nil, err
	}
	res, err := newResource(ctx, version)
	if err != nil {
		return nil, err
	}
	spans, err := autoexport.NewSpanExporter(ctx)
	if err != nil {
		return nil, fmt.Errorf("create span exporter: %w", err)
	}
	reader, err := newMetricReader(ctx, os.Getenv)
	if err != nil {
		return nil, errors.Join(fmt.Errorf("create metric reader: %w", err), spans.Shutdown(ctx))
	}
	tracerProvider := sdktrace.NewTracerProvider(sdktrace.WithBatcher(spans), sdktrace.WithResource(res))
	meterProvider := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(reader), sdkmetric.WithResource(res), sdkmetric.WithView(sdkViews()...),
	)
	shutdown := func(ctx context.Context) error {
		return errors.Join(meterProvider.Shutdown(ctx), tracerProvider.Shutdown(ctx))
	}
	if err := registerHeartbeat(meterProvider); err != nil {
		return nil, errors.Join(err, shutdown(ctx))
	}
	if err := runtime.Start(runtime.WithMeterProvider(meterProvider)); err != nil {
		return nil, errors.Join(fmt.Errorf("start runtime metrics: %w", err), shutdown(ctx))
	}
	otel.SetTracerProvider(tracerProvider)
	otel.SetMeterProvider(meterProvider)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	return shutdown, nil
}

// checkEndpoints refuses a signal exported over OTLP with no endpoint: the SDK
// would silently send it to localhost instead.
func checkEndpoints(getenv func(string) string) error {
	if getenv(endpointEnv) != "" {
		return nil
	}
	for _, signal := range [][2]string{{tracesExporterEnv, tracesEndpointEnv}, {metricsExporterEnv, metricsEndpointEnv}} {
		if exporter := getenv(signal[0]); exporter != "" && exporter != "otlp" {
			continue
		}
		if getenv(signal[1]) == "" {
			return fmt.Errorf("AGENTAREA_OTEL_ENABLED is true but %s is empty (or set %s)", endpointEnv, signal[1])
		}
	}
	return nil
}

func newResource(ctx context.Context, version string) (*resource.Resource, error) {
	host, err := os.Hostname()
	if err != nil {
		return nil, fmt.Errorf("resolve service.instance.id: %w", err)
	}
	res, err := resource.New(ctx,
		resource.WithAttributes(
			attribute.String("service.name", serviceName),
			attribute.String("service.namespace", "agentarea"),
			attribute.String("service.version", version),
			attribute.String("service.instance.id", fmt.Sprintf("%s-%d", host, os.Getpid())),
		),
		resource.WithTelemetrySDK(),
		resource.WithFromEnv(),
	)
	if err != nil {
		return nil, fmt.Errorf("build otel resource: %w", err)
	}
	return res, nil
}

// newMetricReader pushes cumulative OTLP every OTEL_METRIC_EXPORT_INTERVAL
// (15 s by default); any other OTEL_METRICS_EXPORTER, such as prometheus or
// none, is the SDK's own.
func newMetricReader(ctx context.Context, getenv func(string) string) (sdkmetric.Reader, error) {
	if name := getenv(metricsExporterEnv); name != "" && name != "otlp" {
		return autoexport.NewMetricReader(ctx)
	}
	interval, err := exportInterval(getenv)
	if err != nil {
		return nil, err
	}
	protocolName := metricsProtocolEnv
	protocol := getenv(protocolName)
	if protocol == "" {
		protocolName = protocolEnv
		protocol = getenv(protocolName)
	}
	var exporter sdkmetric.Exporter
	switch protocol {
	case "", "http/protobuf":
		exporter, err = otlpmetrichttp.New(ctx, otlpmetrichttp.WithTemporalitySelector(sdkmetric.DefaultTemporalitySelector))
	case "grpc":
		exporter, err = otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithTemporalitySelector(sdkmetric.DefaultTemporalitySelector))
	default:
		return nil, fmt.Errorf("%s=%q is not supported: use http/protobuf or grpc", protocolName, protocol)
	}
	if err != nil {
		return nil, err
	}
	return sdkmetric.NewPeriodicReader(exporter, sdkmetric.WithInterval(interval)), nil
}

func exportInterval(getenv func(string) string) (time.Duration, error) {
	raw := getenv(intervalEnv)
	if raw == "" {
		return defaultInterval, nil
	}
	millis, err := strconv.Atoi(raw)
	if err != nil || millis <= 0 {
		return 0, fmt.Errorf("%s=%q must be a positive number of milliseconds", intervalEnv, raw)
	}
	return time.Duration(millis) * time.Millisecond, nil
}

// registerHeartbeat exports the process uptime, whose absence is how a silent
// exporter is told apart from an idle service.
func registerHeartbeat(provider metric.MeterProvider) error {
	started := time.Now()
	_, err := provider.Meter(scope).Float64ObservableGauge(ProcessUptime,
		metric.WithUnit("s"),
		metric.WithDescription("Seconds since the process started."),
		metric.WithFloat64Callback(func(_ context.Context, observer metric.Float64Observer) error {
			observer.Observe(time.Since(started).Seconds())
			return nil
		}),
	)
	return err
}

// Meter returns the service meter from the global provider.
func Meter() metric.Meter {
	return otel.Meter(scope)
}

// Tracer returns the service tracer from the global provider.
func Tracer() trace.Tracer {
	return otel.Tracer(scope)
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
