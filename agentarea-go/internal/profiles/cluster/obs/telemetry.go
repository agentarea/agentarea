// Package obs is the process's OpenTelemetry setup (observability/
// telemetry.py setup_telemetry, ADR-0048): AGENTAREA_OTEL_ENABLED is the
// gate, the rest is the specification's own OTEL_* variables. Traces go
// over OTLP; metrics over OTLP, a Prometheus endpoint, or nowhere; every
// instrument not in kernel/obs.Instruments is dropped.
package obs

import (
	"context"
	"errors"
	"fmt"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/contrib/exporters/autoexport"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"

	kernel "github.com/agentarea/agentarea/agentarea-go/internal/kernel/obs"
)

const (
	endpointEnv        = "OTEL_EXPORTER_OTLP_ENDPOINT"
	tracesEndpointEnv  = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
	metricsEndpointEnv = "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"
	protocolEnv        = "OTEL_EXPORTER_OTLP_PROTOCOL"
	metricsExporterEnv = "OTEL_METRICS_EXPORTER"
	intervalEnv        = "OTEL_METRIC_EXPORT_INTERVAL"
	serviceNameEnv     = "OTEL_SERVICE_NAME"
	semconvOptInEnv    = "OTEL_SEMCONV_STABILITY_OPT_IN"

	defaultInterval = 15 * time.Second
)

// Options are what the process knows about itself.
type Options struct {
	// Enabled is AGENTAREA_OTEL_ENABLED.
	Enabled bool
	// Service is the service.name unless OTEL_SERVICE_NAME overrides it.
	Service string
	// Version is service.version unless the resource environment sets it.
	Version string
	// Environment is AGENTAREA_ENV (deployment.environment.name).
	Environment string
	// Getenv stands in for os.Getenv in the checks; the exporters read the
	// process environment themselves.
	Getenv func(string) string
}

// Telemetry implements kernel.Telemetry.
type Telemetry struct {
	shutdown func(context.Context) error
}

// Shutdown flushes and stops the providers.
func (t *Telemetry) Shutdown(ctx context.Context) error { return t.shutdown(ctx) }

var _ kernel.Telemetry = (*Telemetry)(nil)

// Config is the telemetry configuration read and checked from the
// environment, as setup_telemetry checks it before installing anything.
type Config struct {
	MetricsExporter string
	TracesProtocol  string
	MetricsProtocol string
	ExportInterval  time.Duration
	ServiceName     string
}

func env(getenv func(string) string, name string) string { return strings.TrimSpace(getenv(name)) }

// pyRepr is Python's repr of a str, as the error messages quote values.
func pyRepr(s string) string {
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		return `"` + s + `"`
	}
	return "'" + strings.ReplaceAll(s, "'", `\'`) + "'"
}

// MetricsExporter is metrics_exporter.
func MetricsExporter(getenv func(string) string) (string, error) {
	v := strings.ToLower(env(getenv, metricsExporterEnv))
	if v == "" {
		v = "otlp"
	}
	if !slices.Contains([]string{"otlp", "prometheus", "none"}, v) {
		return "", fmt.Errorf("%s=%s is not supported; use one of otlp, prometheus, none", metricsExporterEnv, pyRepr(v))
	}
	return v, nil
}

// Protocol is otlp_protocol for signal TRACES or METRICS.
func Protocol(getenv func(string) string, signal string) (string, error) {
	name := "OTEL_EXPORTER_OTLP_" + signal + "_PROTOCOL"
	if env(getenv, name) == "" {
		name = protocolEnv
	}
	v := strings.ToLower(env(getenv, name))
	if v == "" {
		v = "http/protobuf"
	}
	if v != "http/protobuf" && v != "grpc" {
		return "", fmt.Errorf("%s=%s is not supported; use one of http/protobuf, grpc", name, pyRepr(v))
	}
	return v, nil
}

// MissingEndpoint is missing_otlp_endpoint: why an exporting signal has no
// endpoint, empty when each has one.
func MissingEndpoint(getenv func(string) string, metricsOTLP bool) string {
	if env(getenv, endpointEnv) != "" {
		return ""
	}
	traces := env(getenv, tracesEndpointEnv) != ""
	metrics := env(getenv, metricsEndpointEnv) != ""
	if traces && (metrics || !metricsOTLP) {
		return ""
	}
	if traces {
		return "AGENTAREA_OTEL_ENABLED is true and OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is set, but " +
			"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT is not: set it too, or set " +
			"OTEL_EXPORTER_OTLP_ENDPOINT for every signal"
	}
	msg := "AGENTAREA_OTEL_ENABLED is true but OTEL_EXPORTER_OTLP_ENDPOINT is not set " +
		"(nor OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
	if metricsOTLP {
		return msg + " and OTEL_EXPORTER_OTLP_METRICS_ENDPOINT)"
	}
	return msg + ")"
}

