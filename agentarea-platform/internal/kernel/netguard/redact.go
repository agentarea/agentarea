package netguard

import (
	"errors"
	"net/url"
)

// SafeURL is rawURL without userinfo, query or fragment, where a
// member-supplied URL carries its credentials, so a log or an error names
// no secret.
func SafeURL(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return "<unparsable URL>"
	}
	u.User, u.RawQuery, u.ForceQuery, u.Fragment, u.RawFragment = nil, "", false, "", ""
	return u.String()
}

// SafeURLError is err with the URL of the *url.Error in its chain made
// SafeURL: net/http puts the whole request URL into the errors it returns.
func SafeURLError(err error) error {
	var ue *url.Error
	for e := err; errors.As(e, &ue); e = ue.Err {
		ue.URL = SafeURL(ue.URL)
	}
	return err
}
