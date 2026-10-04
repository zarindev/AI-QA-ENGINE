import { useCallback, useState } from "react";

export function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() =>
    document.documentElement.classList.contains("light") ? "light" : "dark",
  );
  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.replace(theme, next);
    try {
      localStorage.setItem("qap-theme", next);
    } catch {
      /* private mode: theme just won't persist */
    }
    setTheme(next);
  }, [theme]);
  return { theme, toggle };
}
