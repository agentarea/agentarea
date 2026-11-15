//go:build archviolation

package service

import (
	_ "go.temporal.io/sdk/client"   // want depguard
	_ "go.temporal.io/sdk/workflow" // want depguard
)
