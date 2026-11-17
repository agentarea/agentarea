package httpx

// statusPhrase is Python's http.HTTPStatus phrase table (3.14), the title
// problem_dict falls back to; it differs from net/http's StatusText (422
// "Unprocessable Content", 413 "Content Too Large", 418 "I'm a Teapot").
// TestStatusPhrasesMatchPython compares it with the captured table.
func statusPhrase(code int) (string, bool) {
	switch code {
	case 100:
		return "Continue", true
	case 101:
		return "Switching Protocols", true
	case 102:
		return "Processing", true
	case 103:
		return "Early Hints", true
	case 200:
		return "OK", true
	case 201:
		return "Created", true
	case 202:
		return "Accepted", true
	case 203:
		return "Non-Authoritative Information", true
	case 204:
		return "No Content", true
	case 205:
		return "Reset Content", true
	case 206:
		return "Partial Content", true
	case 207:
		return "Multi-Status", true
	case 208:
		return "Already Reported", true
	case 226:
		return "IM Used", true
	case 300:
		return "Multiple Choices", true
	case 301:
		return "Moved Permanently", true
	case 302:
		return "Found", true
	case 303:
		return "See Other", true
	case 304:
		return "Not Modified", true
	case 305:
		return "Use Proxy", true
	case 307:
		return "Temporary Redirect", true
	case 308:
		return "Permanent Redirect", true
	case 400:
		return "Bad Request", true
	case 401:
		return "Unauthorized", true
	case 402:
		return "Payment Required", true
	case 403:
		return "Forbidden", true
	case 404:
		return "Not Found", true
	case 405:
		return "Method Not Allowed", true
	case 406:
		return "Not Acceptable", true
	case 407:
		return "Proxy Authentication Required", true
	case 408:
		return "Request Timeout", true
	case 409:
		return "Conflict", true
	case 410:
		return "Gone", true
	case 411:
		return "Length Required", true
	case 412:
		return "Precondition Failed", true
	case 413:
		return "Content Too Large", true
	case 414:
		return "URI Too Long", true
	case 415:
		return "Unsupported Media Type", true
	case 416:
		return "Range Not Satisfiable", true
	case 417:
		return "Expectation Failed", true
	case 418:
		return "I'm a Teapot", true
	case 421:
		return "Misdirected Request", true
	case 422:
		return "Unprocessable Content", true
	case 423:
		return "Locked", true
	case 424:
		return "Failed Dependency", true
	case 425:
		return "Too Early", true
	case 426:
		return "Upgrade Required", true
	case 428:
		return "Precondition Required", true
	case 429:
		return "Too Many Requests", true
	case 431:
		return "Request Header Fields Too Large", true
	case 451:
		return "Unavailable For Legal Reasons", true
	case 500:
		return "Internal Server Error", true
	case 501:
		return "Not Implemented", true
	case 502:
		return "Bad Gateway", true
	case 503:
		return "Service Unavailable", true
	case 504:
		return "Gateway Timeout", true
	case 505:
		return "HTTP Version Not Supported", true
	case 506:
		return "Variant Also Negotiates", true
	case 507:
		return "Insufficient Storage", true
	case 508:
		return "Loop Detected", true
	case 510:
		return "Not Extended", true
	case 511:
		return "Network Authentication Required", true
	}
	return "", false
}
