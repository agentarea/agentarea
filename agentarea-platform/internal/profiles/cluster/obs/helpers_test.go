package obs

import (
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
)

func metricWith(kv ...attribute.KeyValue) metric.RecordOption { return metric.WithAttributes(kv...) }
