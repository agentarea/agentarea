// Package cluster is the adapter set of a cluster deployment: Postgres
// (pgx), Redis Streams, Temporal, OpenFGA, S3, Kubernetes. Each adapter
// implements a kernel port; app builds them once per process.
package cluster
