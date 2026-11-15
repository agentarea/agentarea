package workflows

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

func TestAnswerCheckRewritesALeakingReplyOnce(t *testing.T) {
	f := newFakeRun()
	f.cfg.Agent.AnswerCheck = &api.AnswerCheck{Enabled: true, Language: "ru"}
	f.llm[parentTask] = turns(text("Готово: статус task_not_found"))
	var seen LLMCallRequest
	f.llm[""] = func(req LLMCallRequest, _ int32) (LLMCallResult, error) {
		seen = req
		return text("<changes>убрал код</changes>\n<answer>\nГотово: задача не найдена\n</answer>"), nil
	}
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))

	res := result(t, env)
	if res.FinalResponse != "Готово: задача не найдена" {
		t.Fatalf("final response = %q", res.FinalResponse)
	}
	if seen.Purpose != "answer_check" || seen.Temperature == nil || *seen.Temperature != 0 || seen.MaxTokens == nil || *seen.MaxTokens != 4000 || len(seen.Tools) != 0 {
		t.Fatalf("rewrite call = %+v", seen)
	}
	contains(t, f.events(parentTask), domain.EventLLMCompleted, domain.EventAnswerChecked, domain.EventLLMCompleted, domain.EventTaskCompleted)
	checked := f.eventData(parentTask, domain.EventAnswerChecked)
	if len(checked) != 1 || checked[0]["rewritten"] != true || checked[0]["changes"] != "убрал код" {
		t.Fatalf("answer.checked = %+v", checked)
	}
	completed := f.eventData(parentTask, domain.EventLLMCompleted)
	if completed[0]["purpose"] != "answer_check" || completed[1]["content"] != "Готово: задача не найдена" {
		t.Fatalf("llm.call.completed = %+v", completed)
	}
	if f.llmCalls[""] != 1 {
		t.Fatalf("rewrite calls = %d, want 1", f.llmCalls[""])
	}
	if res.TotalCost.String() != "0.02" {
		t.Fatalf("total cost = %s, want both calls metered", res.TotalCost)
	}
}

func TestAnswerCheckKeepsACleanReplyWithoutACall(t *testing.T) {
	f := newFakeRun()
	f.cfg.Agent.AnswerCheck = &api.AnswerCheck{Enabled: true, Language: "ru"}
	f.llm[parentTask] = turns(text("Готово, всё сделано."))
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	if res := result(t, env); res.FinalResponse != "Готово, всё сделано." || f.llmCalls[""] != 0 {
		t.Fatalf("result = %+v, rewrite calls %d", res, f.llmCalls[""])
	}
	if len(f.eventData(parentTask, domain.EventAnswerChecked)) != 0 {
		t.Fatal("a clean answer records no check")
	}
}

func TestAnswerCheckFailedRewriteStripsCJK(t *testing.T) {
	f := newFakeRun()
	f.cfg.Agent.AnswerCheck = &api.AnswerCheck{Enabled: true}
	f.llm[parentTask] = turns(calls(complete("c1", "Done 你好 now")))
	f.llm[""] = func(LLMCallRequest, int32) (LLMCallResult, error) { return text("no blocks at all"), nil }
	env := newEnv(t, f)
	env.ExecuteWorkflow(AgentExecutionWorkflow, request(nil))
	if res := result(t, env); res.FinalResponse != "Done now" {
		t.Fatalf("final response = %q", res.FinalResponse)
	}
	checked := f.eventData(parentTask, domain.EventAnswerChecked)
	if len(checked) != 1 || checked[0]["rewritten"] != false || checked[0]["changes"] != nil {
		t.Fatalf("answer.checked = %+v", checked)
	}
}
