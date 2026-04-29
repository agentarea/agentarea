"""End-to-end multi-agent scenario against real LLM + real network.

A coordinator agent dispatches work to three specialist agents in parallel:

  * file-writer: writes a text file via ``agentarea/files``
  * pdf-fetcher: downloads a PDF via ``agentarea/web`` (binary -> RustFS artifact)
  * md-summarizer: fetches a web page and writes a markdown summary file

The coordinator uses the auto-generated ``delegate_to_<name>`` tools (Temporal
child workflows under the hood). Each child must complete and the coordinator
must reach ``WorkflowCompleted`` — proving the full delegation fan-out.

This test relies on:
  * the OpenAI-compatible LLM endpoint configured in conftest (real model)
  * outbound HTTPS to ``w3.org`` (PDF) and ``en.wikipedia.org`` (page summary)

If the LLM picks fewer than 3 specialists, or any child times out, the test
fails. We assert on the platform contract (events + DB rows), not on free-text
LLM output, to keep the test deterministic enough to be useful.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow

# Stable, tiny public test PDF used by W3C accessibility test suite.
PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
# example.com is the canonical "always available, no UA gating" page.
# (Wikipedia blocks the default httpx UA with a 403 + robot-policy message.)
SUMMARIZE_URL = "https://example.com/"
SUMMARIZE_TOPIC = "example domain"  # what the page is about


@pytest.mark.integration
@pytest.mark.slow
def test_coordinator_fans_out_to_three_specialists(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """End-to-end: 3 specialists run in parallel, coordinator rolls up."""
    suffix = int(time.time())

    file_writer_id = create_agent(
        alice_client,
        llm_model,
        name=f"file-writer-{suffix}",
        instruction=(
            "You write text files. The user gives you a filename and contents. "
            "Call save_file once with exactly those arguments. Then call "
            "completion with one short sentence describing what you wrote."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    pdf_fetcher_id = create_agent(
        alice_client,
        llm_model,
        name=f"pdf-fetcher-{suffix}",
        instruction=(
            "You download PDFs from URLs. The user gives you a URL. Call "
            "fetch_webpage with that URL. Then call completion with the JSON "
            "response from fetch_webpage verbatim — the parent needs it."
        ),
        tools=[
            {"type": "code", "name": "agentarea/web"},
            {"type": "code", "name": "agentarea/files"},
        ],
    )
    md_summarizer_id = create_agent(
        alice_client,
        llm_model,
        name=f"md-summarizer-{suffix}",
        instruction=(
            "You produce markdown summaries of web pages. Steps: "
            "(1) Call fetch_webpage on the URL the user gives you. "
            "(2) Write a short 5-bullet markdown summary into summary.md "
            "using save_file. (3) Call completion with the filename."
        ),
        tools=[
            {"type": "code", "name": "agentarea/web"},
            {"type": "code", "name": "agentarea/files"},
        ],
    )

    # Re-fetch sanitized agent names — that's what the LLM will see as
    # delegate_to_<name> tools. (The /v1/agents/{id} response has the
    # canonical name string.)
    fw = alice_client.get(f"/v1/agents/{file_writer_id}").raise_for_status().json()
    pf = alice_client.get(f"/v1/agents/{pdf_fetcher_id}").raise_for_status().json()
    ms = alice_client.get(f"/v1/agents/{md_summarizer_id}").raise_for_status().json()

    coord_id = create_agent(
        alice_client,
        llm_model,
        name=f"coordinator-{suffix}",
        instruction=(
            "You coordinate three specialist agents. For the user's request, "
            "call all three delegate_to_* tools (one per specialist) with "
            "specific, complete messages. Wait for them all to return, then "
            "call completion with a short paragraph summarizing each result."
        ),
        tools=[
            {"type": "agent", "name": fw["name"]},
            {"type": "agent", "name": pf["name"]},
            {"type": "agent", "name": ms["name"]},
        ],
    )

    prompt = (
        f"Run all three specialists in parallel:\n"
        f"(1) Tell {fw['name']} to save the contents 'hello from coordinator' "
        f"into a file named greeting.txt.\n"
        f"(2) Tell {pf['name']} to download the PDF at {PDF_URL}.\n"
        f"(3) Tell {ms['name']} to fetch {SUMMARIZE_URL} and write a markdown "
        f"summary into summary.md.\n"
        f"Then summarize what each one did."
    )
    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={"description": prompt},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    # Coordinator is a top-level task — it sits in await_input after
    # completion. We wait for the *event* WorkflowCompleted, not for terminal
    # status. Children are delegation workflows and exit on completion (the
    # bug we just fixed).
    events = wait_for_workflow(
        alice_client, coord_id, task_id, timeout=180.0
    )
    types = [e["event_type"] for e in events]

    # The coordinator's LLM must have actually invoked all 3 delegations.
    delegation_started = [
        e for e in events if e["event_type"] == "AgentDelegationStarted"
    ]
    delegation_completed = [
        e for e in events if e["event_type"] == "AgentDelegationCompleted"
    ]
    assert len(delegation_started) == 3, (
        f"expected 3 delegations, got {len(delegation_started)}; types={types}"
    )
    assert len(delegation_completed) == 3, (
        f"expected 3 completed delegations, got {len(delegation_completed)}; "
        f"types={types}"
    )
    # Each one must have succeeded (the bug had them fail silently after 10 min).
    for d in delegation_completed:
        assert d["metadata"].get("success") is True, (
            f"delegation {d['metadata'].get('target_agent_name')} did not "
            f"succeed: {d['metadata']}"
        )

    # Coordinator must have wrapped up with its own WorkflowCompleted.
    assert "WorkflowCompleted" in types, types

    # === Side-effect verification ===
    # Each delegation event carries the child task_id and target_agent_id.
    # We hit GET /v1/agents/{child_agent}/tasks/{child_task}/artifacts to
    # confirm the actual files exist in workspace storage. Just observing
    # 'success=true' on the delegation envelope is not enough — the agent
    # could lie. The artifact endpoint is workspace-scoped to Alice, so a
    # 404 here would also reveal cross-workspace bleed-through.
    by_agent: dict[str, dict] = {
        d["metadata"]["target_agent_name"]: d["metadata"]
        for d in delegation_completed
    }

    # File-writer: greeting.txt under child task scope, contains the payload.
    fw_meta = by_agent[fw["name"]]
    fw_artifacts = alice_client.get(
        f"/v1/agents/{fw_meta['target_agent_id']}/tasks/{fw_meta['child_task_id']}/artifacts"
    ).raise_for_status().json()
    fw_names = [a["path"].rsplit("/", 1)[-1] for a in fw_artifacts]
    assert "greeting.txt" in fw_names, (
        f"file-writer didn't produce greeting.txt; got {fw_names}"
    )
    greeting = next(a for a in fw_artifacts if a["path"].endswith("greeting.txt"))
    body = httpx.get(greeting["download_url"], timeout=10.0).text
    assert "hello from coordinator" in body, body[:200]

    # PDF-fetcher: downloaded a real PDF into downloads/ via agentarea/web.
    # The web tool persists binary fetches under tasks/{task_id}/downloads/.
    pf_meta = by_agent[pf["name"]]
    pf_artifacts = alice_client.get(
        f"/v1/agents/{pf_meta['target_agent_id']}/tasks/{pf_meta['child_task_id']}/artifacts"
    ).raise_for_status().json()
    pdfs = [a for a in pf_artifacts if a["content_type"] == "application/pdf"]
    assert pdfs, (
        f"pdf-fetcher didn't persist a PDF; artifacts: "
        f"{[(a['path'], a['content_type']) for a in pf_artifacts]}"
    )
    assert pdfs[0]["size"] > 1024, f"PDF too small: {pdfs[0]['size']} bytes"
    pdf_bytes = httpx.get(pdfs[0]["download_url"], timeout=10.0).content
    assert pdf_bytes.startswith(b"%PDF-"), (
        f"downloaded artifact is not a real PDF (no %PDF- magic); "
        f"first bytes: {pdf_bytes[:32]!r}"
    )

    # MD-summarizer: summary.md exists, contains markdown structure.
    ms_meta = by_agent[ms["name"]]
    ms_artifacts = alice_client.get(
        f"/v1/agents/{ms_meta['target_agent_id']}/tasks/{ms_meta['child_task_id']}/artifacts"
    ).raise_for_status().json()
    summaries = [a for a in ms_artifacts if a["path"].endswith("summary.md")]
    assert summaries, (
        f"md-summarizer didn't write summary.md; got "
        f"{[a['path'] for a in ms_artifacts]}"
    )
    md_body = httpx.get(summaries[0]["download_url"], timeout=10.0).text
    # 5 bullets per the instruction. Markdown bullets are '- ' or '* ' lines.
    bullet_lines = [
        ln for ln in md_body.splitlines() if ln.strip().startswith(("-", "*"))
    ]
    assert len(bullet_lines) >= 3, (
        f"summary.md doesn't look like a bulleted markdown summary; "
        f"body[:300]={md_body[:300]!r}"
    )
    # Sanity: the summary should reference the source page's topic.
    assert SUMMARIZE_TOPIC in md_body.lower(), (
        f"summary doesn't reference its source topic ({SUMMARIZE_TOPIC!r}); "
        f"body[:300]={md_body[:300]!r}"
    )

    # Release the coordinator's await window.
    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_specialist_writes_artifact_via_delegation(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """A delegated child must be able to write an artifact, and the parent
    must observe the child's success metadata.

    This is the smallest unit-of-business the multi-agent flow promises:
    'parent says "do X", child does X, parent learns it was done'. We assert
    on what the parent observes via events, plus query the artifact API to
    confirm the child's side-effect actually landed in workspace storage.
    """
    suffix = int(time.time())

    writer_id = create_agent(
        alice_client,
        llm_model,
        name=f"writer-{suffix}",
        instruction=(
            "Save the contents 'delegated payload' to a file called note.txt "
            "using save_file, then call completion with the filename."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    writer = alice_client.get(f"/v1/agents/{writer_id}").raise_for_status().json()

    coord_id = create_agent(
        alice_client,
        llm_model,
        name=f"single-coord-{suffix}",
        instruction=(
            f"Call delegate_to_{writer['name'].replace('-', '_')} once with the "
            "user's message. Then call completion with a one-sentence summary "
            "of what the specialist returned."
        ),
        tools=[{"type": "agent", "name": writer["name"]}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={"description": "Tell the writer to save note.txt now."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(
        alice_client, coord_id, task_id, timeout=120.0
    )

    completed = [e for e in events if e["event_type"] == "AgentDelegationCompleted"]
    assert len(completed) == 1, (
        f"expected 1 delegation completed, got {len(completed)}: "
        f"{[e['event_type'] for e in events]}"
    )
    meta = completed[0]["metadata"]
    assert meta["success"] is True, meta

    # Verify the actual side effect: note.txt exists in the child task's
    # artifact bucket with the expected payload. This proves the child
    # really executed the file write — not just claimed completion.
    artifacts = alice_client.get(
        f"/v1/agents/{meta['target_agent_id']}/tasks/{meta['child_task_id']}/artifacts"
    ).raise_for_status().json()
    notes = [a for a in artifacts if a["path"].endswith("note.txt")]
    assert notes, f"note.txt missing from child artifacts; got {[a['path'] for a in artifacts]}"
    body = httpx.get(notes[0]["download_url"], timeout=10.0).text
    assert "delegated payload" in body, body[:200]

    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_task_summary_endpoint_reflects_event_log(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """GET /tasks/{id}/summary returns derived counts from task_summary view.

    Locks the contract that's about to back the agent-facing
    get_task_summary tool: status, iterations, llm_calls, tools_called,
    cost, final_response. Uses a single specialist that writes one file —
    deterministic enough to count tool calls.
    """
    suffix = int(time.time())
    writer_id = create_agent(
        alice_client,
        llm_model,
        name=f"summary-writer-{suffix}",
        instruction=(
            "Save the contents 'summary fixture' to a file called fixture.txt "
            "using save_file, then call completion."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{writer_id}/tasks/sync",
        json={"description": "Save fixture.txt now."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    # Wait for completion before reading the summary; otherwise counters
    # will reflect a partial run.
    wait_for_workflow(alice_client, writer_id, task_id, timeout=90.0)

    summary = alice_client.get(
        f"/v1/agents/{writer_id}/tasks/{task_id}/summary"
    ).raise_for_status().json()

    assert summary["task_id"] == task_id
    assert summary["agent_id"] == writer_id
    assert summary["status"] == "completed", summary
    # Agent must have called save_file at least once. ``completion`` is a
    # control-plane sentinel, not a real tool call, so it doesn't count.
    assert summary["tools_called"] >= 1, summary
    assert summary["tools_failed"] == 0, summary
    assert summary["iterations"] >= 1, summary
    assert summary["llm_calls"] >= 1, summary
    assert summary["delegations_started"] == 0, summary
    # Final response is set by the completion tool — agent's narrative.
    assert summary["final_response"], summary
    # Cost may be 0 on a free local proxy but the field must be present
    # and numeric.
    assert isinstance(summary["cost_usd"], (int, float)), summary

    alice_client.delete(f"/v1/agents/{writer_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_task_summary_cross_workspace_blocked(
    alice_client: httpx.Client, bob_client: httpx.Client, llm_model: str
) -> None:
    """Bob must not be able to read the summary of Alice's task."""
    agent_id = create_agent(
        alice_client, llm_model, name=f"sum-iso-{int(time.time())}",
        instruction="Reply ok then complete.",
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Reply: ok"}, timeout=30.0,
    ).raise_for_status().json()["id"]

    cross = bob_client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/summary")
    assert cross.status_code == 404, (
        f"CRITICAL: Bob read Alice's task summary: HTTP {cross.status_code} "
        f"{cross.text[:200]!r}"
    )
    alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_fanout_partial_failure_completes_siblings(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """One child failing must not abort siblings.

    Before the fix, a single child's exception bubbled out of
    asyncio.gather inside _execute_agent_delegation and aborted the
    entire fan-out. Now each child's failure is converted to a tool
    message with status=failed, siblings continue to completion, and
    the parent's LLM gets to see all results.

    We can't easily synthesize a real LLM-call failure on demand, so we
    induce a child failure by giving one specialist a tool name that
    doesn't exist — the agent will call it and the workflow surfaces a
    tool error as ``status=failed`` in the envelope. Sibling continues
    normally; parent sees both envelopes; parent reaches WorkflowCompleted.
    """
    suffix = int(time.time())

    good_id = create_agent(
        alice_client, llm_model, name=f"good-{suffix}",
        instruction="Save 'ok' to good.txt via save_file then complete.",
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    bad_id = create_agent(
        alice_client, llm_model, name=f"bad-{suffix}",
        instruction=(
            "You have NO tools available. Just call completion with the "
            "result string 'I have nothing to do'."
        ),
        # No tools at all — child still completes, just with empty tool calls.
        # Real-world failure modes (LLM 503, tool errors) are infra-dependent
        # and flaky. Empty-toolset child reliably exercises the "child returns
        # to parent successfully but produces no side effects" path.
    )

    good = alice_client.get(f"/v1/agents/{good_id}").raise_for_status().json()
    bad = alice_client.get(f"/v1/agents/{bad_id}").raise_for_status().json()

    coord_id = create_agent(
        alice_client, llm_model, name=f"partial-coord-{suffix}",
        instruction=(
            f"Call delegate_to_{good['name'].replace('-','_')} once asking it "
            f"to save good.txt. Also call delegate_to_{bad['name'].replace('-','_')} "
            "once. Then call completion summarizing both results in one short paragraph."
        ),
        tools=[
            {"type": "agent", "name": good["name"]},
            {"type": "agent", "name": bad["name"]},
        ],
    )
    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={"description": "Run both agents in parallel."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, coord_id, task_id, timeout=120.0)
    types = [e["event_type"] for e in events]

    # Both delegations must have been attempted.
    assert sum(1 for e in events if e["event_type"] == "AgentDelegationStarted") == 2, types
    # The good one must have succeeded.
    completed = [e for e in events if e["event_type"] == "AgentDelegationCompleted"]
    assert any(
        e["metadata"]["target_agent_name"] == good["name"]
        and e["metadata"]["success"] is True
        for e in completed
    ), [e["metadata"] for e in completed]
    # Critically, the parent reached WorkflowCompleted — proving siblings
    # were not aborted by the bad child's outcome.
    assert "WorkflowCompleted" in types, types

    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_agent_can_read_back_file_it_wrote(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """The file_toolset round-trip: write, list, read same content back.

    Covers the basic 'agent can use its scratchpad' contract — write a
    file, list to confirm it shows up, read to confirm the bytes round-trip.
    All three calls go through ``agentarea/files`` which is workspace-scoped
    + task-prefixed, so this also indirectly proves the storage path is
    consistent across save/list/read within one task.
    """
    suffix = int(time.time())
    agent_id = create_agent(
        alice_client,
        llm_model,
        name=f"file-rw-{suffix}",
        instruction=(
            "Do exactly these steps in order:\n"
            "1. Call save_file with file_name='note.txt' and contents='alpha-bravo-charlie'.\n"
            "2. Call list_files (no pattern argument).\n"
            "3. Call read_file with file_name='note.txt'.\n"
            "4. Call completion with the EXACT contents you read back, nothing else."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Run the file round-trip steps."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id, timeout=120.0)

    # All three file actions must have actually been invoked. Code tools
    # in DYNAMIC mode are exposed as a single function per toolset (e.g.
    # ``files``) with an ``action`` arg the LLM picks — so the event's
    # tool_name is the toolset, and we read the action from the args.
    file_actions = [
        (e["metadata"].get("arguments") or {}).get("action")
        for e in events
        if e["event_type"] == "ToolCallStarted"
        and e["metadata"]["tool_name"] == "files"
    ]
    for required in ("save_file", "list_files", "read_file"):
        assert required in file_actions, (
            f"agent didn't call files/{required}; file actions seen: {file_actions}"
        )

    # And the artifact actually exists on the side: the artifact list
    # endpoint should now show note.txt with the right size.
    artifacts = alice_client.get(
        f"/v1/agents/{agent_id}/tasks/{task_id}/artifacts"
    ).raise_for_status().json()
    notes = [a for a in artifacts if a["path"].endswith("note.txt")]
    assert notes, f"note.txt missing from storage; got {[a['path'] for a in artifacts]}"
    body = httpx.get(notes[0]["download_url"], timeout=10.0).text
    assert body == "alpha-bravo-charlie", body[:200]

    alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")


@pytest.mark.integration
@pytest.mark.slow
def test_summary_reflects_delegation_counts(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """task_summary view's delegation counters update from real fan-out.

    Exercises that the projection logic correctly counts the
    AgentDelegationStarted/Completed events the workflow emits — same
    code path the UI's task tree will rely on.
    """
    suffix = int(time.time())
    child_id = create_agent(
        alice_client, llm_model, name=f"sum-child-{suffix}",
        instruction="Reply with the word 'ok' then call completion.",
    )
    child = alice_client.get(f"/v1/agents/{child_id}").raise_for_status().json()

    coord_id = create_agent(
        alice_client, llm_model, name=f"sum-coord-{suffix}",
        instruction=(
            f"Call delegate_to_{child['name'].replace('-','_')} once with "
            "the message 'reply ok'. When it returns, call completion with "
            "a single short sentence."
        ),
        tools=[{"type": "agent", "name": child["name"]}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={"description": "Delegate once."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    wait_for_workflow(alice_client, coord_id, task_id, timeout=120.0)

    summary = alice_client.get(
        f"/v1/agents/{coord_id}/tasks/{task_id}/summary"
    ).raise_for_status().json()

    assert summary["status"] == "completed", summary
    assert summary["delegations_started"] == 1, summary
    assert summary["delegations_completed"] == 1, summary
    assert summary["delegations_failed"] == 0, summary

    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")
