package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The reservation is an internal inspection route: it needs the manager bearer
// like every other /instances route.
func TestReservationRouteRequiresManagerBearer(t *testing.T) {
	router := disclosureRouter(t)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/instances/reservation", nil))
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("unauthenticated status = %d, want 401; body=%s", response.Code, response.Body.String())
	}
}

// The reservation route is not read as an instance id, and a backend that cannot
// report a reservation says so instead of answering with a guess.
func TestReservationRouteReportsABackendThatCannotSay(t *testing.T) {
	router := disclosureRouter(t)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, managerInspectionRequest(http.MethodGet, "/instances/reservation"))
	if response.Code != http.StatusNotImplemented {
		t.Fatalf("status = %d, want 501; body=%s", response.Code, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), "reservation_unavailable") {
		t.Fatalf("body = %s, want reservation_unavailable", response.Body.String())
	}
}
