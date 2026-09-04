package sandboxruntime

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"slices"
	"strings"
)

// DefaultIsolationAttestationPath is where a sandbox template is expected to
// publish its attestation document. The composition root passes the effective
// path explicitly; providers never assume one.
const DefaultIsolationAttestationPath = "/etc/agentarea/isolation-attestation.json"

// DecodeIsolationAttestation parses an attestation document strictly. Unknown
// fields and trailing data are rejected so a truncated or foreign document can
// never be read as a valid attestation.
func DecodeIsolationAttestation(document string) (IsolationAttestation, error) {
	decoder := json.NewDecoder(bytes.NewBufferString(document))
	decoder.DisallowUnknownFields()
	var attestation IsolationAttestation
	if err := decoder.Decode(&attestation); err != nil {
		return IsolationAttestation{}, fmt.Errorf("decode isolation attestation: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return IsolationAttestation{}, fmt.Errorf("decode isolation attestation: trailing data")
	}
	return attestation, nil
}

// ErrIsolationUnavailable is returned when a data plane cannot prove the
// isolation boundary it was configured to provide. Answering an API call is not
// evidence of isolation, so an unproven boundary is always a hard failure.
var ErrIsolationUnavailable = errors.New("isolation_unavailable")

// strongIsolationTypes are the only boundaries accepted for untrusted task
// code. runc, plain containers and "unknown" are deliberately absent: there is
// no fallback tier, a provider that cannot offer one of these is unusable.
var strongIsolationTypes = []string{"firecracker", "gvisor", "kata"}

// IsolationAttestation is the evidence a data plane publishes about itself.
// Every field is mandatory — a partial attestation proves nothing.
type IsolationAttestation struct {
	Provider          string `json:"provider"`
	ProviderVersion   string `json:"provider_version"`
	Isolation         string `json:"isolation"`
	RuntimeIdentity   string `json:"runtime_identity"`
	AttestationSource string `json:"attestation_source"`
}

// IsolationRequirement is the posture the operator declared for this
// deployment. The attestation must match it exactly.
type IsolationRequirement struct {
	Provider        string
	Isolation       string
	RuntimeIdentity string
}

// ValidateIsolationRequirement rejects a deployment that never declared a
// verifiable boundary, before any workload is created.
func ValidateIsolationRequirement(req IsolationRequirement) error {
	if strings.TrimSpace(req.Provider) == "" {
		return fmt.Errorf("%w: no provider was declared", ErrIsolationUnavailable)
	}
	isolation := strings.ToLower(strings.TrimSpace(req.Isolation))
	if isolation == "" {
		return fmt.Errorf("%w: %s did not declare an isolation type", ErrIsolationUnavailable, req.Provider)
	}
	if !slices.Contains(strongIsolationTypes, isolation) {
		return fmt.Errorf(
			"%w: %s isolation=%q is not an accepted boundary; expected one of %s",
			ErrIsolationUnavailable, req.Provider, req.Isolation, strings.Join(strongIsolationTypes, ", "),
		)
	}
	return nil
}

// Verify checks a live attestation against the declared deployment requirement.
// Any missing field or mismatch fails closed.
func (a IsolationAttestation) Verify(req IsolationRequirement) error {
	if err := ValidateIsolationRequirement(req); err != nil {
		return err
	}
	for name, value := range map[string]string{
		"provider":           a.Provider,
		"provider_version":   a.ProviderVersion,
		"isolation":          a.Isolation,
		"runtime_identity":   a.RuntimeIdentity,
		"attestation_source": a.AttestationSource,
	} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("%w: %s attestation is missing %s", ErrIsolationUnavailable, req.Provider, name)
		}
	}
	if !strings.EqualFold(strings.TrimSpace(a.Provider), strings.TrimSpace(req.Provider)) {
		return fmt.Errorf(
			"%w: attestation is from provider %q, expected %q",
			ErrIsolationUnavailable, a.Provider, req.Provider,
		)
	}
	attested := strings.ToLower(strings.TrimSpace(a.Isolation))
	if attested != strings.ToLower(strings.TrimSpace(req.Isolation)) {
		return fmt.Errorf(
			"%w: %s attested isolation=%q but the deployment requires %q",
			ErrIsolationUnavailable, req.Provider, a.Isolation, req.Isolation,
		)
	}
	if !slices.Contains(strongIsolationTypes, attested) {
		return fmt.Errorf(
			"%w: %s attested isolation=%q is not an accepted boundary",
			ErrIsolationUnavailable, req.Provider, a.Isolation,
		)
	}
	if pinned := strings.TrimSpace(req.RuntimeIdentity); pinned != "" && pinned != strings.TrimSpace(a.RuntimeIdentity) {
		return fmt.Errorf(
			"%w: %s attested runtime identity %q does not match the pinned %q",
			ErrIsolationUnavailable, req.Provider, a.RuntimeIdentity, pinned,
		)
	}
	return nil
}
