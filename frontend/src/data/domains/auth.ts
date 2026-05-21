import type { DomainConfig } from "../../types";

export const authDomain: DomainConfig = {
  id: "auth",
  title: "Auth",
  description: "Token and API key operations.",
  operations: [
    {
      id: "auth-token",
      title: "Login Token",
      method: "POST",
      path: "/v1/auth/token",
      description: "Exchange username/password for JWT.",
      instructionalText: "Generate an authentication token by providing your credentials. This token is required to authorize requests when communicating with the engine directly.",
      schemaInfo: {
        body: {
          description: "Requires the root administrator or predefined bootstrap username and password config.",
          example: '{\n  "username": "admin",\n  "password": "your-secure-password"\n}'
        }
      },
      defaultBody: JSON.stringify(
        {
          username: "admin",
          password: "admin"
        },
        null,
        2
      )
    },
    {
      id: "auth-create-api-key",
      title: "Create API Key",
      method: "POST",
      path: "/v1/auth/api-keys",
      description: "Generate a scoped API key after route approval.",
      instructionalText: "Create a long-lived API key for scripts or integrations. This route is now approval-token gated: the first call may create a pending approval, then you approve it in Safety Center and retry with a short-lived X-Agent33-Approval-Token header.",
      schemaInfo: {
        headers: [
          {
            name: "X-Agent33-Approval-Token",
            type: "string",
            description: "Short-lived approval token issued after approving the matching route mutation in Safety Center.",
            required: true
          }
        ],
        body: {
          description: "Requires auth scope plus a matching X-Agent33-Approval-Token header from an approved route-mutation request.",
          example: '{\n  "subject": "my-custom-service",\n  "scopes": ["agents:read", "workflows:execute"]\n}'
        }
      },
      defaultHeaders: {
        "X-Agent33-Approval-Token": ""
      },
      defaultBody: JSON.stringify(
        {
          subject: "agent-service",
          scopes: ["agents:read", "workflows:read"]
        },
        null,
        2
      )
    },
    {
      id: "auth-delete-api-key",
      title: "Delete API Key",
      method: "DELETE",
      path: "/v1/auth/api-keys/{key_id}",
      description: "Revoke an API key by ID.",
      instructionalText: "Permanently invalidate an existing API key, preventing any external applications from using it to access your engine.",
      schemaInfo: {
        parameters: [
          { name: "key_id", type: "string", description: "The precise unqiue identifier of the key to revoke.", required: true }
        ]
      },
      defaultPathParams: {
        key_id: "replace-with-key-id"
      }
    }
  ]
};
