package domain

// Email is one message of the platform's own transactional mail (infrastructure/email.py EmailMessage).
type Email struct {
	To       string
	Subject  string
	TextBody string
	// HTMLBody empty sends the text alone.
	HTMLBody string
}
