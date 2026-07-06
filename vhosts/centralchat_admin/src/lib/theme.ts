export type ColorMode = "light" | "dark";

export const THEME_STORAGE_KEY = "central-admin-color-mode";

export function getStoredColorMode(): ColorMode | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function resolveInitialColorMode(): ColorMode {
  return getStoredColorMode() ?? "light";
}

export function applyColorMode(mode: ColorMode): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("dark", mode === "dark");
  root.style.colorScheme = mode;
}

/** Inline script for <head> — avoids flash of wrong theme before hydration. */
export const THEME_INIT_SCRIPT = `(function(){try{var m=localStorage.getItem("${THEME_STORAGE_KEY}");if(m==="dark"){document.documentElement.classList.add("dark");document.documentElement.style.colorScheme="dark";}else if(m==="light"){document.documentElement.classList.remove("dark");document.documentElement.style.colorScheme="light";}}catch(e){}})();`;
