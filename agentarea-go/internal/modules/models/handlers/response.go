package handlers

import (
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// response is a route's answer as Python renders it: a JSON body, or raw bytes with headers.
type response struct {
	status  int
	body    any
	raw     []byte
	headers map[string]string
}

func (x response) visit(w http.ResponseWriter) error {
	for k, v := range x.headers {
		w.Header().Set(k, v)
	}
	if x.raw != nil {
		w.WriteHeader(x.status)
		_, err := w.Write(x.raw)
		return err
	}
	raw, err := wirejson.Marshal(x.body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(x.status)
	_, err = w.Write(raw)
	return err
}

func (x response) VisitCreateModelInstancesBulkV1ModelInstancesBulkPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitCreateModelInstanceV1ModelInstancesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitCreateProviderConfigV1ProviderConfigsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitDeleteModelInstanceV1ModelInstancesInstanceIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitDeleteProviderConfigV1ProviderConfigsConfigIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitDiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitDiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetModelInstanceV1ModelInstancesInstanceIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetPricingCurrencyV1PricingCurrencyGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetProviderConfigV1ProviderConfigsConfigIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitGetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitListModelInstancesV1ModelInstancesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitListProviderConfigsV1ProviderConfigsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitPatchProviderConfigV1ProviderConfigsConfigIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitUpdateProviderConfigV1ProviderConfigsConfigIdPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (x response) VisitValidateModelInstanceV1ModelInstancesTestPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