// ExportInterval is export_interval_ms.
func ExportInterval(getenv func(string) string) (time.Duration, error) {
	raw := env(getenv, intervalEnv)
	if raw == "" {
		return defaultInterval, nil
	}
	ms, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("%s=%s is not milliseconds", intervalEnv, pyRepr(raw))
	}
	if ms <= 0 {
		return 0, fmt.Errorf("%s=%s must be positive", intervalEnv, pyRepr(raw))
	}
	return time.Duration(ms) * time.Millisecond, nil
}

// CheckSemconvOptIn is semconv_opt_in: a set OTEL_SEMCONV_STABILITY_OPT_IN
// must keep the stable HTTP metrics the views name.
func CheckSemconvOptIn(getenv func(string) string) error {
	v := env(getenv, semconvOptInEnv)
	if v == "" {
		return nil
	}
	var tokens []string
	for t := range strings.SplitSeq(v, ",") {
		tokens = append(tokens, strings.TrimSpace(t))
	}
	if slices.Contains(tokens, "http") && !slices.Contains(tokens, "http/dup") {
		return nil
	}
	return fmt.Errorf("%s=%s conflicts with the stable HTTP metrics telemetry exports; unset it or include 'http'",
		semconvOptInEnv, pyRepr(v))
}

// LoadConfig checks the environment as setup_telemetry does, in its order.
func LoadConfig(getenv func(string) string, service string) (Config, error) {
	exporter, err := MetricsExporter(getenv)
	if err != nil {
		return Config{}, err
	}
	if msg := MissingEndpoint(getenv, exporter == "otlp"); msg != "" {
		return Config{}, errors.New(msg)
	}
	c := Config{MetricsExporter: exporter, ServiceName: service}
	if c.TracesProtocol, err = Protocol(getenv, "TRACES"); err != nil {
		return Config{}, err
	}
	if exporter == "otlp" {
		if c.MetricsProtocol, err = Protocol(getenv, "METRICS"); err != nil {
			return Config{}, err
		}
		if c.ExportInterval, err = ExportInterval(getenv); err != nil {
			return Config{}, err
		}
	}
	if err := CheckSemconvOptIn(getenv); err != nil {
		return Config{}, err
	}
	if name := env(getenv, serviceNameEnv); name != "" {
		c.ServiceName = name
	}
	return c, nil
}

// Setup installs tracing and metrics when enabled; disabled, the global
// providers stay the no-op ones and nothing is required.
func Setup(ctx context.Context, opts Options) (*Telemetry, error) {
	if !opts.Enabled {
		return &Telemetry{shutdown: func(context.Context) error { return nil }}, nil
	}
	if opts.Getenv == nil {
		opts.Getenv = os.Getenv
	}
	cfg, err := LoadConfig(opts.Getenv, opts.Service)
	if err != nil {
		return nil, err
	}
	res, err := Resource(ctx, cfg.ServiceName, opts.Version, opts.Environment)
	if err != nil {
		return nil, err
	}
	spans, err := spanExporter(ctx, cfg.TracesProtocol)
	if err != nil {
		return nil, fmt.Errorf("create span exporter: %w", err)
	}
	reader, err := metricReader(ctx, cfg)
	if err != nil {
		return nil, errors.Join(fmt.Errorf("create metric reader: %w", err), spans.Shutdown(ctx))
	}
	tracerProvider := sdktrace.NewTracerProvider(sdktrace.WithBatcher(spans), sdktrace.WithResource(res))
	meterOpts := []sdkmetric.Option{sdkmetric.WithResource(res), sdkmetric.WithView(View)}
	if reader != nil {
		meterOpts = append(meterOpts, sdkmetric.WithReader(reader))
	}
	meterProvider := sdkmetric.NewMeterProvider(meterOpts...)
	shutdown := func(ctx context.Context) error {
		return errors.Join(meterProvider.Shutdown(ctx), tracerProvider.Shutdown(ctx))
	}
	if err := RegisterUptime(meterProvider); err != nil {
		return nil, errors.Join(err, shutdown(ctx))
	}
	otel.SetTracerProvider(tracerProvider)
	otel.SetMeterProvider(meterProvider)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	return &Telemetry{shutdown: shutdown}, nil
}

