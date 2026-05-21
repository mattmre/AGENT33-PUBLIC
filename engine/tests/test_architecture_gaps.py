"""Tests for P3 Architecture Gaps: document extraction, workflow actions,
and executor dispatch for http-request, sub-workflow, and route.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.memory.ingestion import DocumentExtractor
from agent33.workflows.actions import http_request, route, sub_workflow
from agent33.workflows.definition import (
    StepAction,
    WorkflowDefinition,
    WorkflowStep,
)
from agent33.workflows.executor import WorkflowExecutor, WorkflowStatus

# ── DocumentExtractor — PDF via pymupdf ──────────────────────────────


class TestExtractPdfPymupdf:
    """PDF extraction when pymupdf (fitz) is available."""

    def test_extract_pdf_with_pymupdf(self) -> None:
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Page 1 content"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2 content"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page1, mock_page2]))
        mock_doc.__len__ = MagicMock(return_value=2)
        # Support context manager (with fitz.open(...) as doc:)
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        with patch.dict("sys.modules", {"fitz": mock_fitz}):
            extractor = DocumentExtractor()
            result = extractor.extract_pdf(b"fake-pdf-bytes")

        assert result == "Page 1 content\n\nPage 2 content"
        mock_fitz.open.assert_called_once_with(stream=b"fake-pdf-bytes", filetype="pdf")
        mock_page1.get_text.assert_called_once()
        mock_page2.get_text.assert_called_once()


# ── DocumentExtractor — PDF via pdfplumber fallback ──────────────────


class TestExtractPdfPdfplumber:
    """PDF extraction falls back to pdfplumber when fitz is absent."""

    def test_extract_pdf_with_pdfplumber_fallback(self) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Plumber page text"

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        # Ensure fitz is NOT available
        with (
            patch.dict("sys.modules", {"fitz": None, "pdfplumber": mock_pdfplumber}),
        ):
            extractor = DocumentExtractor()
            result = extractor.extract_pdf(b"fake-pdf-bytes")

        assert result == "Plumber page text"
        mock_page.extract_text.assert_called_once()


# ── DocumentExtractor — no PDF library ───────────────────────────────


class TestExtractPdfNoLibrary:
    """Raises ImportError when neither PDF library is installed."""

    def test_extract_pdf_no_library(self) -> None:
        with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None}):
            extractor = DocumentExtractor()
            with pytest.raises(ImportError, match="pymupdf"):
                extractor.extract_pdf(b"fake-pdf-bytes")


# ── DocumentExtractor — image OCR ────────────────────────────────────


class TestExtractImageOcr:
    """Image OCR extraction via pytesseract + Pillow."""

    def test_extract_image_ocr(self) -> None:
        mock_pytesseract = MagicMock()
        mock_pytesseract.image_to_string.return_value = "Extracted OCR text"

        mock_image = MagicMock()
        mock_pil_image = MagicMock()
        mock_pil_image.open.return_value = mock_image

        with patch.dict(
            "sys.modules",
            {
                "pytesseract": mock_pytesseract,
                "PIL": MagicMock(),
                "PIL.Image": mock_pil_image,
            },
        ):
            extractor = DocumentExtractor()
            result = extractor.extract_image_ocr(b"fake-image-bytes")

        assert result == "Extracted OCR text"
        mock_pytesseract.image_to_string.assert_called_once()


class TestExtractImageNoLibrary:
    """Raises ImportError when OCR libraries are missing."""

    def test_extract_image_no_library(self) -> None:
        with patch.dict(
            "sys.modules",
            {"pytesseract": None, "PIL": None, "PIL.Image": None},
        ):
            extractor = DocumentExtractor()
            with pytest.raises(ImportError, match="pytesseract"):
                extractor.extract_image_ocr(b"fake-image")


# ── DocumentExtractor — content type routing ─────────────────────────


class TestExtractTextRouting:
    """extract_text routes to the right method based on content_type."""

    def test_routes_pdf_mime(self) -> None:
        extractor = DocumentExtractor()
        extractor.extract_pdf = MagicMock(return_value="pdf text")
        result = extractor.extract_text(b"data", "application/pdf")
        assert result == "pdf text"
        extractor.extract_pdf.assert_called_once_with(b"data")

    def test_routes_pdf_alias(self) -> None:
        extractor = DocumentExtractor()
        extractor.extract_pdf = MagicMock(return_value="pdf text")
        result = extractor.extract_text(b"data", "pdf")
        assert result == "pdf text"
        extractor.extract_pdf.assert_called_once_with(b"data")

    def test_routes_image(self) -> None:
        extractor = DocumentExtractor()
        extractor.extract_image_ocr = MagicMock(return_value="ocr text")
        result = extractor.extract_text(b"data", "image/png")
        assert result == "ocr text"
        extractor.extract_image_ocr.assert_called_once_with(b"data")

    def test_routes_image_jpeg(self) -> None:
        extractor = DocumentExtractor()
        extractor.extract_image_ocr = MagicMock(return_value="ocr text")
        result = extractor.extract_text(b"data", "image/jpeg")
        assert result == "ocr text"

    def test_extract_text_utf8_fallback(self) -> None:
        extractor = DocumentExtractor()
        result = extractor.extract_text(b"Hello plain text", "text/plain")
        assert result == "Hello plain text"

    def test_extract_text_utf8_with_invalid_bytes(self) -> None:
        extractor = DocumentExtractor()
        result = extractor.extract_text(b"Hello \xff\xfe world", "text/plain")
        # errors="replace" should handle invalid bytes
        assert "Hello" in result
        assert "world" in result


# ── HTTP Request Action ──────────────────────────────────────────────


class TestHttpRequestAction:
    """Tests for the http-request workflow action."""

    async def test_http_request_no_url(self) -> None:
        with pytest.raises(ValueError, match="url"):
            await http_request.execute(url=None)

    async def test_http_request_dry_run(self) -> None:
        result = await http_request.execute(url="https://example.com", method="POST", dry_run=True)
        assert result["dry_run"] is True
        assert result["url"] == "https://example.com"
        assert result["method"] == "POST"

    async def test_http_request_get(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("agent33.workflows.actions.http_request.httpx") as m:
            m.AsyncClient.return_value = mock_client
            result = await http_request.execute(url="https://api.example.com/data")

        assert result["status_code"] == 200
        assert result["json"] == {"ok": True}
        assert result["body"] == '{"ok": true}'
        assert "content-type" in result["headers"]
        mock_client.request.assert_called_once_with(
            "GET", "https://api.example.com/data", headers={}
        )

    async def test_http_request_post_json(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = '{"id": 42}'
        mock_response.headers = {}
        mock_response.json.return_value = {"id": 42}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("agent33.workflows.actions.http_request.httpx") as m:
            m.AsyncClient.return_value = mock_client
            result = await http_request.execute(
                url="https://api.example.com/items",
                method="POST",
                body={"name": "test"},
            )

        assert result["status_code"] == 201
        assert result["json"] == {"id": 42}
        mock_client.request.assert_called_once_with(
            "POST",
            "https://api.example.com/items",
            headers={},
            json={"name": "test"},
        )

    async def test_http_request_with_headers(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_response.headers = {}
        mock_response.json.side_effect = ValueError("not json")

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("agent33.workflows.actions.http_request.httpx") as m:
            m.AsyncClient.return_value = mock_client
            result = await http_request.execute(
                url="https://api.example.com",
                headers={"Authorization": "Bearer tok123"},
            )

        assert result["status_code"] == 200
        assert result["json"] is None  # json parse failed
        assert result["body"] == "ok"
        mock_client.request.assert_called_once_with(
            "GET",
            "https://api.example.com",
            headers={"Authorization": "Bearer tok123"},
        )

    async def test_http_request_text_body(self) -> None:
        """Non-dict/list body is sent as text content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "received"
        mock_response.headers = {}
        mock_response.json.side_effect = ValueError

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("agent33.workflows.actions.http_request.httpx") as m:
            m.AsyncClient.return_value = mock_client
            result = await http_request.execute(
                url="https://example.com",
                method="PUT",
                body="raw text data",
            )

        assert result["status_code"] == 200
        mock_client.request.assert_called_once_with(
            "PUT",
            "https://example.com",
            headers={},
            content="raw text data",
        )


