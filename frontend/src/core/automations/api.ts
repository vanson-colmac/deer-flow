import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface Automation {
  id: string;
  project_id: string;
  name: string;
  trigger_type: string;
  trigger_config: Record<string, any>;
  action_type: string;
  action_config: Record<string, any>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateAutomationRequest {
  name: string;
  trigger_type: string;
  trigger_config: Record<string, any>;
  action_type: string;
  action_config: Record<string, any>;
  enabled?: boolean;
}


export async function listAutomations(projectId: string): Promise<Automation[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/projects/${projectId}/automations`, {
    method: "GET",
  });
  if (!res.ok) throw new Error("Failed to fetch automations");
  return res.json() as Promise<Automation[]>;
}

export async function createAutomation(
  projectId: string,
  request: CreateAutomationRequest
): Promise<Automation> {
  const res = await fetch(`${getBackendBaseURL()}/api/projects/${projectId}/automations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error("Failed to create automation");
  return res.json() as Promise<Automation>;
}

export async function toggleAutomation(
  projectId: string,
  automationId: string,
  isEnabled: boolean
): Promise<Automation> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/projects/${projectId}/automations/${automationId}/toggle`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: isEnabled }),
    }
  );
  if (!res.ok) throw new Error("Failed to toggle automation");
  return res.json() as Promise<Automation>;
}
