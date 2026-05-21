import type { DomainConfig } from "../../types";

export const webhooksDomain: DomainConfig = {
  id: "webhooks",
  title: "Webhooks",
  description: "Inbound webhook adapters.",
  operations: [
    {
      id: "webhook-telegram",
      title: "Telegram Webhook",
      method: "POST",
      path: "/v1/webhooks/telegram",
      description: "Send Telegram webhook payload.",
      defaultBody: "{}"
    },
    {
      id: "webhook-discord",
      title: "Discord Webhook",
      method: "POST",
      path: "/v1/webhooks/discord",
      description: "Send Discord webhook payload.",
      defaultBody: "{}"
    },
    {
      id: "webhook-slack",
      title: "Slack Webhook",
      method: "POST",
      path: "/v1/webhooks/slack",
      description: "Send Slack webhook payload.",
      defaultBody: "{}"
    },
    {
      id: "webhook-whatsapp-get",
      title: "WhatsApp Webhook Verify",
      method: "GET",
      path: "/v1/webhooks/whatsapp",
      description: "Get verification response."
    },
    {
      id: "webhook-whatsapp-post",
      title: "WhatsApp Webhook Event",
      method: "POST",
      path: "/v1/webhooks/whatsapp",
      description: "Send WhatsApp webhook payload.",
      defaultBody: "{}"
    }
  ]
};