# ── Sub-Workflow Action ──────────────────────────────────────────────


class TestSubWorkflowAction:
    """Tests for the sub-workflow action."""

    async def test_sub_workflow_no_definition(self) -> None:
        with pytest.raises(ValueError, match="workflow_definition"):
            await sub_workflow.execute(workflow_definition=None)

    async def test_sub_workflow_dry_run(self) -> None:
        defn = {
            "name": "sub-test",
            "version": "1.0.0",
            "steps": [
                {"id": "s1", "action": "transform"},
                {"id": "s2", "action": "transform"},
            ],
        }
        result = await sub_workflow.execute(workflow_definition=defn, dry_run=True)
        assert result["dry_run"] is True
        assert result["step_count"] == 2

    async def test_sub_workflow_executes(self) -> None:
        """Execute a real 1-step transform sub-workflow with numeric data."""
        defn = {
            "name": "sub-transform",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "t1",
                    "action": "transform",
                    "inputs": {
                        "data": 42,
                    },
                }
            ],
        }
        result = await sub_workflow.execute(workflow_definition=defn, inputs={})
        assert result["status"] == "success"
        assert result["steps_executed"] == ["t1"]
        assert result["duration_ms"] >= 0
        # The transform passes through numeric data
        assert result["outputs"]["result"] == 42

    async def test_sub_workflow_passes_inputs(self) -> None:
        """Verify inputs are forwarded to the sub-workflow state."""
        defn = {
            "name": "sub-passthrough",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "t1",
                    "action": "transform",
                    "inputs": {"data": "{{greeting}}"},
                }
            ],
        }
        result = await sub_workflow.execute(
            workflow_definition=defn,
            inputs={"greeting": "hi there"},
        )
        assert result["status"] == "success"
        assert result["outputs"]["result"] == "hi there"


