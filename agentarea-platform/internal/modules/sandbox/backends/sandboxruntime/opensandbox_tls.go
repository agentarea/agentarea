package sandboxruntime

import (
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net/http"
)

const (
	nistMinRSABits  = 2048
	nistMinECBits   = 224
	nistMinHashBits = 224
)

// withNISTPeerMinimums is transport with the OpenSandbox SDK's server
// certificate floor: key length and signature hash strength, checked on the
// verified chains.
func withNISTPeerMinimums(transport http.RoundTripper) (*http.Transport, error) {
	base, ok := transport.(*http.Transport)
	if !ok {
		return nil, fmt.Errorf("sandbox provider opensandbox needs an *http.Transport, got %T", transport)
	}
	t := base.Clone()
	if t.TLSClientConfig == nil {
		t.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	}
	t.TLSClientConfig.VerifyConnection = enforceNISTPeerCertificateMinimums
	return t, nil
}

func enforceNISTPeerCertificateMinimums(cs tls.ConnectionState) error {
	if len(cs.VerifiedChains) == 0 {
		return errors.New("server did not present a verified certificate chain")
	}
	for i, chain := range cs.VerifiedChains {
		for j, cert := range chain {
			if err := ensureCertPublicKeyMeetsNISTMinimums(cert); err != nil {
				return fmt.Errorf("verified chain[%d] certificate[%d]: %w", i, j, err)
			}
			if len(chain) > 1 && j == len(chain)-1 {
				continue
			}
			if err := ensureCertSignatureHashMeetsNISTMinimums(cert); err != nil {
				return fmt.Errorf("verified chain[%d] certificate[%d]: %w", i, j, err)
			}
		}
	}
	return nil
}

func ensureCertPublicKeyMeetsNISTMinimums(cert *x509.Certificate) error {
	if cert == nil {
		return errors.New("certificate is nil")
	}
	switch pub := cert.PublicKey.(type) {
	case *rsa.PublicKey:
		if pub.N == nil {
			return errors.New("certificate RSA public key modulus is nil")
		}
		if bits := pub.N.BitLen(); bits < nistMinRSABits {
			return fmt.Errorf("certificate RSA key length %d bits is below NIST minimum %d bits", bits, nistMinRSABits)
		}
	case *ecdsa.PublicKey:
		if pub.Curve == nil {
			return errors.New("certificate EC public key curve is nil")
		}
		if bits := pub.Curve.Params().BitSize; bits < nistMinECBits {
			return fmt.Errorf("certificate EC key length %d bits is below NIST minimum %d bits", bits, nistMinECBits)
		}
	case ed25519.PublicKey:
		if bits := len(pub) * 8; bits < nistMinECBits {
			return fmt.Errorf("certificate Ed25519 key length %d bits is below NIST minimum %d bits", bits, nistMinECBits)
		}
	default:
		return fmt.Errorf("unsupported certificate public key type %T", cert.PublicKey)
	}
	return nil
}

func ensureCertSignatureHashMeetsNISTMinimums(cert *x509.Certificate) error {
	bits, err := minHashBitsForSignatureAlgorithm(cert.SignatureAlgorithm)
	if err != nil {
		return err
	}
	if bits < nistMinHashBits {
		return fmt.Errorf("certificate hash strength %d bits is below NIST minimum %d bits (signature algorithm: %s)", bits, nistMinHashBits, cert.SignatureAlgorithm)
	}
	return nil
}

func minHashBitsForSignatureAlgorithm(algo x509.SignatureAlgorithm) (int, error) {
	switch algo {
	case x509.MD2WithRSA, x509.MD5WithRSA:
		return 128, nil
	case x509.SHA1WithRSA, x509.ECDSAWithSHA1:
		return 160, nil
	case x509.SHA256WithRSA, x509.ECDSAWithSHA256, x509.SHA256WithRSAPSS, x509.PureEd25519:
		return 256, nil
	case x509.SHA384WithRSA, x509.ECDSAWithSHA384, x509.SHA384WithRSAPSS:
		return 384, nil
	case x509.SHA512WithRSA, x509.ECDSAWithSHA512, x509.SHA512WithRSAPSS:
		return 512, nil
	case x509.UnknownSignatureAlgorithm, x509.DSAWithSHA1, x509.DSAWithSHA256, x509.MLDSA44, x509.MLDSA65, x509.MLDSA87:
		return 0, fmt.Errorf("unknown certificate signature algorithm: %s", algo)
	default:
		return 0, fmt.Errorf("unknown certificate signature algorithm: %s", algo)
	}
}
