import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OperationConfig } from "../types";
import { workflowsDomain } from "../data/domains/workflows";

const {
  apiRequestMock,
  connectWorkflowLiveTransportMock,
  shouldRefreshWorkflowGraphMock,
  isWorkflowTerminalEventMock
} = vi.hoisted(() => ({
  apiRequestMock: vi.fn(),
  connectWorkflowLiveTransportMock: vi.fn(),
  shouldRefreshWorkflowGraphMock: vi.fn((event: { type: string }) => event.type !== "heartbeat"),
  isWorkflowTerminalEventMock: vi.fn(
    (event: { type: string }) =>
      event.type === "workflow_completed" || event.type === "workflow_failed"
  )
}));

vi.mock("../lib/api", () => ({
  apiRequest: apiRequestMock
}));

vi.mock("../lib/workflowLiveTransport", () => ({
  connectWorkflowLiveTransport: connectWorkflowLiveTransportMock,
  shouldRefreshWorkflowGraph: shouldRefreshWorkflowGraphMock,
  isWorkflowTerminalEvent: isWorkflowTerminalEventMock
}));

vi.mock("./WorkflowGraph", () => ({
  WorkflowGraph: ({ data }: { data: { workflow_id: string; nodes: unknown[] } }) => (
    <div data-testid="workflow-graph">
      {data.workflow_id}:{data.nodes.length}
    </div>
  )
}));

import { OperationCard } from "./OperationCard";

const workflowExecuteOperation: OperationConfig = {
  id: "workflows-execute",
  title: "Execute Workflow",
  method: "POST",
  path: "/v1/workflows/{name}/execute",
  description: "Execute a workflow.",
  defaultPathParams: { name: "hello-flow" },
  defaultQuery: {},
  defaultBody: JSON.stringify({ inputs: { name: "AGENT-33" } }, null, 2),
  uxHint: "workflow-execute"
};

const presetCreateOperation = workflowsDomain.operations.find(
  (operation) => operation.id === "workflows-create"
) as OperationConfig;

const presetExecuteOperation = workflowsDomain.operations.find(
  (operation) => operation.id === "workflows-execute"
) as OperationConfig;

