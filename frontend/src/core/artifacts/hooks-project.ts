import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createProjectArtifact,
  listProjectArtifacts,
} from "./api-project";

export function useProjectArtifacts(projectId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => listProjectArtifacts(projectId),
    enabled: !!projectId,
  });
  return { artifacts: data ?? [], isLoading, error };
}

export function useCreateProjectArtifact(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: { name: string; description?: string; type: string }) =>
      createProjectArtifact(projectId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] });
    },
  });
}
