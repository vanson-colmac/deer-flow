import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface ArtifactVersion {
  id: string;
  artifact_id: string;
  version_number: number;
  content: string;
  created_at: string;
  created_by: string;
}

export interface Artifact {
  id: string;
  project_id: string;
  title: string;
  description: string;
  language: string;
  current_version_id: string;
  created_at: string;
  updated_at: string;
}

export async function listProjectArtifacts(projectId: string): Promise<Artifact[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/projects/${projectId}/artifacts`, {
    method: "GET",
  });
  if (!res.ok) throw new Error("Failed to list artifacts");
  return res.json() as Promise<Artifact[]>;
}

export async function createProjectArtifact(
  projectId: string,
  request: { name: string; description?: string; type: string }
): Promise<Artifact> {
  const res = await fetch(`${getBackendBaseURL()}/api/projects/${projectId}/artifacts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error("Failed to create artifact");
  return res.json() as Promise<Artifact>;
}
