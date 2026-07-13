"use client";

import { Files, PlusIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  useCreateProjectArtifact,
  useProjectArtifacts,
} from "@/core/artifacts/hooks-project";
import { useI18n } from "@/core/i18n/hooks";

const DEFAULT_PROJECT_ID = "default";

export default function ArtifactsPage() {
  const { t } = useI18n();
  const { artifacts, isLoading } = useProjectArtifacts(DEFAULT_PROJECT_ID);
  const { mutate: createArtifact } = useCreateProjectArtifact(DEFAULT_PROJECT_ID);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    createArtifact({
      name,
      description,
      type: "document",
    });
    setName("");
    setDescription("");
    setIsDialogOpen(false);
  };

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">Artifacts</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            Manage your project's versioned artifacts and files.
          </p>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <PlusIcon className="mr-1.5 h-4 w-4" />
              New Artifact
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Artifact</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <label htmlFor="name" className="text-sm font-medium text-foreground">Name</label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Project Plan"
                  required
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="description" className="text-sm font-medium text-foreground">Description</label>
                <Input
                  id="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Optional description"
                />
              </div>
              <Button type="submit" className="w-full">
                Create
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            {t.common.loading}
          </div>
        ) : artifacts.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
              <Files className="text-muted-foreground h-7 w-7" />
            </div>
            <div>
              <p className="font-medium">No Artifacts</p>
              <p className="text-muted-foreground mt-1 text-sm">
                Create an artifact to start tracking versioned content.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {artifacts.map((artifact) => (
              <div
                key={artifact.id}
                className="flex flex-col gap-3 rounded-xl border p-5 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-lg">{artifact.title || (artifact as any).name}</h3>
                  <span className="bg-muted text-muted-foreground rounded-md px-2 py-1 text-xs">
                    {artifact.language || (artifact as any).type}
                  </span>
                </div>
                {artifact.description && (
                  <p className="text-muted-foreground text-sm">
                    {artifact.description}
                  </p>
                )}
                <div className="text-muted-foreground mt-auto text-xs space-y-1">
                  <p>
                    <span className="font-medium text-foreground">Updated:</span>{" "}
                    {new Date(artifact.updated_at).toLocaleString()}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
