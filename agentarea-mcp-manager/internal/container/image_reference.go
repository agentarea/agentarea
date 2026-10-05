package container

import (
	"fmt"
	"regexp"
)

// imageReferencePattern is the OCI distribution reference grammar
// ([domain[:port]/]path[:tag][@digest]), anchored. The image is caller input
// that lands in `docker run` argv in the image position; anything this
// grammar does not accept -- above all a leading '-' -- would be parsed by the
// runtime as a flag (`--volume=/var/run/docker.sock:...`, `--privileged`).
var imageReferencePattern = regexp.MustCompile(
	`^` +
		// optional registry host, with optional port
		`(?:(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])(?:\.(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]))*(?::[0-9]+)?/)?` +
		// one or more lowercase path components
		`[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*` +
		// optional tag
		`(?::[\w][\w.-]{0,127})?` +
		// optional digest
		`(?:@[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,})?` +
		`$`,
)

// maxImageReferenceLength mirrors the distribution reference limit.
const maxImageReferenceLength = 255

// ValidateImageReference refuses anything that is not a plain image
// reference. It must run before an image reaches a runtime command line.
func ValidateImageReference(image string) error {
	if image == "" {
		return fmt.Errorf("image must be a non-empty string")
	}
	if len(image) > maxImageReferenceLength {
		return fmt.Errorf("image reference is longer than %d characters", maxImageReferenceLength)
	}
	if !imageReferencePattern.MatchString(image) {
		return fmt.Errorf("image %q is not a valid image reference", image)
	}
	return nil
}
