package handlers

import "errors"

// errUnmounted answers an operation no route reaches.
var errUnmounted = errors.New("catalog: operation not mounted")
