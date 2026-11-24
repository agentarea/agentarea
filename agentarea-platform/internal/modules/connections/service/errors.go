package service

import "errors"

var (
	errNoGraphWriter = errors.New("connections: the authorization graph cannot be written")
	errNoAgents      = errors.New("connections: no agents port to lend the connection through")
)
