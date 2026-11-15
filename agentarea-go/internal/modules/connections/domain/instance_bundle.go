package domain

import (
	"strings"
	"time"
)

// BundleMembers is a bundle's json_spec.members.
func BundleMembers(bundle Instance) []string { return StringList(bundle.JSONSpec["members"]) }

// DeriveBundleVerification is derive_bundle_verification: a bundle is as
// verified as its members, read now; members holds those found.
func DeriveBundleVerification(bundle Instance, members map[string]Instance, now time.Time) Verification {
	at := now.UTC().Format("2006-01-02T15:04:05.000000+00:00")
	failed := func(code, msg string) Verification {
		return Verification{SchemaVersion: VerificationSchema, Status: VerifyFailed, At: &at,
			Error: &VerificationError{Code: code, Message: msg}}
	}
	ids := BundleMembers(bundle)
	if len(ids) == 0 {
		return failed("bundle_empty", "Bundle has no members.")
	}
	var missing, notReady []string
	for _, id := range ids {
		m, ok := members[id]
		if !ok {
			missing = append(missing, id)
			continue
		}
		if m.Verification.Status != VerifySucceeded {
			notReady = append(notReady, m.Name)
		}
	}
	if len(missing) > 0 {
		return failed("bundle_member_missing", "Bundle member(s) not found: ["+strings.Join(missing, ", ")+"]. They may have been deleted.")
	}
	if len(notReady) > 0 {
		return failed("bundle_member_not_ready", "Bundle members not ready: ["+strings.Join(notReady, ", ")+"].")
	}
	return Verification{SchemaVersion: VerificationSchema, Status: VerifySucceeded, At: &at}
}
