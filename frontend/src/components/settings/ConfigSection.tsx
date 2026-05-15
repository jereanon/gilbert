/**
 * ConfigSection — collapsible card for a single service namespace.
 *
 * Visual structure follows the design-system Card vocabulary:
 *   - Clickable header (eyebrow namespace + title + state pill)
 *   - Body (gated by ``enabled`` if present)
 *   - Backend selector in its own inset Card so the boundary
 *     between service-level and backend-specific is obvious
 *   - Actions section
 *   - Footer with Save / Reset + dirty status
 *
 * State management is preserved verbatim — only the rendering surface
 * changes.
 */

import { useState, useCallback, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import {
  Card,
  CardContent,
  CardEyebrow,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfigField } from "./ConfigField";
import {
  ChevronDownIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  RotateCcwIcon,
  SaveIcon,
  ZapIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  ConfigSection as ConfigSectionType,
  ConfigParamMeta,
  ConfigActionMeta,
  ConfigActionResult,
} from "@/types/config";

interface ConfigSectionProps {
  section: ConfigSectionType;
}

function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Group backend params for display. */
function backendGroups(
  params: ConfigParamMeta[],
  singleBackendName: string,
  hasBackendSelector: boolean,
): { label: string; params: ConfigParamMeta[] }[] {
  // Service with a backend selector — all backend params belong to
  // the currently-selected backend; show as one group.
  if (hasBackendSelector) {
    const label = singleBackendName
      ? `${humanize(singleBackendName)} backend`
      : "Backend";
    return [{ label, params }];
  }

  // Multi-backend service (e.g. AI with backends.anthropic.*,
  // backends.openai.*). Group by the second path segment when keys
  // start with "backends.", otherwise by the first segment.
  const groups: { label: string; params: ConfigParamMeta[] }[] = [];
  const seen = new Set<string>();
  for (const p of params) {
    const parts = p.key.split(".");
    const isNested = parts[0] === "backends" && parts.length >= 3;
    const groupKey = isNested ? `${parts[0]}.${parts[1]}` : parts[0];
    const groupLabel = isNested ? parts[1] : groupKey;
    if (seen.has(groupKey)) continue;
    seen.add(groupKey);
    groups.push({
      label: humanize(groupLabel),
      params: params.filter(
        (q) => q.key === groupKey || q.key.startsWith(`${groupKey}.`),
      ),
    });
  }
  return groups;
}

interface ActionUIState {
  status: "idle" | "running" | "ok" | "error" | "pending";
  message: string;
  /** When set, the button becomes a "Continue" that invokes this key instead. */
  followup: string;
}

export function ConfigSection({ section }: ConfigSectionProps) {
  const queryClient = useQueryClient();
  const api = useWsApi();
  const [expanded, setExpanded] = useState(false);
  const [localValues, setLocalValues] = useState<Record<string, unknown>>({});
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [actionStates, setActionStates] = useState<Record<string, ActionUIState>>(
    {},
  );

  // Merge defaults → server values → local edits so fields show
  // their declared default when no value has been stored yet.
  const merged = useMemo(() => {
    const defaults: Record<string, unknown> = {};
    for (const p of section.params) {
      if (p.default != null) defaults[p.key] = p.default;
    }
    return { ...defaults, ...section.values, ...localValues };
  }, [section.params, section.values, localValues]);

  const hasChanges = Object.keys(localValues).length > 0;

  const handleFieldChange = useCallback((key: string, value: unknown) => {
    setLocalValues((prev) => ({ ...prev, [key]: value }));
    setSaveStatus(null);
  }, []);

  const saveMutation = useMutation({
    mutationFn: () => api.setConfigSection(section.namespace, localValues),
    onSuccess: (result) => {
      setLocalValues({});
      queryClient.invalidateQueries({ queryKey: ["config"] });
      const results = result?.results ?? {};
      const restarted = Object.values(results).some(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (r: any) =>
          r?.message?.includes("restarted") || r?.message?.includes("enabled"),
      );
      setSaveStatus(restarted ? "Saved — service restarting…" : "Saved");
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: () => {
      setSaveStatus("Save failed");
      setTimeout(() => setSaveStatus(null), 3000);
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => api.resetConfigSection(section.namespace),
    onSuccess: () => {
      setLocalValues({});
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setSaveStatus("Reset to defaults");
      setTimeout(() => setSaveStatus(null), 3000);
    },
  });

  const runAction = useCallback(
    async (action: ConfigActionMeta, keyOverride?: string) => {
      if (action.confirm && !keyOverride) {
        if (!window.confirm(action.confirm)) return;
      }
      const invokeKey = keyOverride ?? action.key;
      setActionStates((prev) => ({
        ...prev,
        [action.key]: { status: "running", message: "", followup: "" },
      }));
      try {
        const resp = await api.invokeConfigAction(section.namespace, invokeKey);
        const result: ConfigActionResult = resp.result;

        // If the backend asked us to persist values, push them into
        // localValues as if the user had typed them. Lets the user
        // see the new values as pending changes and click Save
        // explicitly — matches how every other field behaves.
        const persistRaw = (result.data ?? {})["persist"];
        if (persistRaw && typeof persistRaw === "object") {
          const persist = persistRaw as Record<string, unknown>;
          if (Object.keys(persist).length > 0) {
            setLocalValues((prev) => ({ ...prev, ...persist }));
            setSaveStatus(null);
          }
        }

        setActionStates((prev) => ({
          ...prev,
          [action.key]: {
            status: result.status,
            message: result.message,
            followup: result.followup_action ?? "",
          },
        }));

        if (result.open_url) {
          window.open(result.open_url, "_blank", "noopener,noreferrer");
        }

        // Auto-clear ok messages; leave errors / pending up.
        // Persist-bearing actions stay visible longer (the user
        // still has to click Save).
        const hasPersist =
          persistRaw &&
          typeof persistRaw === "object" &&
          Object.keys(persistRaw as Record<string, unknown>).length > 0;
        if (result.status === "ok") {
          setTimeout(
            () => {
              setActionStates((prev) => {
                const next = { ...prev };
                if (next[action.key]?.status === "ok") delete next[action.key];
                return next;
              });
            },
            hasPersist ? 20000 : 5000,
          );
        }
      } catch (exc) {
        setActionStates((prev) => ({
          ...prev,
          [action.key]: {
            status: "error",
            message: (exc as Error)?.message ?? String(exc),
            followup: "",
          },
        }));
      }
    },
    [api, section.namespace],
  );

  // Split params into groups
  const enabledParam = section.params.find((p) => p.key === "enabled");
  const backendParam = section.params.find((p) => p.key === "backend");
  const serviceParams = section.params.filter(
    (p) => p.key !== "enabled" && p.key !== "backend" && !p.backend_param,
  );
  const backendSettingsParams = section.params.filter((p) => p.backend_param);

  const backendName = String(merged["backend"] ?? "");

  /** Get the nested value for a dot-path key. Falls back to the
   *  param's declared default. */
  const getValue = (key: string): unknown => {
    if (key in localValues) return localValues[key];
    const parts = key.split(".");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let cur: any = section.values;
    for (const part of parts) {
      if (cur == null || typeof cur !== "object") {
        cur = undefined;
        break;
      }
      cur = cur[part];
    }
    if (cur === undefined) {
      const param = section.params.find((p) => p.key === key);
      return param?.default ?? undefined;
    }
    return cur;
  };

  // ── Status pill ────────────────────────────────────────────────
  const statusPill = (() => {
    if (section.started) {
      return (
        <Badge variant="active" dot>
          running
        </Badge>
      );
    }
    if (section.failed) {
      return (
        <Badge variant="error" dot>
          failed
        </Badge>
      );
    }
    if (!section.enabled) {
      return (
        <Badge variant="off" dot>
          off
        </Badge>
      );
    }
    return null;
  })();

  const sectionEnabled = !enabledParam || merged["enabled"] === true;

  return (
    <Card>
      {/* Header — clickable, toggles expansion. */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "group/header w-full text-left",
          "transition-colors duration-(--duration-fast) ease-(--ease-out)",
          "hover:bg-foreground/[0.025]",
          expanded && "border-b border-border",
        )}
      >
        <CardHeader className="grid-cols-[auto_1fr_auto] items-center py-3 gap-x-2.5">
          {expanded ? (
            <ChevronDownIcon className="size-3.5 text-muted-foreground row-span-2" />
          ) : (
            <ChevronRightIcon className="size-3.5 text-muted-foreground row-span-2" />
          )}
          <div className="min-w-0">
            <CardEyebrow>{section.namespace}</CardEyebrow>
            <CardTitle className="mt-1 truncate">
              {humanize(section.namespace)}
            </CardTitle>
          </div>
          {statusPill ? (
            <div className="row-span-2 self-center">{statusPill}</div>
          ) : null}
        </CardHeader>
      </button>

      {/* Body */}
      {expanded && (
        <CardContent className="py-4 space-y-4">
          {/* Enabled toggle — the "root" gate. Sits above the gated
              body so the dependency relationship is visually obvious. */}
          {enabledParam && (
            <ConfigField
              param={enabledParam}
              value={merged["enabled"]}
              onChange={handleFieldChange}
              namespace={section.namespace}
            />
          )}

          {sectionEnabled && (
            <>
              {/* Service-level params */}
              {serviceParams.length > 0 && (
                <div className="space-y-4">
                  {serviceParams.map((p) => (
                    <ConfigField
                      key={p.key}
                      param={p}
                      value={merged[p.key]}
                      onChange={handleFieldChange}
                      namespace={section.namespace}
                    />
                  ))}
                </div>
              )}

              {/* Backend selector — last service-level option, sits
                  outside the backend Card to encode that it picks WHICH
                  backend goes inside that card. */}
              {backendParam && (
                <ConfigField
                  param={backendParam}
                  value={merged["backend"]}
                  onChange={handleFieldChange}
                  namespace={section.namespace}
                />
              )}

              {/* Backend-specific settings — inset Card per backend
                  group. Makes the "these are only relevant when this
                  backend is selected" boundary visible. */}
              {backendSettingsParams.length > 0 &&
                (!backendParam || backendName) &&
                backendGroups(
                  backendSettingsParams,
                  backendName,
                  !!backendParam,
                ).map((group) => {
                  // Multi-backend groups collapse unless explicitly
                  // enabled. An unset / null / undefined stored value
                  // counts as disabled — otherwise every newly-
                  // registered backend would expand its full config on
                  // first render just because its declared default is
                  // True.
                  const enableParam = group.params.find((p) =>
                    p.key.endsWith(".enabled"),
                  );
                  const isEnabled = enableParam
                    ? getValue(enableParam.key) === true
                    : true;
                  const otherParams = enableParam
                    ? group.params.filter((p) => p !== enableParam)
                    : group.params;

                  return (
                    <Card key={group.label} size="sm">
                      <CardHeader className="pb-1">
                        <CardEyebrow>{group.label.toLowerCase()}</CardEyebrow>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        {enableParam && (
                          <ConfigField
                            param={enableParam}
                            value={getValue(enableParam.key)}
                            onChange={handleFieldChange}
                            namespace={section.namespace}
                          />
                        )}
                        {isEnabled &&
                          otherParams.map((p) => (
                            <ConfigField
                              key={p.key}
                              param={p}
                              value={getValue(p.key)}
                              onChange={handleFieldChange}
                              namespace={section.namespace}
                            />
                          ))}
                      </CardContent>
                    </Card>
                  );
                })}
            </>
          )}

          {/* Actions — one-click ops declared by the service / backend.
              Filtered to the current backend so switching backends
              (even unsaved) immediately surfaces the right buttons.
              Actions with empty ``backend`` are service-level. */}
          <ActionsBlock
            section={section}
            actions={section.actions ?? []}
            actionStates={actionStates}
            runAction={runAction}
            backendName={String(merged["backend"] ?? "")}
            hasBackendChangeUnsaved={
              backendParam !== undefined &&
              "backend" in localValues &&
              localValues["backend"] !== section.values["backend"]
            }
            hasChanges={hasChanges}
          />
        </CardContent>
      )}

      {/* Footer — Save / Reset + dirty status. Only shown when
          expanded (no point dangling when the body is collapsed). */}
      {expanded && (
        <CardFooter className="justify-between">
          <div className="text-xs">
            {saveStatus ? (
              <span
                className={cn(
                  "font-mono",
                  saveStatus.includes("fail")
                    ? "text-destructive"
                    : "text-success",
                )}
              >
                {saveStatus}
              </span>
            ) : hasChanges ? (
              <span className="font-mono text-(--signal)">
                {Object.keys(localValues).length} unsaved change
                {Object.keys(localValues).length === 1 ? "" : "s"}
              </span>
            ) : (
              <span className="text-muted-foreground">No changes.</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              disabled={resetMutation.isPending}
              onClick={() => resetMutation.mutate()}
            >
              <RotateCcwIcon />
              Reset
            </Button>
            <Button
              size="sm"
              disabled={!hasChanges || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              <SaveIcon />
              {saveMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </CardFooter>
      )}
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────
// Actions block — extracted for readability. Same behavior; the
// surface now reads as a list with mono action keys + state text.
// ──────────────────────────────────────────────────────────────────

interface ActionsBlockProps {
  section: ConfigSectionType;
  actions: ConfigActionMeta[];
  actionStates: Record<string, ActionUIState>;
  runAction: (action: ConfigActionMeta, keyOverride?: string) => Promise<void>;
  backendName: string;
  hasBackendChangeUnsaved: boolean;
  hasChanges: boolean;
}

function ActionsBlock({
  actions,
  actionStates,
  runAction,
  backendName,
  hasBackendChangeUnsaved,
  hasChanges,
}: ActionsBlockProps) {
  const visible = actions.filter(
    (a) => !a.hidden && (!a.backend || a.backend === backendName),
  );
  if (visible.length === 0) return null;

  return (
    <div className="pt-1">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          actions
        </span>
      </div>

      {hasBackendChangeUnsaved ? (
        <p className="mb-2 text-xs text-warning">
          Save to enable actions for the new backend.
        </p>
      ) : hasChanges ? (
        <p className="mb-2 text-xs text-warning">
          Unsaved changes — actions run against the saved values, not
          the ones you just edited. Save first.
        </p>
      ) : null}

      <div className="space-y-1">
        {visible.map((action) => {
          const state = actionStates[action.key];
          const running = state?.status === "running";
          const pending = state?.status === "pending";
          const isFollowup = pending && !!state?.followup;
          const nextKey = isFollowup ? state.followup : action.key;
          const label = isFollowup ? "Continue" : action.label;
          const statusColor =
            state?.status === "error"
              ? "text-destructive"
              : state?.status === "ok"
                ? "text-success"
                : state?.status === "pending"
                  ? "text-warning"
                  : "text-muted-foreground";

          return (
            <div
              key={action.key}
              className="flex flex-wrap items-center gap-2"
            >
              <Button
                size="sm"
                variant="outline"
                disabled={running}
                onClick={() =>
                  runAction(action, isFollowup ? nextKey : undefined)
                }
              >
                {isFollowup ? <ExternalLinkIcon /> : <ZapIcon />}
                {running ? "Running…" : label}
              </Button>
              {action.description && !state && (
                <span className="text-xs text-muted-foreground">
                  {action.description}
                </span>
              )}
              {state?.message && (
                <span className={cn("text-xs font-mono", statusColor)}>
                  {state.message}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
