package temporal

import (
	"fmt"

	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/contrib/opentelemetry"
)

// withTracing adds the OpenTelemetry tracing interceptor (observability/temporal.py
// TracingInterceptor) to the client and the workers built from it: a span per workflow and
// activity start and run, carried across Temporal in headers. It traces through the global
// provider, a no-op unless telemetry is on.
func withTracing(opts *client.Options) error {
	t, err := opentelemetry.NewTracingInterceptor(opentelemetry.TracerOptions{})
	if err != nil {
		return fmt.Errorf("temporal tracing: %w", err)
	}
	opts.Interceptors = append(opts.Interceptors, t)
	return nil
}
