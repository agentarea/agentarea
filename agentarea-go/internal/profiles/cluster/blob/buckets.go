package blob

import (
	"context"
	"errors"
	"fmt"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"
)

// InitBuckets creates each bucket (already existing is fine) and gives it the
// browser CORS allowlist, as agentarea_common.artifacts.bucket_init does:
// browsers upload straight to the store with presigned URLs, so each bucket
// needs a rule naming the app origins. A "*" origin is refused.
func (c *Client) InitBuckets(ctx context.Context, buckets, corsOrigins []string) error {
	for _, o := range corsOrigins {
		if o == "*" {
			return errors.New("storage CORS needs explicit origins, not '*'")
		}
	}
	for _, b := range buckets {
		if _, err := c.internal.CreateBucket(ctx, &s3.CreateBucketInput{Bucket: &b}); err != nil {
			var api smithy.APIError
			if !errors.As(err, &api) || (api.ErrorCode() != "BucketAlreadyOwnedByYou" && api.ErrorCode() != "BucketAlreadyExists") {
				return fmt.Errorf("create bucket %s: %w", b, err)
			}
		}
		if len(corsOrigins) == 0 {
			continue
		}
		maxAge := int32(3600)
		_, err := c.internal.PutBucketCors(ctx, &s3.PutBucketCorsInput{
			Bucket: &b,
			CORSConfiguration: &types.CORSConfiguration{CORSRules: []types.CORSRule{{
				AllowedOrigins: corsOrigins,
				AllowedMethods: []string{"GET", "PUT", "HEAD"},
				AllowedHeaders: []string{"*"},
				ExposeHeaders:  []string{"ETag"},
				MaxAgeSeconds:  &maxAge,
			}}},
		})
		if err != nil {
			return fmt.Errorf("set CORS on bucket %s: %w", b, err)
		}
	}
	return nil
}
