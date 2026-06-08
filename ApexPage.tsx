import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Brain,
  Clock3, FileDown, FileText,
  MessageCircle,
  Radar,
  RefreshCw,
  Search,
  ShieldAlert, ShieldCheck,
  Sparkles,
  Trash2,
  Users,
  WandSparkles,
  Zap,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { ApexAuditLogEntry, ApexEvent, ApexSummaryResponse, ApexDashboardConfig, ApexQuotaPreviewResponse, ApexAlert, ApexPromptContext, ApexRecoveryAction, ApexSegmentRecommendation, ApexSegmentUser, ApexTimelineEntry, ApexUser } from "@/lib/api";
import { cn } from "@/lib/utils";

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value || 0);
}

function formatDate(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function identityTitle(user?: ApexUser | null): string {
  if (!user) return "—";
  return user.display_name || user.sender_name || user.chat_name || user.phone_number || user.chat_id;
}

function identityConfidenceLabel(user?: ApexUser | null): string {
  const confidence = user?.identity_confidence;
  if (!confidence) return "Unknown identity";
  return `${confidence.label} · ${confidence.score}/100 · ${confidence.source}`;
}

function identitySubtitle(user?: ApexUser | null): string {
  if (!user) return "—";
  return user.phone_number || user.sender_phone || user.chat_phone || user.sender_id || user.chat_id;
}

function getMemoryHealth(user?: ApexUser | null) {
  if (!user) return { score: 0, label: "No user", tone: "amber" as const, reasons: ["Select a user"] };
  const reasons: string[] = [];
  let score = 100;
  if (!user.stable_memory?.trim()) {
    score -= 25;
    reasons.push("Missing stable memory");
  }
  if (!user.conversation_summary?.trim()) {
    score -= 25;
    reasons.push("Missing continuity summary");
  }
  if (!user.last_user_message?.trim()) {
    score -= 20;
    reasons.push("No latest user message captured");
  }
  if (!user.last_agent_reply?.trim()) {
    score -= 20;
    reasons.push("No latest agent reply captured");
  }
  if ((user.menu_request_count ?? 0) > (user.mode_switch_count ?? 0) + 2) {
    score -= 10;
    reasons.push("Menu requests are outpacing mode selection");
  }
  if (score >= 85) return { score, label: "Healthy", tone: "green" as const, reasons: reasons.length ? reasons : ["Continuity fields look complete"] };
  if (score >= 60) return { score, label: "Watch", tone: "amber" as const, reasons };
  return { score, label: "Weak", tone: "red" as const, reasons };
}

function eventTone(eventType: string) {
  if (eventType === "mode_switch") return "border-sky-500/30 bg-sky-500/10 text-sky-200";
  if (eventType === "menu") return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  if (eventType === "outbound") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
  return "border-primary/30 bg-primary/10 text-primary";
}

function titleCaseEvent(eventType: string) {
  return eventType.replace(/_/g, " ").replace(/\w/g, (c) => c.toUpperCase());
}

function StatCard({ label, value, hint, icon: Icon, tone = "default" }: {
  label: string;
  value: string | number;
  hint: string;
  icon: typeof Activity;
  tone?: "default" | "green" | "amber" | "blue" | "red";
}) {
  return (
    <Card className="overflow-hidden border-border/70 bg-card/70">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">{label}</div>
            <div className="mt-2 text-3xl font-semibold tracking-tight text-foreground">{value}</div>
            <div className="mt-1 text-sm text-muted-foreground normal-case">{hint}</div>
          </div>
          <div
            className={cn(
              "rounded-2xl border p-3",
              tone === "green" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
              tone === "amber" && "border-amber-500/30 bg-amber-500/10 text-amber-300",
              tone === "blue" && "border-sky-500/30 bg-sky-500/10 text-sky-300",
              tone === "red" && "border-rose-500/30 bg-rose-500/10 text-rose-300",
              tone === "default" && "border-primary/20 bg-primary/10 text-primary",
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ModeSplit({ general, upsc }: { general: number; upsc: number }) {
  const total = Math.max(general + upsc, 1);
  const generalPct = Math.round((general / total) * 100);
  const upscPct = Math.round((upsc / total) * 100);
  return (
    <Card className="border-border/70 bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Brain className="h-5 w-5 text-primary" />
          Mode split
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="h-3 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary" style={{ width: `${generalPct}%` }} />
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm normal-case">
          <div className="rounded-xl border border-border/70 bg-background/40 p-3">
            <div className="text-muted-foreground">General AI</div>
            <div className="mt-1 text-xl font-semibold">{generalPct}%</div>
            <div className="text-xs text-muted-foreground">{formatNumber(general)} users</div>
          </div>
          <div className="rounded-xl border border-border/70 bg-background/40 p-3">
            <div className="text-muted-foreground">UPSC Mentor</div>
            <div className="mt-1 text-xl font-semibold">{upscPct}%</div>
            <div className="text-xs text-muted-foreground">{formatNumber(upsc)} users</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function UserRow({ user, active, onSelect }: { user: ApexUser; active: boolean; onSelect: (user: ApexUser) => void }) {
  const health = getMemoryHealth(user);
  return (
    <button
      type="button"
      onClick={() => onSelect(user)}
      className={cn(
        "grid w-full gap-3 rounded-2xl border p-4 text-left transition md:grid-cols-[1.2fr_0.55fr_0.55fr_1.1fr_0.65fr] md:items-center",
        active
          ? "border-primary/40 bg-primary/10"
          : "border-border/60 bg-background/35 hover:border-primary/25 hover:bg-background/55",
      )}
    >
      <div className="min-w-0 normal-case">
        <div className="truncate font-medium text-foreground">{identityTitle(user)}</div>
        <div className="mt-1 truncate text-xs text-muted-foreground">{identitySubtitle(user)}</div>
        <div className="mt-1 truncate text-[11px] text-muted-foreground">{user.chat_id}</div>
      </div>
      <div>
        <Badge>{user.current_mode || "general"}</Badge>
        <div className="mt-1 text-xs text-muted-foreground">{identityConfidenceLabel(user)}</div>
      </div>
      <div className="text-sm normal-case">
        <div className="font-medium">{formatNumber(user.message_count ?? 0)}</div>
        <div className="text-xs text-muted-foreground">messages</div>
      </div>
      <div className="min-w-0 text-sm text-muted-foreground normal-case">
        <div className="truncate">{user.stable_memory || "No stable memory yet"}</div>
        <div className="mt-1 truncate text-xs">{user.last_user_message || "No recent message"}</div>
      </div>
      <div className="text-sm normal-case">
        <div className={cn(
          "inline-flex rounded-full border px-2 py-1 text-xs font-medium",
          health.tone === "green" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
          health.tone === "amber" && "border-amber-500/30 bg-amber-500/10 text-amber-200",
          health.tone === "red" && "border-rose-500/30 bg-rose-500/10 text-rose-200",
        )}>
          {health.label}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">{health.score}/100</div>
      </div>
    </button>
  );
}

function DetailField({ label, value }: { label: string; value?: string | number }) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/40 p-3">
      <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="mt-2 whitespace-pre-wrap break-words text-sm text-foreground normal-case">{value || "—"}</div>
    </div>
  );
}

function EventRow({ event, onPickUser }: { event: ApexEvent; onPickUser: (chatId: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onPickUser(event.chat_id)}
      className="w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/25 hover:bg-background/55"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 truncate text-sm font-medium">{event.chat_id}</div>
        <div className={cn("rounded-full border px-2 py-1 text-xs font-medium", eventTone(event.event_type))}>
          {titleCaseEvent(event.event_type)}
        </div>
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <Clock3 className="h-3.5 w-3.5" />
        {formatDate(event.created_at)}
      </div>
      <div className="mt-2 text-xs text-muted-foreground normal-case">
        Mode: {event.mode || "general"} • Units: {event.units}
      </div>
      {event.metadata ? <div className="mt-2 truncate text-xs text-muted-foreground normal-case">{event.metadata}</div> : null}
    </button>
  );
}

export default function ApexPage() {
  const [data, setData] = useState<ApexSummaryResponse | null>(null);
  const [users, setUsers] = useState<ApexUser[]>([]);
  const [auditLog, setAuditLog] = useState<ApexAuditLogEntry[]>([]);
  const [timeline, setTimeline] = useState<ApexTimelineEntry[]>([]);
  const [simulatedContext, setSimulatedContext] = useState<ApexPromptContext | null>(null);
  const [alerts, setAlerts] = useState<ApexAlert[]>([]);
  const [alertCounts, setAlertCounts] = useState({ critical: 0, warning: 0, info: 0 });
  const [segments, setSegments] = useState<{ new_users: ApexSegmentUser[]; dormant_users: ApexSegmentUser[]; frequent_switchers: ApexSegmentUser[]; menu_loop_users: ApexSegmentUser[]; power_users: ApexSegmentUser[] }>({ new_users: [], dormant_users: [], frequent_switchers: [], menu_loop_users: [], power_users: [] });
  const [segmentCounts, setSegmentCounts] = useState({ new_users: 0, dormant_users: 0, frequent_switchers: 0, menu_loop_users: 0, power_users: 0, upsc_heavy: 0, general_heavy: 0, retained_1d: 0, retained_7d: 0, retained_30d: 0 });
  const [segmentRecommendations, setSegmentRecommendations] = useState<ApexSegmentRecommendation[]>([]);
  const [exportPreview, setExportPreview] = useState<string>("");
  const [exportLoading, setExportLoading] = useState<string | null>(null);
  const [exportFilename, setExportFilename] = useState<string>("");
  const [apexConfig, setApexConfig] = useState<ApexDashboardConfig | null>(null);
  const [quotaPreview, setQuotaPreview] = useState<ApexQuotaPreviewResponse | null>(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<string>("");
  const [showQRModal, setShowQRModal] = useState(false);
  const [qrData, setQrData] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadUsers = useCallback(async (nextQuery = "") => {
    setUsersLoading(true);
    try {
      const result = await api.getApexUsers({ q: nextQuery, limit: 100 });
      setUsers(result.users);
      setSelectedChatId((current) => {
        if (current && result.users.some((user) => user.chat_id === current)) return current;
        return result.users[0]?.chat_id || "";
      });
    } finally {
      setUsersLoading(false);
    }
  }, []);

  const loadSegments = useCallback(async () => {
    try {
      const result = await api.getApexSegments();
      setSegments(result.segments);
      setSegmentCounts(result.counts);
      setSegmentRecommendations(result.recommendations);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const result = await api.getApexAlerts();
      setAlerts(result.alerts);
      setAlertCounts(result.counts);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadContextSimulation = useCallback(async (chatId?: string) => {
    if (!chatId) {
      setSimulatedContext(null);
      return;
    }
    try {
      const result = await api.simulateApexContext({ chat_id: chatId });
      setSimulatedContext(result.context);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadTimeline = useCallback(async (chatId?: string) => {
    try {
      const result = await api.getApexTimeline(chatId, 100);
      setTimeline(result.timeline);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadAuditLog = useCallback(async (chatId?: string) => {
    try {
      const result = await api.getApexAuditLog(chatId, 20);
      setAuditLog(result.audit_log);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const loadConfigAndQuota = useCallback(async () => {
    try {
      const [configResult, quotaResult] = await Promise.all([api.getApexConfig(), api.getApexQuotaPreview()]);
      setApexConfig(configResult.config);
      setQuotaPreview(quotaResult);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const updateApexConfig = useCallback(<K extends keyof ApexDashboardConfig>(key: K, value: ApexDashboardConfig[K]) => {
    setApexConfig((current) => current ? { ...current, [key]: value } : current);
  }, []);

  const saveApexConfig = useCallback(async () => {
    if (!apexConfig || configSaving) return;
    setConfigSaving(true);
    setActionMessage(null);
    try {
      const result = await api.saveApexConfig(apexConfig);
      setApexConfig(result.config);
      setQuotaPreview(await api.getApexQuotaPreview());
      setActionMessage("Apex runtime controls saved.");
    } catch (e) {
      setError(String(e));
    } finally {
      setConfigSaving(false);
    }
  }, [apexConfig, configSaving]);

  const load = useCallback(async () => {
    setError(null);
    setActionMessage(null);
    try {
      const [summary] = await Promise.all([api.getApexSummary(), loadUsers(query), loadConfigAndQuota()]);
      setData(summary);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [loadConfigAndQuota, loadUsers, query]);

  
  useEffect(() => {
    let interval: any;
    if (showQRModal) {
      interval = setInterval(async () => {
        try {
          const res = await fetch("/api/apex/whatsapp-qr", {
            headers: { "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ || "" }
          });
          const data = await res.json();
          if (data.qr === "connected") {
            setShowQRModal(false);
          } else if (data.qr) {
            setQrData(data.qr);
          }
        } catch (e) {}
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [showQRModal]);

  const handleRelogin = async () => {
    setQrData("");
    setShowQRModal(true);
    await fetch("/api/apex/whatsapp-relogin", {
      method: "POST",
      headers: { "X-Hermes-Session-Token": window.__HERMES_SESSION_TOKEN__ || "" }
    }).catch(console.error);
  };

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadAuditLog(selectedChatId || undefined);
    void loadTimeline(selectedChatId || undefined);
    void loadAlerts();
    void loadSegments();
    void loadContextSimulation(selectedChatId || undefined);
  }, [loadAlerts, loadAuditLog, loadContextSimulation, loadSegments, loadTimeline, selectedChatId]);

  const overview = data?.overview;
  const recentModeSwitches = useMemo(
    () => data?.recent_events.filter((event) => event.event_type === "mode_switch").slice(0, 6) ?? [],
    [data],
  );
  const selectedUser = useMemo(
    () => users.find((user) => user.chat_id === selectedChatId) ?? data?.recent_users.find((user) => user.chat_id === selectedChatId) ?? users[0],
    [data?.recent_users, selectedChatId, users],
  );
  const selectedHealth = useMemo(() => getMemoryHealth(selectedUser), [selectedUser]);
  const usersByChatId = useMemo(
    () => new Map(users.map((user) => [user.chat_id, user])),
    [users],
  );
  const recentUsers = useMemo(
    () => data?.recent_users.map((user) => usersByChatId.get(user.chat_id) ?? user) ?? [],
    [data?.recent_users, usersByChatId],
  );
  const usersNeedingAttention = useMemo(
    () => users.filter((user) => getMemoryHealth(user).score < 85),
    [users],
  );
  const menuHeavyUsers = useMemo(
    () => users.filter((user) => (user.menu_request_count ?? 0) > Math.max(1, (user.mode_switch_count ?? 0) + 1)),
    [users],
  );
  const modeSwitchLeaders = useMemo(
    () => [...users].sort((a, b) => (b.mode_switch_count ?? 0) - (a.mode_switch_count ?? 0)).slice(0, 5),
    [users],
  );

  const handleExportPreview = useCallback(async (kind: "users" | "usage" | "identity" | "memory" | "operator") => {
    setExportLoading(kind);
    try {
      let payload: unknown;
      let filename = "";
      if (kind === "users") {
        payload = (await api.getApexExportUsers()).export;
        filename = "apex-users-export.json";
      } else if (kind === "usage") {
        payload = await api.getApexExportUsageSummary();
        filename = "apex-usage-summary.json";
      } else if (kind === "identity") {
        payload = (await api.getApexExportIdentityCoverage()).export;
        filename = "apex-identity-coverage.json";
      } else if (kind === "memory") {
        payload = (await api.getApexExportMemoryHealth()).export;
        filename = "apex-memory-health.json";
      } else {
        payload = (await api.getApexExportOperatorSummary()).export;
        filename = "apex-operator-summary.json";
      }
      setExportFilename(filename);
      setExportPreview(JSON.stringify(payload, null, 2));
    } catch (e) {
      setError(String(e));
    } finally {
      setExportLoading(null);
    }
  }, []);

  const handleDownloadExport = useCallback(() => {
    if (!exportPreview.trim()) return;
    const blob = new Blob([exportPreview], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportFilename || "apex-export.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }, [exportFilename, exportPreview]);

  const handleSearch = useCallback(async () => {
    setActionMessage(null);
    try {
      await loadUsers(query.trim());
    } catch (e) {
      setError(String(e));
    }
  }, [loadUsers, query]);

  const handleClearMemory = useCallback(async () => {
    if (!selectedUser || clearing) return;
    const confirmed = window.confirm(`Clear continuity memory for ${selectedUser.chat_id}? This keeps the user row but wipes recent memory fields.`);
    if (!confirmed) return;
    setClearing(true);
    setActionMessage(null);
    try {
      await api.clearApexUserMemory(selectedUser.chat_id);
      setActionMessage(`Cleared continuity memory for ${selectedUser.chat_id}.`);
      await Promise.all([loadUsers(query.trim()), load(), loadAuditLog(selectedUser.chat_id)]);
    } catch (e) {
      setError(String(e));
    } finally {
      setClearing(false);
    }
  }, [clearing, load, loadAuditLog, loadUsers, query, selectedUser]);

  const recoveryActions = useMemo<Record<ApexRecoveryAction, { label: string; pending: string; confirm: string; group: "sync" | "memory" | "mode" | "reset" }>>(() => ({
    refresh_identity: {
      label: "Refresh identity",
      pending: "Refreshing",
      confirm: "Refresh identity metadata for this user only. This updates mapped WhatsApp identity fields from available session data.",
      group: "sync",
    },
    resend_menu: {
      label: "Resend onboarding/menu",
      pending: "Sending",
      confirm: "Send the current Apex onboarding or returning menu to this user only. No stored memory fields are cleared.",
      group: "sync",
    },
    force_mode_sync: {
      label: "Force mode sync",
      pending: "Syncing",
      confirm: "Re-save the current mode onto this user row and mark the user onboarded. This only affects this selected user.",
      group: "sync",
    },
    rebuild_summary: {
      label: "Rebuild summary",
      pending: "Rebuilding",
      confirm: "Recompute the conversation summary for this user from the currently stored continuity fields. Stable memory is not cleared.",
      group: "memory",
    },
    clear_continuity: {
      label: "Clear continuity only",
      pending: "Clearing",
      confirm: "Clear last user message, last agent reply, conversation summary, and last interaction time for this user only. Stable memory stays intact.",
      group: "memory",
    },
    clear_stable_memory: {
      label: "Clear stable memory only",
      pending: "Clearing",
      confirm: "Clear stable memory for this user only. Continuity fields and mode state stay intact.",
      group: "memory",
    },
    set_mode_general: {
      label: "Set mode: General AI",
      pending: "Switching",
      confirm: "Switch this user to General AI mode and mark the user onboarded. This increments the user-scoped mode switch counter.",
      group: "mode",
    },
    set_mode_upsc: {
      label: "Set mode: UPSC Mentor",
      pending: "Switching",
      confirm: "Switch this user to UPSC Mentor mode and mark the user onboarded. This increments the user-scoped mode switch counter.",
      group: "mode",
    },
    restore_default_mode: {
      label: "Restore default mode",
      pending: "Restoring",
      confirm: "Set this user back to the dashboard-configured default Apex mode and mark the user onboarded. This affects this user only.",
      group: "mode",
    },
    clear_onboarding: {
      label: "Reset onboarding",
      pending: "Resetting",
      confirm: "Mark this user as not onboarded so the onboarding flow can run again. Memory and identity fields stay intact.",
      group: "reset",
    },
    reset_user_scoped: {
      label: "Reset selected user state",
      pending: "Resetting",
      confirm: "Reset onboarding, mode, continuity, stable memory, and per-user menu/mode counters for this selected user only. This does not delete the user row.",
      group: "reset",
    },
    backfill_identities: {
      label: "Backfill identities",
      pending: "Backfilling",
      confirm: "Backfill identity data from available session mappings. This is a global action and should not be triggered from the per-user shelf.",
      group: "sync",
    },
  }), []);

  const handleRecoveryAction = useCallback(async (action: ApexRecoveryAction) => {
    if (!selectedUser || actionLoading) return;
    const definition = recoveryActions[action];
    if (!definition || action === "backfill_identities") return;
    const confirmed = window.confirm(`${definition.label} for ${selectedUser.chat_id}? ${definition.confirm}`);
    if (!confirmed) return;
    setActionLoading(action);
    setActionMessage(null);
    try {
      await api.runApexRecoveryAction(selectedUser.chat_id, action);
      setActionMessage(`${definition.label} completed for ${selectedUser.chat_id}.`);
      await Promise.all([
        loadUsers(query.trim()),
        load(),
        loadAuditLog(selectedUser.chat_id),
        loadTimeline(selectedUser.chat_id),
        loadContextSimulation(selectedUser.chat_id),
      ]);
    } catch (e) {
      setError(String(e));
    } finally {
      setActionLoading(null);
    }
  }, [actionLoading, load, loadAuditLog, loadContextSimulation, loadTimeline, loadUsers, query, recoveryActions, selectedUser]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    );
  }

  if (error || !overview) {
    return (
      <div className="rounded-2xl border border-destructive/30 bg-destructive/10 p-6 normal-case text-destructive">
        Apex dashboard failed to load: {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 normal-case">
      <section className="relative overflow-hidden rounded-3xl border border-border/70 bg-gradient-to-br from-primary/15 via-card to-background p-6 shadow-sm">
        <div className="absolute right-0 top-0 h-48 w-48 rounded-full bg-primary/20 blur-3xl" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              Apex command center
            </div>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground md:text-4xl">WhatsApp AI operations</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Live visibility for Apex users, sticky modes, continuity memory, and gateway usage without opening the terminal.
            </p>
          </div>
          <Button onClick={load} size="sm">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        </div>
      </section>

      {actionMessage ? (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
          {actionMessage}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-3">
        <StatCard label="Active alerts" value={formatNumber(overview.active_alerts ?? alerts.length)} hint={`${alertCounts.critical} critical · ${alertCounts.warning} warning · ${alertCounts.info} info`} icon={AlertTriangle} tone={alertCounts.critical ? "red" : alertCounts.warning ? "amber" : "green"} />
        <StatCard label="Critical alerts" value={formatNumber(alertCounts.critical)} hint="Immediate operator attention" icon={ShieldAlert} tone={alertCounts.critical ? "red" : "green"} />
        <StatCard label="Warning alerts" value={formatNumber(alertCounts.warning)} hint="Behavior drift and health issues" icon={Radar} tone={alertCounts.warning ? "amber" : "green"} />
      </div>

      <div className="rounded-3xl border border-border/70 bg-card/70 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-foreground">Alert strip</div>
            <div className="text-xs text-muted-foreground">Silent failures, churn, thrash, and memory-risk signals.</div>
          </div>
        </div>
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          {alerts.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border p-6 text-sm text-muted-foreground">No active Apex alerts.</div>
          ) : (
            alerts.slice(0, 8).map((alert) => (
              <button
                key={alert.id}
                type="button"
                onClick={() => alert.chat_id && setSelectedChatId(alert.chat_id)}
                className="rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/40 hover:bg-background/55"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium text-foreground">{alert.title}</div>
                  <Badge>{alert.severity}</Badge>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{alert.chat_id || alert.kind}</div>
                <div className="mt-2 text-sm text-muted-foreground">{alert.detail}</div>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="New users" value={formatNumber(segmentCounts.new_users)} hint="First seen within 48h" icon={Zap} tone={segmentCounts.new_users ? "blue" : "green"} />
        <StatCard label="Dormant users" value={formatNumber(segmentCounts.dormant_users)} hint="Inactive for 7+ days" icon={Clock3} tone={segmentCounts.dormant_users ? "amber" : "green"} />
        <StatCard label="Power users" value={formatNumber(segmentCounts.power_users)} hint="15+ messages tracked" icon={Users} tone={segmentCounts.power_users ? "blue" : "green"} />
        <StatCard label="Recommendations" value={formatNumber(overview.segment_recommendations ?? segmentRecommendations.length)} hint="Operator suggestions from behavior" icon={WandSparkles} tone={segmentRecommendations.length ? "amber" : "green"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-5 w-5 text-primary" />
              Segmentation board
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[
              { label: "New users", items: segments.new_users },
              { label: "Dormant users", items: segments.dormant_users },
              { label: "Frequent switchers", items: segments.frequent_switchers },
              { label: "Menu-loop users", items: segments.menu_loop_users },
              { label: "Power users", items: segments.power_users },
            ].map(({ label, items }) => (
              <div key={label} className="rounded-2xl border border-border/60 bg-background/35 p-4">
                <div className="text-sm font-medium text-foreground">{label}</div>
                <div className="mt-3 space-y-2">
                  {items.length === 0 ? (
                    <div className="text-xs text-muted-foreground">None in this cohort.</div>
                  ) : (
                    items.slice(0, 4).map((item) => (
                      <button key={`${label}-${item.chat_id}`} type="button" onClick={() => setSelectedChatId(item.chat_id)} className="block w-full rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-left">
                        <div className="truncate text-sm font-medium text-foreground">{item.chat_id}</div>
                        <div className="mt-1 text-xs text-muted-foreground">mode {item.mode} · msgs {item.message_count} · memory {item.memory_score}</div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <WandSparkles className="h-5 w-5 text-primary" />
              Recommendations
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {segmentRecommendations.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-sm text-muted-foreground">No segment-based recommendations right now.</div>
            ) : (
              segmentRecommendations.slice(0, 8).map((item) => (
                <button key={`${item.chat_id}-${item.title}`} type="button" onClick={() => setSelectedChatId(item.chat_id)} className="block w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left">
                  <div className="text-sm font-medium text-foreground">{item.title}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{item.chat_id}</div>
                  <div className="mt-2 text-sm text-muted-foreground">{item.detail}</div>
                </button>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Export reports" value={formatNumber(overview.exportable_reports ?? 5)} hint="Users, usage, identity, memory, operator" icon={FileDown} tone="blue" />
        <StatCard label="Identity reports" value={formatNumber(overview.identity_mapped_users ?? 0)} hint="Coverage export ready" icon={ShieldCheck} tone="green" />
        <StatCard label="Memory reports" value={formatNumber(users.filter((user) => (user.memory_qa?.score ?? 0) >= 0).length)} hint="Memory health export ready" icon={Brain} tone="blue" />
        <StatCard label="Usage reports" value={formatNumber(overview.total_users ?? 0)} hint="Compact privacy-aware summary" icon={BarChart3} tone="blue" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileDown className="h-5 w-5 text-primary" />
              Operator reports
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              <button type="button" onClick={() => void handleExportPreview("users")} disabled={exportLoading !== null} className="rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/40 hover:bg-background/55 disabled:cursor-not-allowed disabled:opacity-60">
                <div className="text-sm font-medium text-foreground">Users export</div>
                <div className="mt-1 text-xs text-muted-foreground">Compact per-user report without transcript payloads.</div>
              </button>
              <button type="button" onClick={() => void handleExportPreview("usage")} disabled={exportLoading !== null} className="rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/40 hover:bg-background/55 disabled:cursor-not-allowed disabled:opacity-60">
                <div className="text-sm font-medium text-foreground">Usage summary</div>
                <div className="mt-1 text-xs text-muted-foreground">Traffic, menu, switch, alert, and recommendation totals.</div>
              </button>
              <button type="button" onClick={() => void handleExportPreview("identity")} disabled={exportLoading !== null} className="rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/40 hover:bg-background/55 disabled:cursor-not-allowed disabled:opacity-60">
                <div className="text-sm font-medium text-foreground">Identity coverage</div>
                <div className="mt-1 text-xs text-muted-foreground">Mapping coverage, high-confidence counts, and refresh gaps.</div>
              </button>
              <button type="button" onClick={() => void handleExportPreview("memory")} disabled={exportLoading !== null} className="rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/40 hover:bg-background/55 disabled:cursor-not-allowed disabled:opacity-60">
                <div className="text-sm font-medium text-foreground">Memory health</div>
                <div className="mt-1 text-xs text-muted-foreground">Continuity quality buckets for operator review.</div>
              </button>
              <button type="button" onClick={() => void handleExportPreview("operator")} disabled={exportLoading !== null} className="rounded-2xl border border-primary/30 bg-primary/5 p-4 text-left transition hover:border-primary/50 hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60 sm:col-span-2 xl:col-span-1 2xl:col-span-2">
                <div className="text-sm font-medium text-foreground">Operator summary</div>
                <div className="mt-1 text-xs text-muted-foreground">One compact leadership-ready report with usage, identity, memory, segments, alerts, and capped recommendations.</div>
              </button>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/35 p-4 text-sm text-muted-foreground">
              Exports stay compact and privacy-aware. No raw transcript history, last user message, last agent reply, or full timeline payload is included.
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-5 w-5 text-primary" />
                Export preview
              </CardTitle>
              <Button onClick={handleDownloadExport} disabled={!exportPreview.trim() || exportLoading !== null} size="sm">Download JSON</Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-2xl border border-border/60 bg-background/35 px-4 py-3 text-xs text-muted-foreground">
              {exportFilename || "Choose a report to generate a local browser download."}
            </div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-2xl border border-border/60 bg-background/35 p-4 text-xs text-muted-foreground">{exportPreview || "Choose an export to preview the server-generated report payload."}</pre>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total users" value={formatNumber(overview.total_users ?? 0)} hint="All persisted WhatsApp users" icon={Users} tone="blue" />
        <StatCard label="Active users" value={formatNumber(overview.active_users ?? 0)} hint="Users with interaction memory" icon={Activity} tone="green" />
        <StatCard label="New today" value={formatNumber(overview.new_users_today ?? 0)} hint="First seen today" icon={Zap} tone="amber" />
        <StatCard label="7d traffic" value={formatNumber((overview.inbound_events_7d ?? 0) + (overview.outbound_events_7d ?? 0))} hint="Inbound + outbound ledger events" icon={MessageCircle} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Memory watchlist" value={formatNumber(usersNeedingAttention.length)} hint="Users needing continuity QA" icon={AlertTriangle} tone={usersNeedingAttention.length ? "amber" : "green"} />
        <StatCard label="Menu-heavy users" value={formatNumber(menuHeavyUsers.length)} hint="Users reopening menu without settling" icon={Radar} tone={menuHeavyUsers.length ? "amber" : "green"} />
        <StatCard label="Top switcher count" value={formatNumber(modeSwitchLeaders[0]?.mode_switch_count || 0)} hint="Highest mode-switch activity" icon={WandSparkles} tone="blue" />
        <StatCard label="Identity coverage" value={formatNumber(overview.identity_mapped_users ?? 0)} hint={`${formatNumber(overview.identity_high_confidence ?? 0)} high confidence, ${formatNumber(overview.identity_refresh_needed ?? 0)} need refresh`} icon={Radar} tone={(overview.identity_refresh_needed ?? 0) ? "amber" : "green"} />
        <StatCard label="Selected memory score" value={selectedUser ? `${selectedHealth.score}/100` : "—"} hint={selectedUser ? `${selectedHealth.label} continuity state` : "Pick a user to inspect"} icon={ShieldCheck} tone={selectedHealth.tone === "red" ? "red" : selectedHealth.tone === "amber" ? "amber" : "green"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <ModeSplit general={overview.general_users ?? 0} upsc={overview.upsc_users ?? 0} />
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-5 w-5 text-primary" />
              Usage signals, last 7 days
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-border/70 bg-background/40 p-3">
              <div className="text-xs text-muted-foreground">Inbound</div>
              <div className="mt-1 text-2xl font-semibold">{formatNumber(overview.inbound_events_7d ?? 0)}</div>
            </div>
            <div className="rounded-xl border border-border/70 bg-background/40 p-3">
              <div className="text-xs text-muted-foreground">Outbound</div>
              <div className="mt-1 text-2xl font-semibold">{formatNumber(overview.outbound_events_7d ?? 0)}</div>
            </div>
            <div className="rounded-xl border border-border/70 bg-background/40 p-3">
              <div className="text-xs text-muted-foreground">Mode switches</div>
              <div className="mt-1 text-2xl font-semibold">{formatNumber(overview.mode_switches_7d ?? 0)}</div>
            </div>
            <div className="rounded-xl border border-border/70 bg-background/40 p-3">
              <div className="text-xs text-muted-foreground">Menus</div>
              <div className="mt-1 text-2xl font-semibold">{formatNumber(overview.menu_requests_7d ?? 0)}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {apexConfig ? (
        <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <Card className="border-border/70 bg-card/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="h-5 w-5 text-primary" />
                Apex Runtime Controls
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-3 md:grid-cols-3">
                <label className="grid gap-1 text-xs text-muted-foreground">
                  Default mode
                  <select className="rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground" value={apexConfig.default_mode} onChange={(event) => updateApexConfig("default_mode", event.target.value)}>
                    <option value="general">General AI</option>
                    <option value="upsc">UPSC Mentor</option>
                  </select>
                </label>
                <label className="grid gap-1 text-xs text-muted-foreground">
                  Continuity cap
                  <Input type="number" value={apexConfig.continuity_length_cap} onChange={(event) => updateApexConfig("continuity_length_cap", Number(event.target.value))} />
                </label>
                <label className="grid gap-1 text-xs text-muted-foreground">
                  Summary cap
                  <Input type="number" value={apexConfig.summary_length_cap} onChange={(event) => updateApexConfig("summary_length_cap", Number(event.target.value))} />
                </label>
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <label className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/40 p-3 text-sm"><input type="checkbox" checked={apexConfig.stable_memory_enabled} onChange={(event) => updateApexConfig("stable_memory_enabled", event.target.checked)} /> Stable memory</label>
                <label className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/40 p-3 text-sm"><input type="checkbox" checked={apexConfig.interactive_whatsapp_mode} onChange={(event) => updateApexConfig("interactive_whatsapp_mode", event.target.checked)} /> Interactive mode</label>
                <label className="flex items-center gap-2 rounded-xl border border-border/70 bg-background/40 p-3 text-sm"><input type="checkbox" checked={apexConfig.quota_preview_enabled} onChange={(event) => updateApexConfig("quota_preview_enabled", event.target.checked)} /> Quota preview</label>
              </div>
              <label className="grid gap-1 text-xs text-muted-foreground">
                Onboarding menu text
                <textarea className="min-h-24 rounded-xl border border-border bg-background p-3 text-sm text-foreground" value={apexConfig.onboarding_menu_text} onChange={(event) => updateApexConfig("onboarding_menu_text", event.target.value)} />
              </label>
              <label className="grid gap-1 text-xs text-muted-foreground">
                Returning menu text
                <textarea className="min-h-24 rounded-xl border border-border bg-background p-3 text-sm text-foreground" value={apexConfig.returning_menu_text} onChange={(event) => updateApexConfig("returning_menu_text", event.target.value)} />
              </label>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="grid gap-1 text-xs text-muted-foreground">General prompt snippet<textarea className="min-h-20 rounded-xl border border-border bg-background p-3 text-sm text-foreground" value={apexConfig.general_prompt_snippet} onChange={(event) => updateApexConfig("general_prompt_snippet", event.target.value)} /></label>
                <label className="grid gap-1 text-xs text-muted-foreground">UPSC prompt snippet<textarea className="min-h-20 rounded-xl border border-border bg-background p-3 text-sm text-foreground" value={apexConfig.upsc_prompt_snippet} onChange={(event) => updateApexConfig("upsc_prompt_snippet", event.target.value)} /></label>
              </div>
              <Button onClick={() => void saveApexConfig()} disabled={configSaving}>{configSaving ? "Saving..." : "Save Apex controls"}</Button>
            </CardContent>
          </Card>
          <Card className="border-border/70 bg-card/70">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldAlert className="h-5 w-5 text-primary" />
                Quota & Credit Preview
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-4">
                <label className="grid gap-1 text-xs text-muted-foreground">Warn 24h<Input type="number" value={apexConfig.quota_warning_24h} onChange={(event) => updateApexConfig("quota_warning_24h", Number(event.target.value))} /></label>
                <label className="grid gap-1 text-xs text-muted-foreground">Block 24h<Input type="number" value={apexConfig.quota_block_24h} onChange={(event) => updateApexConfig("quota_block_24h", Number(event.target.value))} /></label>
                <label className="grid gap-1 text-xs text-muted-foreground">Warn 7d<Input type="number" value={apexConfig.quota_warning_7d} onChange={(event) => updateApexConfig("quota_warning_7d", Number(event.target.value))} /></label>
                <label className="grid gap-1 text-xs text-muted-foreground">Block 7d<Input type="number" value={apexConfig.quota_block_7d} onChange={(event) => updateApexConfig("quota_block_7d", Number(event.target.value))} /></label>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <StatCard label="Would block" value={formatNumber(quotaPreview?.summary.would_block ?? 0)} hint="Preview only, no enforcement" icon={ShieldAlert} tone={(quotaPreview?.summary.would_block ?? 0) ? "red" : "green"} />
                <StatCard label="Warning" value={formatNumber(quotaPreview?.summary.warning ?? 0)} hint="Users over warning thresholds" icon={AlertTriangle} tone={(quotaPreview?.summary.warning ?? 0) ? "amber" : "green"} />
                <StatCard label="Normal" value={formatNumber(quotaPreview?.summary.normal ?? 0)} hint="Users below preview thresholds" icon={ShieldCheck} tone="green" />
              </div>
              <div className="grid gap-2">
                {(quotaPreview?.users ?? []).slice(0, 6).map((user) => (
                  <button key={user.chat_id} type="button" onClick={() => setSelectedChatId(user.chat_id)} className="flex items-center justify-between gap-3 rounded-xl border border-border/70 bg-background/40 p-3 text-left text-sm hover:border-primary/40">
                    <span className="min-w-0 truncate">{user.display_name}</span>
                    <span className="text-xs text-muted-foreground">24h {user.usage_24h} · 7d {user.usage_7d}</span>
                    <Badge>{user.status}</Badge>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-5 w-5 text-primary" />
              Recent users
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {recentUsers.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No Apex users yet.</div>
            ) : (
              recentUsers.slice(0, 8).map((user) => (
                <UserRow
                  key={user.chat_id}
                  user={user}
                  active={selectedUser?.chat_id === user.chat_id}
                  onSelect={(next) => setSelectedChatId(next.chat_id)}
                />
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Recent mode switches
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {recentModeSwitches.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No recent mode switches.</div>
            ) : (
              recentModeSwitches.map((event) => (
                <div key={`${event.chat_id}-${event.created_at}`} className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 truncate text-sm font-medium">{event.chat_id}</div>
                    <Badge>{event.mode || "mode"}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">{formatDate(event.created_at)}</div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <Search className="h-5 w-5 text-primary" />
                User explorer
              </CardTitle>
              <div className="flex w-full gap-2 lg:w-auto lg:min-w-[420px]">
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void handleSearch();
                  }}
                  placeholder="Search phone, name, chat id, or memory"
                />
                <Button onClick={handleSearch} size="sm" disabled={usersLoading}>
                  {usersLoading ? <Spinner /> : <Search className="h-4 w-4" />}
                  Search
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {users.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No matching Apex users.</div>
            ) : (
              users.map((user) => (
                <UserRow
                  key={user.chat_id}
                  user={user}
                  active={selectedUser?.chat_id === user.chat_id}
                  onSelect={(next) => setSelectedChatId(next.chat_id)}
                />
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-5 w-5 text-primary" />
                User detail inspector
              </CardTitle>
              <div className="grid gap-4 xl:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Recovery shelf · Safe sync</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void handleRecoveryAction("refresh_identity")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <RefreshCw className="h-4 w-4" />
                      {actionLoading === "refresh_identity" ? recoveryActions.refresh_identity.pending : recoveryActions.refresh_identity.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("resend_menu")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <RefreshCw className="h-4 w-4" />
                      {actionLoading === "resend_menu" ? recoveryActions.resend_menu.pending : recoveryActions.resend_menu.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("force_mode_sync")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <RefreshCw className="h-4 w-4" />
                      {actionLoading === "force_mode_sync" ? recoveryActions.force_mode_sync.pending : recoveryActions.force_mode_sync.label}
                    </Button>
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Recovery shelf · Memory repair</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void handleRecoveryAction("rebuild_summary")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <RefreshCw className="h-4 w-4" />
                      {actionLoading === "rebuild_summary" ? recoveryActions.rebuild_summary.pending : recoveryActions.rebuild_summary.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("clear_continuity")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <Trash2 className="h-4 w-4" />
                      {actionLoading === "clear_continuity" ? recoveryActions.clear_continuity.pending : recoveryActions.clear_continuity.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("clear_stable_memory")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <Trash2 className="h-4 w-4" />
                      {actionLoading === "clear_stable_memory" ? recoveryActions.clear_stable_memory.pending : recoveryActions.clear_stable_memory.label}
                    </Button>
                    <Button onClick={handleClearMemory} size="sm" disabled={!selectedUser || clearing || !!actionLoading}>
                      <Trash2 className="h-4 w-4" />
                      {clearing ? "Clearing" : "Clear all memory"}
                    </Button>
                  </div>
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Recovery shelf · Mode repair</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void handleRecoveryAction("set_mode_general")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <WandSparkles className="h-4 w-4" />
                      {actionLoading === "set_mode_general" ? recoveryActions.set_mode_general.pending : recoveryActions.set_mode_general.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("set_mode_upsc")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <WandSparkles className="h-4 w-4" />
                      {actionLoading === "set_mode_upsc" ? recoveryActions.set_mode_upsc.pending : recoveryActions.set_mode_upsc.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("restore_default_mode")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <WandSparkles className="h-4 w-4" />
                      {actionLoading === "restore_default_mode" ? recoveryActions.restore_default_mode.pending : recoveryActions.restore_default_mode.label}
                    </Button>
                  </div>
                </div>
                <div className="rounded-2xl border border-rose-500/25 bg-rose-500/5 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-rose-200">Recovery shelf · Scoped reset</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button onClick={() => void handleRecoveryAction("clear_onboarding")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <Trash2 className="h-4 w-4" />
                      {actionLoading === "clear_onboarding" ? recoveryActions.clear_onboarding.pending : recoveryActions.clear_onboarding.label}
                    </Button>
                    <Button onClick={() => void handleRecoveryAction("reset_user_scoped")} size="sm" disabled={!selectedUser || !!actionLoading}>
                      <Trash2 className="h-4 w-4" />
                      {actionLoading === "reset_user_scoped" ? recoveryActions.reset_user_scoped.pending : recoveryActions.reset_user_scoped.label}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {!selectedUser ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">Select a user to inspect memory and recent activity.</div>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  <DetailField label="Display name" value={identityTitle(selectedUser)} />
                  <DetailField label="Primary phone" value={selectedUser.phone_number} />
                  <DetailField label="Chat ID" value={selectedUser.chat_id} />
                  <DetailField label="Sender ID" value={selectedUser.sender_id} />
                  <DetailField label="Sender phone" value={selectedUser.sender_phone} />
                  <DetailField label="Chat phone" value={selectedUser.chat_phone} />
                  <DetailField label="Chat name" value={selectedUser.chat_name} />
                  <DetailField label="Sender name" value={selectedUser.sender_name} />
                  <DetailField label="Mode" value={selectedUser.current_mode || "general"} />
                  <DetailField label="Onboarded" value={selectedUser.onboarded ? "Yes" : "No"} />
                  <DetailField label="Group chat" value={selectedUser.is_group ? "Yes" : "No"} />
                  <DetailField label="Chat JID kind" value={selectedUser.chat_jid_kind} />
                  <DetailField label="Sender JID kind" value={selectedUser.sender_jid_kind} />
                  <DetailField label="Identity source" value={selectedUser.identity_source} />
                  <DetailField label="Identity refreshed" value={formatDate(selectedUser.identity_refreshed_at)} />
                  <DetailField label="Message count" value={selectedUser.message_count} />
                  <DetailField label="Mode switches" value={selectedUser.mode_switch_count} />
                  <DetailField label="Menu requests" value={selectedUser.menu_request_count} />
                  <DetailField label="First seen" value={formatDate(selectedUser.first_seen)} />
                  <DetailField label="Last seen" value={formatDate(selectedUser.last_seen)} />
                </div>
                <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Continuity QA</div>
                      <div className="mt-2 text-xl font-semibold text-foreground">{selectedHealth.label} · {selectedHealth.score}/100</div>
                    </div>
                    <div className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium",
                      selectedHealth.tone === "green" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
                      selectedHealth.tone === "amber" && "border-amber-500/30 bg-amber-500/10 text-amber-200",
                      selectedHealth.tone === "red" && "border-rose-500/30 bg-rose-500/10 text-rose-200",
                    )}>
                      {selectedHealth.label}
                    </div>
                  </div>
                  <div className="mt-3 space-y-2">
                    {selectedHealth.reasons.map((reason) => (
                      <div key={reason} className="rounded-xl border border-border/50 bg-background/40 px-3 py-2 text-sm text-muted-foreground normal-case">
                        {reason}
                      </div>
                    ))}
                  </div>
                </div>
                <DetailField label="Stable memory" value={selectedUser.stable_memory} />
                <DetailField label="Conversation summary" value={selectedUser.conversation_summary} />
                <DetailField label="Latest user message" value={selectedUser.last_user_message} />
                <DetailField label="Latest agent reply" value={selectedUser.last_agent_reply} />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <WandSparkles className="h-5 w-5 text-primary" />
              Prompt context preview
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {!selectedUser ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">Select a user to preview live injected context.</div>
            ) : (
              <>
                <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Memory QA</div>
                    <Badge>{selectedUser.memory_qa?.label || simulatedContext?.memory_qa.label || "unknown"} · {selectedUser.memory_qa?.score ?? simulatedContext?.memory_qa.score ?? 0}/100</Badge>
                  </div>
                  <div className="mt-3 space-y-2">
                    {(selectedUser.memory_qa?.findings || simulatedContext?.memory_qa.findings || []).map((finding) => (
                      <div key={`${finding.label}-${finding.severity}`} className="rounded-xl border border-border/50 bg-background/40 px-3 py-2">
                        <div className="text-sm font-medium text-foreground">{finding.label}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{finding.detail}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <DetailField label="Selected mode" value={simulatedContext?.mode || selectedUser.current_mode || "general"} />
                <DetailField label="Stable memory injection" value={simulatedContext?.stable_memory || selectedUser.stable_memory || "No stable memory will be injected."} />
                <DetailField label="Continuity summary injection" value={simulatedContext?.conversation_summary || selectedUser.conversation_summary || "No continuity summary will be injected."} />
                <DetailField label="Previous exchange context" value={`User: ${selectedUser.last_user_message || "—"}
Assistant: ${selectedUser.last_agent_reply || "—"}`} />
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock3 className="h-5 w-5 text-primary" />
              Live event feed
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.recent_events.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No recent Apex events.</div>
            ) : (
              data.recent_events.slice(0, 12).map((event) => (
                <EventRow key={`${event.chat_id}-${event.created_at}-${event.event_type}`} event={event} onPickUser={setSelectedChatId} />
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        
        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock3 className="h-5 w-5 text-primary" />
              Operator timeline
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {timeline.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">No timeline entries for this scope yet.</div>
            ) : (
              timeline.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => entry.chat_id && setSelectedChatId(entry.chat_id)}
                  className="w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/60 hover:bg-primary/5"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-foreground">{entry.title || entry.event_type.replace(/_/g, " ")}</div>
                    <div className="text-xs text-muted-foreground">{formatDate(entry.created_at)}</div>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">{entry.chat_id}</div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <span className="rounded-full border border-border/70 px-2 py-1">{entry.source}</span>
                    {entry.mode ? <span className="rounded-full border border-border/70 px-2 py-1">{entry.mode}</span> : null}
                    {entry.status ? <span className="rounded-full border border-border/70 px-2 py-1">{entry.status}</span> : null}
                    {typeof entry.units === "number" ? <span className="rounded-full border border-border/70 px-2 py-1">{entry.units} units</span> : null}
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Audit log
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {auditLog.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">No audit entries for this scope yet.</div>
            ) : (
              auditLog.map((entry) => (
                <div key={entry.id} className="rounded-2xl border border-border/60 bg-background/35 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium text-foreground">{entry.action.replace(/_/g, " ")}</div>
                    <div className="text-xs text-muted-foreground">{formatDate(entry.created_at)}</div>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">{entry.chat_id}</div>
                  <div className="mt-2 text-xs text-muted-foreground">Status: {entry.status}</div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <WandSparkles className="h-5 w-5 text-primary" />
              Recovery actions shelf
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground normal-case">
            <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
              Scoped actions are now backend-driven, per-user, and audit logged. Live actions now include refresh identity, force mode sync, direct mode override, onboarding reset, summary rebuild, clear continuity, clear stable memory, and clear full memory.
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/35 p-4">
              Resend onboarding/menu now goes through the live WhatsApp bridge and is audit logged alongside the other scoped recovery actions.
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        
        <Card className="border-border/70 bg-card/70 xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Zap className="h-5 w-5 text-primary" />
              WhatsApp Connection
            </CardTitle>
          </CardHeader>
          <CardContent>
            <button type="button" onClick={handleRelogin} className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 transition-colors">WhatsApp Re-login</button>
            {showQRModal && (
              <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm">
                <div className="relative w-full max-w-sm rounded-xl border bg-card p-6 shadow-xl">
                  <button onClick={() => setShowQRModal(false)} className="absolute right-4 top-4 text-muted-foreground hover:text-foreground">✕</button>
                  <h3 className="text-lg font-semibold mb-4 text-center">Scan QR Code</h3>
                  <div className="flex flex-col items-center justify-center p-2 gap-4">
                    {qrData ? (
                      <img src={`https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(qrData)}`} alt="QR Code" className="rounded-lg shadow-sm w-[250px] h-[250px]" />
                    ) : (
                      <div className="flex flex-col items-center py-10 text-muted-foreground"><Zap className="h-8 w-8 animate-pulse mb-2 text-primary" /> Generating new session...</div>
                    )}
                    <p className="text-sm text-muted-foreground text-center mt-2">Open WhatsApp on your phone and scan this code to link your account.</p>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70 xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-5 w-5 text-primary" />
              Continuity watchlist
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {usersNeedingAttention.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">All tracked users currently look healthy.</div>
            ) : (
              usersNeedingAttention.slice(0, 6).map((user) => {
                const health = getMemoryHealth(user);
                return (
                  <button key={user.chat_id} type="button" onClick={() => setSelectedChatId(user.chat_id)} className="w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/25 hover:bg-background/55">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 truncate text-sm font-medium">{user.chat_id}</div>
                      <div className="text-xs text-muted-foreground">{health.score}/100</div>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground normal-case">{health.reasons[0]}</div>
                  </button>
                );
              })
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70 xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Radar className="h-5 w-5 text-primary" />
              Menu friction
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {menuHeavyUsers.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">No users are repeatedly looping through menu selection right now.</div>
            ) : (
              menuHeavyUsers.slice(0, 6).map((user) => (
                <button key={user.chat_id} type="button" onClick={() => setSelectedChatId(user.chat_id)} className="w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/25 hover:bg-background/55">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 truncate text-sm font-medium">{user.chat_id}</div>
                    <Badge>{user.current_mode || "general"}</Badge>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground normal-case">Menu requests: {user.menu_request_count} • Mode switches: {user.mode_switch_count}</div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-card/70 xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Zap className="h-5 w-5 text-primary" />
              Frequent switchers
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {modeSwitchLeaders.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">No switching activity recorded yet.</div>
            ) : (
              modeSwitchLeaders.map((user) => (
                <button key={user.chat_id} type="button" onClick={() => setSelectedChatId(user.chat_id)} className="w-full rounded-2xl border border-border/60 bg-background/35 p-4 text-left transition hover:border-primary/25 hover:bg-background/55">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 truncate text-sm font-medium">{user.chat_id}</div>
                    <div className="text-sm font-semibold text-foreground">{user.mode_switch_count}</div>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground normal-case">Current mode: {user.current_mode || "general"} • Menus: {user.menu_request_count}</div>
                </button>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
