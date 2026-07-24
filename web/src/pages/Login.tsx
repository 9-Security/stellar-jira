import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, verifyTotp } from "../api";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [loginToken, setLoginToken] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (loginToken) {
        await verifyTotp(loginToken, totpCode);
        navigate("/");
        return;
      }
      const res = await login(email, password);
      if (res.requires_totp && res.login_token) {
        setLoginToken(res.login_token);
        return;
      }
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登入失敗");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-box" onSubmit={onSubmit}>
        <div className="login-brand">
          <img src="/logo.png" alt="JJNET" />
          <h2>xMDR SOC 戰情中心</h2>
        </div>
        {error && <div className="error">{error}</div>}
        {!loginToken ? (
          <>
            <label className="muted">Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
            <label className="muted">密碼</label>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              required
            />
          </>
        ) : (
          <>
            <label className="muted">驗證碼 (2FA)</label>
            <input
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              inputMode="numeric"
              required
            />
          </>
        )}
        <button className="btn" type="submit" disabled={loading} style={{ width: "100%" }}>
          {loading ? "處理中…" : loginToken ? "驗證" : "登入"}
        </button>
      </form>
    </div>
  );
}