describe("OperationCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiRequestMock.mockReset();
    connectWorkflowLiveTransportMock.mockReset();
    shouldRefreshWorkflowGraphMock.mockClear();
    isWorkflowTerminalEventMock.mockClear();
  });

  it("wires single-run workflow execution to graph fetch and live refreshes", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "11111111-1111-4111-8111-111111111111"
    );

    let liveEventHandler: ((event: { type: string }) => Promise<void> | void) | undefined;
    const disconnectMock = vi.fn();
    connectWorkflowLiveTransportMock.mockImplementation(
      (options: { onEvent: (event: { type: string }) => Promise<void> | void }) => {
        liveEventHandler = options.onEvent;
        return { close: disconnectMock };
      }
    );

    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 10,
        url: "/v1/workflows/hello-flow/execute",
        data: { run_id: "11111111-1111-4111-8111-111111111111", status: "success" }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "/v1/visualizations/workflows/hello-flow/graph?run_id=11111111-1111-4111-8111-111111111111",
        data: {
          workflow_id: "hello-flow",
          nodes: [{ id: "step-a" }],
          edges: []
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "/v1/visualizations/workflows/hello-flow/graph?run_id=11111111-1111-4111-8111-111111111111",
        data: {
          workflow_id: "hello-flow",
          nodes: [{ id: "step-a" }, { id: "step-b" }],
          edges: []
        }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "/v1/visualizations/workflows/hello-flow/graph?run_id=11111111-1111-4111-8111-111111111111",
        data: {
          workflow_id: "hello-flow",
          nodes: [{ id: "step-a" }, { id: "step-b" }, { id: "step-c" }],
          edges: []
        }
      });

    const onResult = vi.fn();
    render(
      <OperationCard
        operation={workflowExecuteOperation}
        token="jwt-token"
        apiKey=""
        onResult={onResult}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      inputs: { name: "AGENT-33" },
      run_id: "11111111-1111-4111-8111-111111111111"
    });
    expect(apiRequestMock.mock.calls[1][0]).toMatchObject({
      method: "GET",
      path: "/v1/visualizations/workflows/{workflow_id}/graph",
      pathParams: { workflow_id: "hello-flow" },
      query: { run_id: "11111111-1111-4111-8111-111111111111" }
    });
    expect(connectWorkflowLiveTransportMock).toHaveBeenCalledWith(
      expect.objectContaining({ runId: "11111111-1111-4111-8111-111111111111", token: "jwt-token" })
    );
    expect(screen.getByTestId("workflow-graph")).toHaveTextContent("hello-flow:1");

    await act(async () => {
      await liveEventHandler?.({ type: "heartbeat" });
    });
    expect(apiRequestMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await liveEventHandler?.({ type: "step_completed" });
    });
    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(3));
    expect(screen.getByTestId("workflow-graph")).toHaveTextContent("hello-flow:2");

    await act(async () => {
      await liveEventHandler?.({ type: "workflow_completed" });
    });
    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(4));
    expect(disconnectMock).toHaveBeenCalled();
    expect(screen.getByTestId("workflow-graph")).toHaveTextContent("hello-flow:3");
    expect(onResult).toHaveBeenCalledTimes(1);
  });

  it("keeps repeat-mode execution on the existing non-live path", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      durationMs: 10,
      url: "/v1/workflows/hello-flow/execute",
      data: { status: "success", executions: 2 }
    });

    render(
      <OperationCard
        operation={workflowExecuteOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    await userEvent.selectOptions(screen.getByLabelText("Mode"), "repeat");
    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      inputs: { name: "AGENT-33" },
      repeat_count: 3,
      autonomous: false
    });
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).not.toHaveProperty("run_id");
    expect(connectWorkflowLiveTransportMock).not.toHaveBeenCalled();
  });

  it("shows the raw endpoint warning only after advanced controls are visible", async () => {
    render(
      <OperationCard
        operation={presetExecuteOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    expect(screen.queryByText("Raw endpoint mode")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Advanced" }));

    expect(screen.getByText("Raw endpoint mode")).toBeInTheDocument();
    expect(screen.getByText(/Review path params, query params, and JSON body/)).toBeInTheDocument();
  });

  it("requires an explicit apply action before a workflow preset overwrites execute inputs", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "22222222-2222-4222-8222-222222222222"
    );

    connectWorkflowLiveTransportMock.mockReturnValue({ close: vi.fn() });
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 10,
        url: "/v1/workflows/hello-flow/execute",
        data: { run_id: "22222222-2222-4222-8222-222222222222", status: "success" }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "/v1/visualizations/workflows/hello-flow/graph?run_id=22222222-2222-4222-8222-222222222222",
        data: {
          workflow_id: "hello-flow",
          nodes: [],
          edges: []
        }
      });

    render(
      <OperationCard
        operation={presetExecuteOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    await userEvent.selectOptions(await screen.findByLabelText("Workflow Preset"), "metrics-review");
    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(2));
    expect(apiRequestMock.mock.calls[0][0].pathParams).toEqual({ name: "hello-flow" });
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      inputs: { name: "AGENT-33" },
      run_id: "22222222-2222-4222-8222-222222222222"
    });
  });

  it("applies workflow presets to create payloads and execute requests", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      durationMs: 12,
      url: "/v1/workflows/",
      data: { created: true, name: "improvement-cycle-retrospective" }
    });

    const { unmount } = render(
      <OperationCard
        operation={presetCreateOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    await userEvent.click(await screen.findByRole("button", { name: "Apply preset" }));
    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      name: "improvement-cycle-retrospective",
      version: "1.0.0"
    });

    unmount();
    apiRequestMock.mockReset();
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "33333333-3333-4333-8333-333333333333"
    );
    connectWorkflowLiveTransportMock.mockReturnValue({ close: vi.fn() });
    apiRequestMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 10,
        url: "/v1/workflows/improvement-cycle-metrics-review/execute",
        data: { run_id: "33333333-3333-4333-8333-333333333333", status: "success" }
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        durationMs: 5,
        url: "/v1/visualizations/workflows/improvement-cycle-metrics-review/graph?run_id=33333333-3333-4333-8333-333333333333",
        data: {
          workflow_id: "improvement-cycle-metrics-review",
          nodes: [{ id: "validate" }],
          edges: []
        }
      });

    render(
      <OperationCard
        operation={presetExecuteOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    await userEvent.selectOptions(await screen.findByLabelText("Workflow Preset"), "metrics-review");
    await userEvent.click(await screen.findByRole("button", { name: "Apply preset" }));
    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(2));
    expect(apiRequestMock.mock.calls[0][0].pathParams).toEqual({
      name: "improvement-cycle-metrics-review"
    });
    expect(JSON.parse(apiRequestMock.mock.calls[0][0].body as string)).toMatchObject({
      inputs: {
        review_period: "2026-03-01 to 2026-03-07",
        baseline_period: "2026-02-23 to 2026-02-29"
      },
      run_id: "33333333-3333-4333-8333-333333333333"
    });
  });

  it("passes custom headers through the shared request helper", async () => {
    apiRequestMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      durationMs: 9,
      url: "/v1/auth/api-keys",
      data: { key_id: "key-1" }
    });

    const headerOperation: OperationConfig = {
      id: "auth-create-api-key",
      title: "Create API Key",
      method: "POST",
      path: "/v1/auth/api-keys",
      description: "Generate a scoped API key after route approval.",
      defaultHeaders: { "X-Agent33-Approval-Token": "" },
      defaultBody: JSON.stringify(
        {
          subject: "agent-service",
          scopes: ["agents:read"]
        },
        null,
        2
      )
    };

    render(
      <OperationCard
        operation={headerOperation}
        token="jwt-token"
        apiKey=""
        onResult={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText("Headers (JSON)"), {
      target: { value: '{\n  "X-Agent33-Approval-Token": "approval-token-123"\n}' }
    });
    await userEvent.click(screen.getByRole("button", { name: /^Run / }));

    await waitFor(() => expect(apiRequestMock).toHaveBeenCalledTimes(1));
    expect(apiRequestMock.mock.calls[0][0]).toMatchObject({
      headers: { "X-Agent33-Approval-Token": "approval-token-123" }
    });
  });
});
