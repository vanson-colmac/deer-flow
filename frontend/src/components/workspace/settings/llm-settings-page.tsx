"use client";

import {
  BrainCircuitIcon,
  EditIcon,
  PlusIcon,
  TrashIcon,
  XIcon,
  ServerIcon,
  KeyIcon,
  GlobeIcon,
  SparklesIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import {
  createModel,
  deleteModel,
  loadModels,
  updateModel,
} from "@/core/models/api";
import type { ModelCreatePayload, ModelUpdatePayload } from "@/core/models/api";
import type { Model } from "@/core/models/types";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

export function LLMSettingsPage() {
  const { t } = useI18n();
  const [models, setModels] = useState<Model[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<Model | null>(null);
  const [deleteConfirmModel, setDeleteConfirmModel] = useState<Model | null>(
    null,
  );

  const fetchModels = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await loadModels();
      setModels(res.models);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchModels();
  }, [fetchModels]);

  const handleAdd = useCallback(() => {
    setEditingModel(null);
    setDialogOpen(true);
  }, []);

  const handleEdit = useCallback((model: Model) => {
    setEditingModel(model);
    setDialogOpen(true);
  }, []);

  const handleDeleteConfirm = useCallback(
    async (model: Model) => {
      try {
        await deleteModel(model.name);
        toast.success(t.settings.models.deleteSuccess);
        setDeleteConfirmModel(null);
        void fetchModels();
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : "Delete failed");
      }
    },
    [fetchModels, t],
  );

  const handleSaved = useCallback(() => {
    setDialogOpen(false);
    void fetchModels();
  }, [fetchModels]);

  return (
    <SettingsSection
      title={t.settings.models.title}
      description={t.settings.models.description}
    >
      <div className="mb-4 flex justify-end">
        <Button
          variant="default"
          size="sm"
          onClick={handleAdd}
          className="gap-1.5"
        >
          <PlusIcon className="size-4" />
          {t.settings.models.addModel}
        </Button>
      </div>

      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : models.length === 0 ? (
        <EmptyState
          title={t.settings.models.noModels}
          description={t.settings.models.noModelsDescription}
          onAdd={handleAdd}
          addLabel={t.settings.models.addModel}
        />
      ) : (
        <div className="flex w-full flex-col gap-3">
          {models.map((model) => (
            <ModelCard
              key={model.name}
              model={model}
              onEdit={() => handleEdit(model)}
              onDelete={() => setDeleteConfirmModel(model)}
              labels={{
                edit: t.settings.models.editModel,
                delete: t.settings.models.deleteModel,
              }}
            />
          ))}
        </div>
      )}

      {/* Add / Edit dialog */}
      <ModelFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        model={editingModel}
        onSaved={handleSaved}
        labels={t.settings.models}
      />

      {/* Delete confirmation */}
      <Dialog
        open={!!deleteConfirmModel}
        onOpenChange={(open) => !open && setDeleteConfirmModel(null)}
      >
        <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{t.settings.models.deleteModel}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            {t.settings.models.deleteConfirm}
          </p>
          {deleteConfirmModel && (
            <p className="text-sm font-medium">{deleteConfirmModel.name}</p>
          )}
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="ghost"
              onClick={() => setDeleteConfirmModel(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() =>
                deleteConfirmModel && handleDeleteConfirm(deleteConfirmModel)
              }
            >
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EmptyState({
  title,
  description,
  onAdd,
  addLabel,
}: {
  title: string;
  description: string;
  onAdd: () => void;
  addLabel: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-lg border border-dashed p-8 text-center">
      <BrainCircuitIcon className="text-muted-foreground size-10" />
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-muted-foreground text-xs">{description}</p>
      </div>
      <Button variant="outline" size="sm" onClick={onAdd} className="gap-1.5">
        <PlusIcon className="size-4" />
        {addLabel}
      </Button>
    </div>
  );
}

function ModelCard({
  model,
  onEdit,
  onDelete,
  labels,
}: {
  model: Model;
  onEdit: () => void;
  onDelete: () => void;
  labels: { edit: string; delete: string };
}) {
  const badges = useMemo(() => {
    const b: { icon: typeof SparklesIcon; label: string }[] = [];
    if (model.supports_thinking) b.push({ icon: SparklesIcon, label: "Thinking" });
    if (model.supports_reasoning_effort) b.push({ icon: ZapIcon, label: "Reasoning" });
    return b;
  }, [model.supports_thinking, model.supports_reasoning_effort]);

  return (
    <Item className="w-full" variant="outline">
      <ItemContent>
        <ItemTitle>
          <div className="flex items-center gap-2">
            <BrainCircuitIcon className="text-primary size-4" />
            <span>{model.display_name || model.name}</span>
          </div>
        </ItemTitle>
        <ItemDescription className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs">{model.model}</span>
          {badges.map((b) => (
            <span
              key={b.label}
              className="bg-primary/10 text-primary inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
            >
              <b.icon className="size-3" />
              {b.label}
            </span>
          ))}
        </ItemDescription>
      </ItemContent>
      <ItemActions>
        <button
          type="button"
          onClick={onEdit}
          className="text-muted-foreground hover:text-foreground transition-colors"
          title={labels.edit}
        >
          <EditIcon className="size-4" />
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="text-muted-foreground hover:text-destructive transition-colors"
          title={labels.delete}
        >
          <TrashIcon className="size-4" />
        </button>
      </ItemActions>
    </Item>
  );
}

// ---------------------------------------------------------------------------
// Form dialog
// ---------------------------------------------------------------------------

interface ModelFormLabels {
  addModel: string;
  editModel: string;
  fieldName: string;
  fieldNamePlaceholder: string;
  fieldModel: string;
  fieldModelPlaceholder: string;
  fieldDisplayName: string;
  fieldDisplayNamePlaceholder: string;
  fieldProvider: string;
  fieldProviderPlaceholder: string;
  fieldApiKey: string;
  fieldApiKeyPlaceholder: string;
  fieldBaseUrl: string;
  fieldBaseUrlPlaceholder: string;
  thinkingSupport: string;
  reasoningEffortSupport: string;
  createSuccess: string;
  updateSuccess: string;
}

function ModelFormDialog({
  open,
  onOpenChange,
  model,
  onSaved,
  labels,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  model: Model | null;
  onSaved: () => void;
  labels: ModelFormLabels;
}) {
  const isEdit = !!model;
  const [saving, setSaving] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("langchain_openai:ChatOpenAI");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [supportsThinking, setSupportsThinking] = useState(false);
  const [supportsReasoning, setSupportsReasoning] = useState(false);

  useEffect(() => {
    if (open) {
      if (model) {
        setName(model.name);
        setModelId(model.model);
        setDisplayName(model.display_name ?? "");
        setProvider(""); // not returned by API, leave empty for edits
        setApiKey("");
        setBaseUrl("");
        setSupportsThinking(model.supports_thinking ?? false);
        setSupportsReasoning(model.supports_reasoning_effort ?? false);
      } else {
        setName("");
        setModelId("");
        setDisplayName("");
        setProvider("langchain_openai:ChatOpenAI");
        setApiKey("");
        setBaseUrl("");
        setSupportsThinking(false);
        setSupportsReasoning(false);
      }
    }
  }, [open, model]);

  const handleSubmit = useCallback(async () => {
    if (!name.trim() || !modelId.trim()) return;
    setSaving(true);
    try {
      if (isEdit) {
        const payload: ModelUpdatePayload = {
          model: modelId,
          display_name: displayName || null,
          supports_thinking: supportsThinking,
          supports_reasoning_effort: supportsReasoning,
        };
        if (apiKey) payload.api_key = apiKey;
        if (baseUrl) payload.base_url = baseUrl;
        if (provider) payload.use = provider;
        await updateModel(model!.name, payload);
        toast.success(labels.updateSuccess);
      } else {
        const payload: ModelCreatePayload = {
          name: name.trim(),
          model: modelId.trim(),
          display_name: displayName || null,
          use: provider || "langchain_openai:ChatOpenAI",
          supports_thinking: supportsThinking,
          supports_reasoning_effort: supportsReasoning,
        };
        if (apiKey) payload.api_key = apiKey;
        if (baseUrl) payload.base_url = baseUrl;
        await createModel(payload);
        toast.success(labels.createSuccess);
      }
      onSaved();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [
    name,
    modelId,
    displayName,
    provider,
    apiKey,
    baseUrl,
    supportsThinking,
    supportsReasoning,
    isEdit,
    model,
    labels,
    onSaved,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrainCircuitIcon className="size-5" />
            {isEdit ? labels.editModel : labels.addModel}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Name */}
          <FormField
            icon={<ServerIcon className="size-4" />}
            label={labels.fieldName}
          >
            <Input
              id="model-name"
              value={name}
              disabled={isEdit}
              onChange={(e) => setName(e.target.value)}
              placeholder={labels.fieldNamePlaceholder}
            />
          </FormField>

          {/* Model ID */}
          <FormField
            icon={<BrainCircuitIcon className="size-4" />}
            label={labels.fieldModel}
          >
            <Input
              id="model-id"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder={labels.fieldModelPlaceholder}
            />
          </FormField>

          {/* Display name */}
          <FormField
            icon={<EditIcon className="size-4" />}
            label={labels.fieldDisplayName}
          >
            <Input
              id="model-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={labels.fieldDisplayNamePlaceholder}
            />
          </FormField>

          {/* Provider class */}
          <FormField
            icon={<ServerIcon className="size-4" />}
            label={labels.fieldProvider}
          >
            <Input
              id="model-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              placeholder={labels.fieldProviderPlaceholder}
            />
          </FormField>

          {/* API key */}
          <FormField
            icon={<KeyIcon className="size-4" />}
            label={labels.fieldApiKey}
          >
            <Input
              id="model-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={labels.fieldApiKeyPlaceholder}
            />
          </FormField>

          {/* Base URL */}
          <FormField
            icon={<GlobeIcon className="size-4" />}
            label={labels.fieldBaseUrl}
          >
            <Input
              id="model-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={labels.fieldBaseUrlPlaceholder}
            />
          </FormField>

          {/* Toggles */}
          <div className="flex flex-col gap-3 rounded-lg border p-3">
            <ToggleRow
              label={labels.thinkingSupport}
              icon={<SparklesIcon className="size-4" />}
              checked={supportsThinking}
              onChange={setSupportsThinking}
            />
            <ToggleRow
              label={labels.reasoningEffortSupport}
              icon={<ZapIcon className="size-4" />}
              checked={supportsReasoning}
              onChange={setSupportsReasoning}
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            <XIcon className="mr-1 size-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={saving || !name.trim() || !modelId.trim()}
          >
            {saving ? "Saving..." : isEdit ? "Update" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FormField({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
        {icon}
        {label}
      </label>
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  icon,
  checked,
  onChange,
}: {
  label: string;
  icon: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-sm">
        {icon}
        {label}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
