"use client";

import { Clock, PlusIcon } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import {
  useAutomations,
  useCreateAutomation,
  useToggleAutomation,
} from "@/core/automations/hooks";
import { useI18n } from "@/core/i18n/hooks";

const DEFAULT_PROJECT_ID = "default";

export default function AutomationsPage() {
  const { t } = useI18n();
  const { automations, isLoading } = useAutomations(DEFAULT_PROJECT_ID);
  const { mutate: createAutomation } = useCreateAutomation(DEFAULT_PROJECT_ID);
  const { mutate: toggleAutomation } = useToggleAutomation(DEFAULT_PROJECT_ID);

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [cronExpression, setCronExpression] = useState("*/5 * * * *");
  const [actionType, setActionType] = useState("spawn_thread");

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    createAutomation({
      name: name || "New Automation",
      trigger_type: "cron",
      trigger_config: { cron_expression: cronExpression },
      action_type: actionType,
      action_config: {},
      enabled: true,
    });
    setName("");
    setIsDialogOpen(false);
  };

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">Automations</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            Manage your background jobs and triggered workflows.
          </p>
        </div>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <PlusIcon className="mr-1.5 h-4 w-4" />
              New Automation
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Automation</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <label htmlFor="name" className="text-sm font-medium text-foreground">Name</label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Sync Contacts"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="cron" className="text-sm font-medium text-foreground">Cron Expression</label>
                <Input
                  id="cron"
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  placeholder="*/5 * * * *"
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="action" className="text-sm font-medium text-foreground">Action Type</label>
                <Input
                  id="action"
                  value={actionType}
                  onChange={(e) => setActionType(e.target.value)}
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
        ) : automations.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
              <Clock className="text-muted-foreground h-7 w-7" />
            </div>
            <div>
              <p className="font-medium">No Automations</p>
              <p className="text-muted-foreground mt-1 text-sm">
                Create an automation to run tasks in the background.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {automations.map((auto) => (
              <div
                key={auto.id}
                className="flex flex-col gap-4 rounded-xl border p-5 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">{auto.name || auto.action_type}</h3>
                  <Switch
                    checked={auto.enabled}
                    onCheckedChange={(checked) =>
                      toggleAutomation({
                        automationId: auto.id,
                        isEnabled: checked,
                      })
                    }
                  />
                </div>
                <div className="text-muted-foreground text-sm space-y-1">
                  <p>
                    <span className="font-medium text-foreground">Trigger:</span>{" "}
                    {auto.trigger_type} ({auto.trigger_config.cron_expression})
                  </p>
                  <p>
                    <span className="font-medium text-foreground">Created:</span>{" "}
                    {new Date(auto.created_at).toLocaleString()}
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
