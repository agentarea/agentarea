package handlers

import (
	"context"
	"net/http"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/catalog"
)

func (x response) VisitAnalyzeBundleV1BundlesAnalyzePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitInstallBundleV1BundlesInstallPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListMcpServersV1McpServersGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateMcpServerV1McpServersPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteMcpServerV1McpServersServerIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetMcpServerV1McpServersServerIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateMcpServerV1McpServersServerIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeployMcpServerV1McpServersServerIdDeployPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListModelSpecsV1ModelSpecsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateModelSpecV1ModelSpecsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpsertModelSpecV1ModelSpecsUpsertPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteModelSpecV1ModelSpecsModelSpecIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetModelSpecV1ModelSpecsModelSpecIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateModelSpecV1ModelSpecsModelSpecIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListProviderSpecsV1ProviderSpecsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetProviderSpecV1ProviderSpecsProviderSpecIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListRegistriesV1RegistriesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateRegistryV1RegistriesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitBrowseCatalogV1RegistriesCatalogBrowseGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteCatalogItemV1RegistriesCatalogItemsItemIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetCatalogItemV1RegistriesCatalogItemsItemIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateCatalogItemV1RegistriesCatalogItemsItemIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSearchCatalogV1RegistriesCatalogSearchGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteRegistryV1RegistriesRegistryIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetRegistryV1RegistriesRegistryIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateRegistryV1RegistriesRegistryIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListRegistryItemsV1RegistriesRegistryIdItemsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateCatalogItemV1RegistriesRegistryIdItemsPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSyncRegistryV1RegistriesRegistryIdSyncPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListWorkspaceRegistriesV1WorkspaceRegistriesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateWorkspaceRegistryV1WorkspaceRegistriesPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDeleteWorkspaceRegistryV1WorkspaceRegistriesRegistryIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetWorkspaceRegistryV1WorkspaceRegistriesRegistryIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitUpdateWorkspaceRegistryV1WorkspaceRegistriesRegistryIdPatchResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSyncWorkspaceRegistryV1WorkspaceRegistriesRegistryIdSyncPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}

func (*Server) AnalyzeBundleV1BundlesAnalyzePost(context.Context, gen.AnalyzeBundleV1BundlesAnalyzePostRequestObject) (gen.AnalyzeBundleV1BundlesAnalyzePostResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) InstallBundleV1BundlesInstallPost(context.Context, gen.InstallBundleV1BundlesInstallPostRequestObject) (gen.InstallBundleV1BundlesInstallPostResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) ListMcpServersV1McpServersGet(context.Context, gen.ListMcpServersV1McpServersGetRequestObject) (gen.ListMcpServersV1McpServersGetResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) CreateMcpServerV1McpServersPost(context.Context, gen.CreateMcpServerV1McpServersPostRequestObject) (gen.CreateMcpServerV1McpServersPostResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) DeleteMcpServerV1McpServersServerIdDelete(context.Context, gen.DeleteMcpServerV1McpServersServerIdDeleteRequestObject) (gen.DeleteMcpServerV1McpServersServerIdDeleteResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) GetMcpServerV1McpServersServerIdGet(context.Context, gen.GetMcpServerV1McpServersServerIdGetRequestObject) (gen.GetMcpServerV1McpServersServerIdGetResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) UpdateMcpServerV1McpServersServerIdPatch(context.Context, gen.UpdateMcpServerV1McpServersServerIdPatchRequestObject) (gen.UpdateMcpServerV1McpServersServerIdPatchResponseObject, error) {
	return nil, errUnmounted
}

func (*Server) DeployMcpServerV1McpServersServerIdDeployPost(context.Context, gen.DeployMcpServerV1McpServersServerIdDeployPostRequestObject) (gen.DeployMcpServerV1McpServersServerIdDeployPostResponseObject, error) {
	return nil, errUnmounted
}