# ── Route Action ─────────────────────────────────────────────────────


class TestRouteAction:
    """Tests for the route workflow action."""

    async def test_route_no_query(self) -> None:
        with pytest.raises(ValueError, match="query"):
            await route.execute(query=None)

    async def test_route_no_candidates(self) -> None:
        """No registry and no explicit candidates raises ValueError."""
        original_registry = route._agent_registry
        try:
            route._agent_registry = None
            with pytest.raises(ValueError, match="No candidate"):
                await route.execute(query="help me code")
        finally:
            route._agent_registry = original_registry

    async def test_route_dry_run(self) -> None:
        original_registry = route._agent_registry
        try:
            route._agent_registry = None
            result = await route.execute(
                query="hello",
                candidates=["agent-a", "agent-b"],
                dry_run=True,
            )
            assert result["dry_run"] is True
            assert result["candidates"] == ["agent-a", "agent-b"]
        finally:
            route._agent_registry = original_registry

    async def test_route_no_router_fallback(self) -> None:
        """Without a model router, falls back to first candidate."""
        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = None
            route._agent_registry = None
            result = await route.execute(
                query="analyze this code",
                candidates=["code-worker", "researcher"],
            )
            assert result["selected_agent"] == "code-worker"
            assert result["confidence"] == 0.0
            assert result["reason"] == "no_router"
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry

    async def test_route_with_llm(self) -> None:
        """LLM returns valid JSON selecting an agent."""
        llm_response = SimpleNamespace(
            content=json.dumps(
                {
                    "agent": "researcher",
                    "confidence": 0.92,
                    "reason": "Research query detected",
                }
            )
        )
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=llm_response)

        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = mock_router
            route._agent_registry = None
            result = await route.execute(
                query="find papers on transformers",
                candidates=["code-worker", "researcher"],
            )
            assert result["selected_agent"] == "researcher"
            assert result["confidence"] == 0.92
            assert result["reason"] == "Research query detected"
            mock_router.complete.assert_called_once()
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry

    async def test_route_parse_error_fallback(self) -> None:
        """LLM returns unparseable text, falls back to first candidate."""
        llm_response = SimpleNamespace(content="I think agent-a")
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=llm_response)

        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = mock_router
            route._agent_registry = None
            result = await route.execute(
                query="help",
                candidates=["agent-a", "agent-b"],
            )
            assert result["selected_agent"] == "agent-a"
            assert result["confidence"] == 0.0
            assert result["reason"] == "parse_error"
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry

    async def test_route_with_registry(self) -> None:
        """Route uses agent registry to build candidate list."""
        from agent33.agents.definition import (
            AgentDefinition,
            AgentRole,
        )
        from agent33.agents.registry import AgentRegistry

        registry = AgentRegistry()
        registry.register(
            AgentDefinition(
                name="code-worker",
                version="1.0.0",
                role=AgentRole.IMPLEMENTER,
                description="Writes code",
            )
        )
        registry.register(
            AgentDefinition(
                name="researcher",
                version="1.0.0",
                role=AgentRole.RESEARCHER,
                description="Finds information",
            )
        )

        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = None  # no LLM, uses fallback
            route._agent_registry = registry
            result = await route.execute(
                query="write a function",
                candidates=["code-worker"],
            )
            # Only code-worker is in candidates filter
            assert result["selected_agent"] == "code-worker"
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry

    async def test_route_llm_markdown_fenced(self) -> None:
        """LLM wraps JSON in markdown code fences."""
        fenced = '```json\n{"agent": "qa", "confidence": 0.8, "reason": "test"}\n```'
        llm_response = SimpleNamespace(content=fenced)
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=llm_response)

        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = mock_router
            route._agent_registry = None
            result = await route.execute(
                query="run tests",
                candidates=["qa", "code-worker"],
            )
            assert result["selected_agent"] == "qa"
            assert result["confidence"] == 0.8
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry


# ── StepAction Enum ──────────────────────────────────────────────────


class TestNewStepActions:
    """Verify the three new StepAction enum members exist."""

    def test_http_request_action_exists(self) -> None:
        assert StepAction.HTTP_REQUEST.value == "http-request"

    def test_sub_workflow_action_exists(self) -> None:
        assert StepAction.SUB_WORKFLOW.value == "sub-workflow"

    def test_route_action_exists(self) -> None:
        assert StepAction.ROUTE.value == "route"


# ── WorkflowStep model accepts new fields ────────────────────────────


class TestWorkflowStepNewFields:
    """Verify WorkflowStep accepts the new action-specific fields."""

    def test_http_request_fields(self) -> None:
        step = WorkflowStep(
            id="h1",
            action=StepAction.HTTP_REQUEST,
            url="https://example.com",
            http_method="POST",
            http_headers={"X-Key": "val"},
            http_body={"data": 1},
        )
        assert step.url == "https://example.com"
        assert step.http_method == "POST"
        assert step.http_headers == {"X-Key": "val"}
        assert step.http_body == {"data": 1}

    def test_sub_workflow_field(self) -> None:
        step = WorkflowStep(
            id="sw1",
            action=StepAction.SUB_WORKFLOW,
            sub_workflow={
                "name": "inner",
                "version": "1.0.0",
                "steps": [],
            },
        )
        assert step.sub_workflow is not None
        assert step.sub_workflow["name"] == "inner"

    def test_route_fields(self) -> None:
        step = WorkflowStep(
            id="r1",
            action=StepAction.ROUTE,
            query="help me",
            route_candidates=["a", "b"],
            route_model="gpt-4",
        )
        assert step.query == "help me"
        assert step.route_candidates == ["a", "b"]
        assert step.route_model == "gpt-4"

    def test_route_fields_defaults(self) -> None:
        step = WorkflowStep(id="r2", action=StepAction.ROUTE)
        assert step.query is None
        assert step.route_candidates is None
        assert step.route_model == "llama3.2"