// Resource is the process identity: the environment's resource
// (OTEL_RESOURCE_ATTRIBUTES), then service.name, service.namespace,
// service.version, service.instance.id "{pod or host}-{pid}" and
// deployment.environment.name over it.
func Resource(ctx context.Context, service, version, environment string) (*resource.Resource, error) {
	detected, err := resource.New(ctx, resource.WithFromEnv(), resource.WithTelemetrySDK(),
		resource.WithAttributes(attribute.String("service.name", service)))
	if err != nil {
		return nil, fmt.Errorf("build otel resource: %w", err)
	}
	attrs := detected.Set()
	pod := ""
	if v, ok := attrs.Value("k8s.pod.name"); ok {
		pod = v.String()
	}
	if pod == "" {
		if pod, err = os.Hostname(); err != nil {
			return nil, fmt.Errorf("resolve service.instance.id: %w", err)
		}
	}
	if v, ok := attrs.Value("service.version"); ok && v.String() != "" {
		version = v.String()
	}
	identity := resource.NewSchemaless(
		attribute.String("service.name", service),
		attribute.String("service.namespace", "agentarea"),
		attribute.String("service.version", version),
		attribute.String("service.instance.id", fmt.Sprintf("%s-%d", pod, os.Getpid())),
		attribute.String("deployment.environment.name", environment),
	)
	merged, err := resource.Merge(detected, identity)
	if err != nil {
		return nil, fmt.Errorf("merge otel resource: %w", err)
	}
	return merged, nil
}

func spanExporter(ctx context.Context, protocol string) (sdktrace.SpanExporter, error) {
	if protocol == "grpc" {
		return otlptracegrpc.New(ctx)
	}
	return otlptracehttp.New(ctx)
}

// metricReader is the OTLP push reader every OTEL_METRIC_EXPORT_INTERVAL,
// the Prometheus pull endpoint (OTEL_EXPORTER_PROMETHEUS_HOST/PORT,
// localhost:9464), or none.
func metricReader(ctx context.Context, cfg Config) (sdkmetric.Reader, error) {
	switch cfg.MetricsExporter {
	case "none":
		return nil, nil
	case "prometheus":
		return autoexport.NewMetricReader(ctx)
	}
	var exporter sdkmetric.Exporter
	var err error
	if cfg.MetricsProtocol == "grpc" {
		exporter, err = otlpmetricgrpc.New(ctx)
	} else {
		exporter, err = otlpmetrichttp.New(ctx)
	}
	if err != nil {
		return nil, err
	}
	return sdkmetric.NewPeriodicReader(exporter, sdkmetric.WithInterval(cfg.ExportInterval)), nil
}

// View keeps each instrument of the table with its attribute keys and
// buckets and drops every other instrument (metric_views' catch-all).
func View(inst sdkmetric.Instrument) (sdkmetric.Stream, bool) {
	for _, p := range kernel.Instruments() {
		if p.Name != inst.Name {
			continue
		}
		keys := make([]attribute.Key, len(p.Attributes))
		for i, k := range p.Attributes {
			keys[i] = attribute.Key(k)
		}
		s := sdkmetric.Stream{Name: inst.Name, Description: inst.Description, Unit: inst.Unit,
			AttributeFilter: attribute.NewAllowKeysFilter(keys...)}
		if p.Buckets != nil {
			s.Aggregation = sdkmetric.AggregationExplicitBucketHistogram{Boundaries: p.Buckets}
		}
		return s, true
	}
	return sdkmetric.Stream{Name: inst.Name, Aggregation: sdkmetric.AggregationDrop{}}, true
}

// RegisterUptime exports agentarea.process.uptime, whose absence tells a
// silent exporter from an idle process.
func RegisterUptime(provider metric.MeterProvider) error {
	started := time.Now()
	_, err := provider.Meter(kernel.MeterScope).Float64ObservableGauge(kernel.ProcessUptime,
		metric.WithUnit("s"),
		metric.WithDescription("Seconds since the process started; the heartbeat of its telemetry."),
		metric.WithFloat64Callback(func(_ context.Context, o metric.Float64Observer) error {
			o.Observe(time.Since(started).Seconds())
			return nil
		}),
	)
	return err
}
