import { getToken } from "./api/client";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";

export function App() {
  // Minimal gate: presence of a token decides which screen to show. React Query drives data.
  const authed = !!getToken();
  return authed ? <Dashboard /> : <Login />;
}
