export interface InstalledPlugin {
  name: string;
  version: string;
  description: string;
  install_path: string;
  source: "std" | "local" | "installed" | "unknown" | string;
  source_url: string | null;
  installed_at: string | null;
  registered_services: string[];
  running: boolean;
  uninstallable: boolean;
  /** Whether the plugin will be loaded on the next restart. */
  enabled: boolean;
}

export interface InstallPluginResponse {
  plugin: InstalledPlugin;
}

export interface SetEnabledResult {
  name: string;
  enabled: boolean;
  restart_required: boolean;
}
