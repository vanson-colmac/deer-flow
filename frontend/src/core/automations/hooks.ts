import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createAutomation,
  listAutomations,
  toggleAutomation,
  type CreateAutomationRequest,
} from "./api";

export function useAutomations(projectId: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["automations", projectId],
    queryFn: () => listAutomations(projectId),
    enabled: !!projectId,
  });
  return { automations: data ?? [], isLoading, error };
}

export function useCreateAutomation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAutomationRequest) =>
      createAutomation(projectId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations", projectId] });
    },
  });
}

export function useToggleAutomation(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      automationId,
      isEnabled,
    }: {
      automationId: string;
      isEnabled: boolean;
    }) => toggleAutomation(projectId, automationId, isEnabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["automations", projectId] });
    },
  });
}
