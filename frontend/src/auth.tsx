import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  createScholarContribution, fetchScholarProfile, loginScholar, registerScholar, updateScholarProfile,
  type ScholarContributionInput, type ScholarProfile, type ScholarProfileInput,
} from "./api";

const TOKEN_KEY = "medbridge.scholar-token";

interface AuthContextValue {
  profile: ScholarProfile | null;
  loading: boolean;
  login: (identifier: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  updateProfile: (input: ScholarProfileInput) => Promise<void>;
  contributeResearch: (input: ScholarContributionInput) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<ScholarProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) { setLoading(false); return; }
    fetchScholarProfile(token).then(setProfile).catch(() => localStorage.removeItem(TOKEN_KEY)).finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    profile,
    loading,
    async login(identifier, password) {
      const session = await loginScholar(identifier, password);
      localStorage.setItem(TOKEN_KEY, session.access_token);
      setProfile(session.profile);
    },
    async register(email, username, password) {
      const session = await registerScholar(email, username, password);
      localStorage.setItem(TOKEN_KEY, session.access_token);
      setProfile(session.profile);
    },
    async updateProfile(input) {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) throw new Error("Scholar login required");
      setProfile(await updateScholarProfile(token, input));
    },
    async contributeResearch(input) {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) throw new Error("Scholar login required");
      await createScholarContribution(token, input);
    },
    logout() { localStorage.removeItem(TOKEN_KEY); setProfile(null); },
  }), [profile, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
