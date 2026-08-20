import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../auth";
import { navigate } from "../router";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(""); setSubmitting(true);
    try {
      if (mode === "login") await login(username || email, password);
      else await register(email, username, password);
      navigate("/profile");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally { setSubmitting(false); }
  }

  return <main className="auth-page">
    <section className="auth-card">
      <button className="auth-brand" onClick={() => navigate("/landing")}>[ MEDBRIDGE ]</button>
      <p className="eyebrow">{mode === "login" ? "SCHOLAR ACCESS" : "CREATE SCHOLAR PROFILE"}</p>
      <h1>{mode === "login" ? "Welcome back" : "Join as a scholar"}</h1>
      <p className="auth-copy">Guests can browse the platform without an account. Sign in to use the separate scholar profile.</p>
      <form onSubmit={submit} className="auth-form">
        {mode === "register" && <label>Email <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@gmail.com" required /></label>}
        <label>{mode === "login" ? "Email or username" : "Username"}<input value={username} onChange={(e) => setUsername(e.target.value)} placeholder={mode === "login" ? "name@gmail.com or scholar" : "researcher_name"} required /></label>
        <label>Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required /></label>
        {error && <p className="auth-error">{error}</p>}
        <button className="auth-submit" disabled={submitting}>{submitting ? "Please wait…" : mode === "login" ? "Sign in as scholar" : "Create scholar account"}</button>
      </form>
      <button className="auth-switch" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
        {mode === "login" ? "New here? Create a scholar account" : "Already have an account? Sign in"}
      </button>
      <button className="auth-guest" onClick={() => navigate("/")}>Continue in guest mode →</button>
    </section>
  </main>;
}
