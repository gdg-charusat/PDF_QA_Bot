import { useState, useEffect } from "react";

const THEME_STORAGE_KEY = "pdf-qa-bot-theme";

/**
 * Custom hook for managing dark mode theme
 * Persists theme preference to localStorage and applies to document
 */
export const useTheme = () => {
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved ? JSON.parse(saved) : false;
  });

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(darkMode));
    document.body.classList.toggle("dark-mode", darkMode);
  }, [darkMode]);

  const toggleTheme = () => setDarkMode((prev) => !prev);

  return { darkMode, toggleTheme };
};

export default useTheme;
