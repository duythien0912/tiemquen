/* Compose-derived shop theme (4 seed colors → derived palette, ENGINE-SPEC §6)
 * mapped onto the shadcn/ui CSS-variable contract so EVERY shadcn component
 * automatically wears the shop's theme — no per-component styling. */

const SHADCN_MAP: Record<string, string[]> = {
  bg: ["--background"],
  surface: ["--card", "--popover", "--secondary", "--muted"],
  text: ["--foreground", "--card-foreground", "--popover-foreground", "--secondary-foreground"],
  text_muted: ["--muted-foreground"],
  accent: ["--primary", "--ring", "--accent"],
  accent_text: ["--primary-foreground", "--accent-foreground"],
  warn: ["--chart-4"],
  success: ["--chart-2"],
};

export function applyShopTheme(theme: Record<string, string>): void {
  const root = document.documentElement.style;
  for (const [key, value] of Object.entries(theme)) {
    for (const cssVar of SHADCN_MAP[key] || []) root.setProperty(cssVar, value);
    root.setProperty(`--tq-${key.replace(/_/g, "-")}`, value);
  }
}
