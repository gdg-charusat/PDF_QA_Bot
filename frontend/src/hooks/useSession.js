import { useState, useEffect } from "react";

/**
 * Custom hook for managing session ID
 * Generates a unique session ID on mount for session isolation
 */
export const useSession = () => {
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    // Generate unique session ID using crypto API or fallback
    const newSessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).substring(2, 15) +
          Math.random().toString(36).substring(2, 15);

    setSessionId(newSessionId);
  }, []);

  return sessionId;
};

export default useSession;
