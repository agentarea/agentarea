package workload

import (
	"fmt"
	"regexp"
)

// imageReferenceRE is the OCI reference grammar ([domain[:port]/]path[:tag][@digest]),
// anchored. The image lands in a runtime argv in the image position, so
// anything else, above all a leading '-', would be read as a flag.
var imageReferenceRE = regexp.MustCompile(`^` +
	`(?:(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])(?:\.(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]))*(?::[0-9]+)?/)?` +
	`[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*` +
	`(?::[\w][\w.-]{0,127})?` +
	`(?:@[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,})?` +
	`$`)

const maxImageReferenceLength = 255

// ValidateImageReference refuses anything that is not a plain image reference.
func ValidateImageReference(image string) error {
	if image == "" {
		return fmt.Errorf("image must be a non-empty string")
	}
	if len(image) > maxImageReferenceLength {
		return fmt.Errorf("image reference is longer than %d characters", maxImageReferenceLength)
	}
	if !imageReferenceRE.MatchString(image) {
		return fmt.Errorf("image %q is not a valid image reference", image)
	}
	return nil
}