# ── Executor Dispatch ────────────────────────────────────────────────


class TestExecutorDispatch:
    """Test that WorkflowExecutor dispatches to the new actions."""

    async def test_executor_http_request_step(self) -> None:
        """Executor dispatches http-request step in dry_run mode."""
        defn = WorkflowDefinition(
            name="http-test",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    id="fetch",
                    action=StepAction.HTTP_REQUEST,
                    url="https://api.example.com/data",
                    http_method="GET",
                )
            ],
            execution={"dry_run": True},
        )
        executor = WorkflowExecutor(defn)
        result = await executor.execute({})

        assert result.status == WorkflowStatus.SUCCESS
        assert "fetch" in result.steps_executed
        fetch_output = result.outputs
        assert fetch_output["dry_run"] is True
        assert fetch_output["url"] == "https://api.example.com/data"
        assert fetch_output["method"] == "GET"

    async def test_executor_sub_workflow_step(self) -> None:
        """Executor dispatches sub-workflow step."""
        defn = WorkflowDefinition(
            name="sub-test",
            version="1.0.0",
            steps=[
                WorkflowStep(
                    id="nested",
                    action=StepAction.SUB_WORKFLOW,
                    sub_workflow={
                        "name": "inner-wf",
                        "version": "1.0.0",
                        "steps": [
                            {
                                "id": "t1",
                                "action": "transform",
                                "inputs": {
                                    "data": 99,
                                },
                            }
                        ],
                    },
                )
            ],
        )
        executor = WorkflowExecutor(defn)
        result = await executor.execute({})

        assert result.status == WorkflowStatus.SUCCESS
        assert "nested" in result.steps_executed
        nested_output = result.outputs
        assert nested_output["status"] == "success"
        assert nested_output["outputs"]["result"] == 99

    async def test_executor_route_step_dry_run(self) -> None:
        """Executor dispatches route step in dry_run mode."""
        original_registry = route._agent_registry
        try:
            route._agent_registry = None
            defn = WorkflowDefinition(
                name="route-test",
                version="1.0.0",
                steps=[
                    WorkflowStep(
                        id="pick-agent",
                        action=StepAction.ROUTE,
                        query="analyze my data",
                        route_candidates=["analyst", "coder"],
                    )
                ],
                execution={"dry_run": True},
            )
            executor = WorkflowExecutor(defn)
            result = await executor.execute({})

            assert result.status == WorkflowStatus.SUCCESS
            assert "pick-agent" in result.steps_executed
            out = result.outputs
            assert out["dry_run"] is True
            assert out["candidates"] == ["analyst", "coder"]
        finally:
            route._agent_registry = original_registry

    async def test_executor_route_step_no_router(self) -> None:
        """Route step without router falls back to first candidate."""
        original_router = route._model_router
        original_registry = route._agent_registry
        try:
            route._model_router = None
            route._agent_registry = None
            defn = WorkflowDefinition(
                name="route-fallback",
                version="1.0.0",
                steps=[
                    WorkflowStep(
                        id="r1",
                        action=StepAction.ROUTE,
                        query="help me",
                        route_candidates=["first", "second"],
                    )
                ],
            )
            executor = WorkflowExecutor(defn)
            result = await executor.execute({})

            assert result.status == WorkflowStatus.SUCCESS
            out = result.outputs
            assert out["selected_agent"] == "first"
            assert out["confidence"] == 0.0
        finally:
            route._model_router = original_router
            route._agent_registry = original_registry
