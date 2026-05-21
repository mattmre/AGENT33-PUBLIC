"""E2E: Multi-tenant data isolation through the HTTP API.

These tests verify that:
1. Tenant-scoped requests cannot access other tenants' data
2. Admin callers see cross-tenant data
3. Unauthenticated requests are rejected
4. Session and workflow data is properly tenant-partitioned
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


class TestTenantAuthEnforcement:
    """Authentication and authorization boundary tests."""

    def test_unauthenticated_request_returns_401(self, e2e_client):
        """Requests without any credentials get 401.

        This catches regressions where new routes accidentally bypass
        the AuthMiddleware.
        """
        _, client, _ = e2e_client

        resp = client.get("/v1/agents/")
        assert resp.status_code == 401

    def test_unauthenticated_post_returns_401(self, e2e_client):
        """POST endpoints also enforce authentication.

        Separate from GET to catch asymmetric middleware bypass bugs.
        """
        _, client, _ = e2e_client

        resp = client.post(
            "/v1/agents/some-agent/invoke",
            json={"inputs": {"prompt": "hello"}},
        )
        assert resp.status_code == 401

    def test_public_endpoints_do_not_require_auth(self, e2e_client):
        """Dashboard endpoint is accessible without auth.

        Verifies the public route allowlist is working correctly.
        Note: /health is excluded because it probes external services
        with network timeouts; we test auth bypass via the dashboard.
        """
        _, client, _ = e2e_client

        # Dashboard endpoint (public HTML page, no auth required)
        resp = client.get("/v1/dashboard/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestSessionTenantIsolation:
    """Session data isolation between tenants."""

    def test_tenant_client_allows_case_insensitive_auth_override(
        self,
        tenant_a_client,
        tenant_b_token,
    ):
        """Lowercase authorization overrides should replace, not append, fixture auth."""
        _, client_a = tenant_a_client

        resp = client_a.post(
            "/v1/sessions/",
            json={"purpose": "tenant-a-override-check"},
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized in E2E")

        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        overridden = client_a.get(
            f"/v1/sessions/{session_id}",
            headers={"authorization": f"Bearer {tenant_b_token}"},
        )
        assert overridden.status_code == 403

    def test_tenant_a_cannot_see_tenant_b_sessions(self, tenant_a_client, tenant_b_client):
        """Tenant A creates a session; tenant B cannot see it in listing.

        This is the core multi-tenancy isolation test. If the session listing
        does not filter by tenant_id, tenant B would see tenant A's sessions,
        which is a data leak.
        """
        app, client_a = tenant_a_client
        _, client_b = tenant_b_client

        # Check that session service is available
        resp_check = client_a.post(
            "/v1/sessions/",
            json={"purpose": "tenant-a-e2e-session"},
        )
        if resp_check.status_code == 503:
            pytest.skip("Operator session service not initialized in E2E")

        assert resp_check.status_code == 201
        session_a = resp_check.json()
        session_a_id = session_a["session_id"]
        assert session_a["tenant_id"] == "tenant-a"

        # Tenant B lists sessions -- should not see tenant A's session
        resp_b = client_b.get("/v1/sessions/")
        assert resp_b.status_code == 200
        b_sessions = resp_b.json()
        b_session_ids = [s["session_id"] for s in b_sessions]
        assert session_a_id not in b_session_ids

    def test_tenant_cannot_access_other_tenants_session_by_id(
        self, tenant_a_client, tenant_b_client
    ):
        """Direct GET by session ID enforces tenant ownership.

        Even if tenant B somehow knows tenant A's session_id, the API
        should return 403 (tenant mismatch), not the session data.
        """
        app, client_a = tenant_a_client
        _, client_b = tenant_b_client

        resp = client_a.post(
            "/v1/sessions/",
            json={"purpose": "tenant-a-direct-access-test"},
        )
        if resp.status_code == 503:
            pytest.skip("Operator session service not initialized in E2E")

        assert resp.status_code == 201
        session_id = resp.json()["session_id"]

        # Tenant B tries direct access
        resp_b = client_b.get(f"/v1/sessions/{session_id}")
        assert resp_b.status_code == 403

    def test_admin_sees_all_tenants_sessions(self, tenant_a_client, tenant_b_client, admin_client):
        """Admin callers bypass tenant filtering and see all sessions.

        This verifies the admin override logic works correctly, which is
        needed for platform operators.
        """
        app_a, client_a = tenant_a_client
        _, client_b = tenant_b_client
        _, admin_cl, _ = admin_client

        # Create sessions as both tenants
        resp_a = client_a.post(
            "/v1/sessions/",
            json={"purpose": "admin-view-test-a"},
        )
        if resp_a.status_code == 503:
            pytest.skip("Operator session service not initialized in E2E")

        resp_b = client_b.post(
            "/v1/sessions/",
            json={"purpose": "admin-view-test-b"},
        )
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201

        session_a_id = resp_a.json()["session_id"]
        session_b_id = resp_b.json()["session_id"]

        # Admin lists all sessions
        resp_admin = admin_cl.get("/v1/sessions/")
        assert resp_admin.status_code == 200
        admin_session_ids = [s["session_id"] for s in resp_admin.json()]

        # Admin should see both
        assert session_a_id in admin_session_ids
        assert session_b_id in admin_session_ids


class TestWorkflowTenantIsolation:
    """Workflow execution history is tenant-partitioned."""

    def test_workflow_history_is_tenant_scoped(
        self,
        tenant_a_client,
        tenant_b_client,
        tenant_a_token,
        route_approval_headers,
    ):
        """Tenant A executes a workflow; tenant B cannot see it in history.

        Workflow execution history records include tenant_id. The history
        endpoint filters by the calling tenant, preventing cross-tenant
        visibility of execution results.
        """
        _, client_a = tenant_a_client
        _, client_b = tenant_b_client

        wf_def = {
            "name": "e2e-tenant-wf",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "step-1",
                    "action": "transform",
                    "config": {"expression": "'tenant-test'"},
                },
            ],
        }

        # Tenant A creates and executes
        resp = client_a.post(
            "/v1/workflows/",
            json=wf_def,
            headers=route_approval_headers(
                client_a,
                route_name="workflows.create",
                operation="create",
                arguments=wf_def,
                details="Pytest tenant workflow setup",
                authorization=f"Bearer {tenant_a_token}",
            ),
        )
        if resp.status_code == 409:
            # Already exists from prior test run -- proceed to execute
            pass
        elif resp.status_code != 201:
            pytest.skip(f"Cannot create workflow: {resp.status_code}")

        resp_exec = client_a.post(
            "/v1/workflows/e2e-tenant-wf/execute",
            json={"inputs": {}},
        )
        assert resp_exec.status_code == 200
        run_id = resp_exec.json()["run_id"]

        # Tenant B checks history -- should not see tenant A's run
        resp_hist = client_b.get("/v1/workflows/e2e-tenant-wf/history")
        assert resp_hist.status_code == 200
        b_run_ids = [h["run_id"] for h in resp_hist.json()]
        assert run_id not in b_run_ids
