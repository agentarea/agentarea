package handlers

import "net/http"

func (x response) VisitUploadTaskFileV1RunnerTasksTaskIdFilesFilePathPutResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRunnerWhoamiV1RunnerWhoamiGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListAgentTasksV1AgentsAgentIdTasksGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateTaskForAgentWithStreamV1AgentsAgentIdTasksPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitScheduleTaskForAgentV1AgentsAgentIdTasksSchedulePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCreateTaskForAgentSyncV1AgentsAgentIdTasksSyncPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitCancelAgentTaskV1AgentsAgentIdTasksTaskIdDeleteResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetAgentTaskV1AgentsAgentIdTasksTaskIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSendA2uiActionV1AgentsAgentIdTasksTaskIdA2uiActionPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListTaskArtifactsV1AgentsAgentIdTasksTaskIdArtifactsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDownloadTaskArtifactV1AgentsAgentIdTasksTaskIdArtifactsFilesArtifactPathGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSendTaskCommandV1AgentsAgentIdTasksTaskIdCommandPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListPendingEscalationsV1AgentsAgentIdTasksTaskIdEscalationsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetTaskEventsV1AgentsAgentIdTasksTaskIdEventsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitStreamTaskEventsV1AgentsAgentIdTasksTaskIdEventsStreamGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitSubmitTaskInputV1AgentsAgentIdTasksTaskIdInputPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitPauseAgentTaskV1AgentsAgentIdTasksTaskIdPausePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitResolveTaskEscalationV1AgentsAgentIdTasksTaskIdResolveEscalationPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitResumeAgentTaskV1AgentsAgentIdTasksTaskIdResumePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitRetryAgentTaskV1AgentsAgentIdTasksTaskIdRetryPostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListTaskSandboxFilesV1AgentsAgentIdTasksTaskIdSandboxFilesGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitReadTaskSandboxFileV1AgentsAgentIdTasksTaskIdSandboxFilesFilePathGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetAgentTaskStatusV1AgentsAgentIdTasksTaskIdStatusGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetTaskSummaryV1AgentsAgentIdTasksTaskIdSummaryGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetInboxItemsV1InboxGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListApprovalDecisionsV1InboxDecisionsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetAllTasksV1TasksGetResponse(w http.ResponseWriter) error { return x.visit(w) }
func (x response) VisitGetTaskByIdV1TasksTaskIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitContinueTaskExecutionV1TasksTaskIdContinuePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitListToolCallApprovalsV1ToolCallApprovalsGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitGetToolCallApprovalV1ToolCallApprovalsApprovalIdGetResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
func (x response) VisitDecideToolCallApprovalV1ToolCallApprovalsApprovalIdDecidePostResponse(w http.ResponseWriter) error {
	return x.visit(w)
}
