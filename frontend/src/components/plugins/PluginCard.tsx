import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Trash2Icon, AlertCircleIcon } from "lucide-react";
import type { InstalledPlugin } from "@/types/plugins";

interface PluginCardProps {
  plugin: InstalledPlugin;
  onUninstall: () => void;
  uninstalling: boolean;
  onSetEnabled: (enabled: boolean) => Promise<void>;
}

function sourceBadgeVariant(
  source: string,
): "default" | "secondary" | "outline" {
  switch (source) {
    case "installed":
      return "default";
    case "std":
      return "secondary";
    case "local":
      return "outline";
    default:
      return "outline";
  }
}

function formatInstalledAt(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const month = d.toLocaleString("en-US", { month: "short" });
    const day = d.getDate();
    const year = d.getFullYear();
    return `${month} ${day}, ${year}`;
  } catch {
    return iso;
  }
}

export function PluginCard({
  plugin,
  onUninstall,
  uninstalling,
  onSetEnabled,
}: PluginCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [restartRequired, setRestartRequired] = useState(false);

  async function handleToggle(checked: boolean) {
    setToggling(true);
    try {
      await onSetEnabled(checked);
      setRestartRequired(true);
    } finally {
      setToggling(false);
    }
  }

  return (
    <Card>
      <CardHeader
        className="cursor-pointer py-3"
        onClick={() => setExpanded(!expanded)}
      >
        <CardTitle className="text-sm flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full flex-shrink-0 ${
              plugin.running ? "bg-green-500" : "bg-yellow-500"
            }`}
            title={plugin.running ? "Loaded" : "Not running"}
          />
          <span className="font-medium">{plugin.name}</span>
          <span className="text-xs text-muted-foreground">v{plugin.version}</span>
          <Badge variant={sourceBadgeVariant(plugin.source)} className="text-[10px]">
            {plugin.source}
          </Badge>
          {restartRequired && (
            <span className="flex items-center gap-1 text-xs text-amber-500 ml-1">
              <AlertCircleIcon className="h-3 w-3" />
              Restart required
            </span>
          )}
          {/* Enable toggle — stop click from bubbling to expand handler */}
          <span
            className="ml-auto flex items-center gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="text-xs text-muted-foreground">
              {plugin.enabled ? "Enabled" : "Disabled"}
            </span>
            <Switch
              checked={plugin.enabled}
              disabled={toggling}
              onCheckedChange={handleToggle}
            />
          </span>
          <span className="text-xs text-muted-foreground ml-1">
            {expanded ? "▾" : "▸"}
          </span>
        </CardTitle>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-3 text-sm pt-0">
          {plugin.description && (
            <p className="text-muted-foreground text-xs">{plugin.description}</p>
          )}

          {restartRequired && (
            <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 p-2 text-xs text-amber-700 dark:text-amber-400">
              <AlertCircleIcon className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
              <span>
                Restart Gilbert to apply this change. The plugin will be{" "}
                {plugin.enabled ? "enabled" : "disabled"} on the next boot.
              </span>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
            <span className="text-muted-foreground">Install path:</span>
            <code className="break-all">{plugin.install_path}</code>

            {plugin.source_url && (
              <>
                <span className="text-muted-foreground">Source URL:</span>
                <a
                  href={plugin.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all underline"
                >
                  {plugin.source_url}
                </a>
              </>
            )}

            {plugin.installed_at && (
              <>
                <span className="text-muted-foreground">Installed:</span>
                <span>{formatInstalledAt(plugin.installed_at)}</span>
              </>
            )}
          </div>

          {plugin.registered_services.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">
                Registered services:
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {plugin.registered_services.map((s) => (
                  <Badge key={s} variant="outline" className="text-xs">
                    {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {plugin.uninstallable && (
            <div className="pt-2 border-t">
              <Button
                size="sm"
                variant="destructive"
                onClick={onUninstall}
                disabled={uninstalling}
              >
                <Trash2Icon className="h-3 w-3 mr-1" />
                {uninstalling ? "Uninstalling..." : "Uninstall"}
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
